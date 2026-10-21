"""Sensor discovery and sampling for the dashboard and display packets."""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import psutil

HWMON_ROOT = Path("/sys/class/hwmon")
DRM_ROOT = Path("/sys/class/drm")

CPU_CHIPS = {
    "k10temp",
    "coretemp",
    "zenpower",
    "cpu_thermal",
    "soc_thermal",
    "acpitz",
}

SYSTEM_CHIPS = {
    "nvme",
    "amdgpu",
    "r8169",
    "spd5118",
    "mt7921_phy0",
    "iwlwifi",
    "drivetemp",
}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _read_int(path: Path) -> int | None:
    raw = _read_text(path)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _temp_c(path: Path) -> float | None:
    value = _read_int(path)
    if value is None:
        return None
    return value / 1000.0


@dataclass(frozen=True)
class TempSensor:
    id: str
    label: str
    chip: str
    path: str
    value: float | None = None

    @property
    def display(self) -> str:
        if self.value is None:
            return self.label
        return f"{self.label} · {self.value:.1f} °C"


@dataclass(frozen=True)
class GpuInfo:
    id: str
    label: str
    kind: str  # "nvidia" | "amd" | "intel"
    index: int = 0
    temp_path: str = ""
    usage_path: str = ""
    name_path: str = ""


@dataclass
class GpuReading:
    name: str
    temperature: float | None = None
    usage: float | None = None
    memory_used: int | None = None
    memory_total: int | None = None


@dataclass
class Snapshot:
    cpu_temperature: float | None = None
    cpu_usage: float = 0.0
    cpu_frequency: float | None = None
    cpu_name: str = "CPU"
    cpu_model: str = "CPU"
    gpu_temperature: float | None = None
    gpu_usage: float | None = None
    gpu_name: str = "GPU"
    gpu_memory_used: int | None = None
    gpu_memory_total: int | None = None
    ram_usage: float = 0.0
    system_sensors: list[TempSensor] = field(default_factory=list)


def _chip_name(hwmon: Path) -> str:
    return _read_text(hwmon / "name") or hwmon.name


@lru_cache(maxsize=1)
def cpu_model_name() -> str:
    """Return a friendly processor name for the dashboard."""

    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.lower().startswith("model name"):
                    value = line.split(":", 1)[1].strip()
                    if value:
                        return value
    except OSError:
        pass
    try:
        import platform

        return platform.processor() or "CPU"
    except Exception:
        return "CPU"


def _temp_sensors_for(hwmon: Path) -> list[TempSensor]:
    chip = _chip_name(hwmon)
    sensors: list[TempSensor] = []
    for path in sorted(hwmon.glob("temp*_input")):
        stem = path.name.removesuffix("_input")
        label = _read_text(hwmon / f"{stem}_label")
        if not label:
            label = chip
        sensors.append(
            TempSensor(
                id=f"{chip}:{stem}",
                label=label,
                chip=chip,
                path=str(path),
                value=_temp_c(path),
            )
        )
    return sensors


def list_cpu_temp_sensors() -> list[TempSensor]:
    sensors: list[TempSensor] = []
    for hwmon in sorted(HWMON_ROOT.glob("hwmon*")):
        chip = _chip_name(hwmon)
        if chip in CPU_CHIPS:
            sensors.extend(_temp_sensors_for(hwmon))
    # Prefer the package/Tctl sensor when labels make the choice obvious.
    order = {"tctl": 0, "package id 0": 1, "tccd1": 2, "tdie": 0}
    sensors.sort(key=lambda item: (order.get(item.label.lower(), 5), item.id))
    return sensors


def list_system_sensors() -> list[TempSensor]:
    sensors: list[TempSensor] = []
    for hwmon in sorted(HWMON_ROOT.glob("hwmon*")):
        chip = _chip_name(hwmon)
        if chip in CPU_CHIPS or chip not in SYSTEM_CHIPS:
            continue
        for sensor in _temp_sensors_for(hwmon):
            # For NVMe and similar chips, one composite average is enough.
            if sensor.label.lower() in ("composite", chip, "edge"):
                sensors.append(sensor)
    return sensors


def pick_cpu_sensor(sensor_id: str = "") -> TempSensor | None:
    sensors = list_cpu_temp_sensors()
    if not sensors:
        return None
    if sensor_id:
        for sensor in sensors:
            if sensor.id == sensor_id:
                return sensor
    preferred = ("tctl", "package id 0", "tdie")
    for wanted in preferred:
        for sensor in sensors:
            if sensor.label.lower() == wanted:
                return sensor
    return sensors[0]


def cpu_summary(sensor_id: str = "") -> tuple[float | None, str]:
    sensor = pick_cpu_sensor(sensor_id)
    if sensor is None:
        return None, "CPU"
    value = _temp_c(Path(sensor.path))
    return value, sensor.label


def _nvidia_gpus() -> list[GpuInfo]:
    if not shutil.which("nvidia-smi"):
        return []
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    gpus: list[GpuInfo] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        index_text, _, name = line.partition(",")
        try:
            index = int(index_text.strip())
        except ValueError:
            continue
        gpus.append(
            GpuInfo(
                id=f"nvidia:{index}",
                label=name.strip() or f"NVIDIA GPU {index}",
                kind="nvidia",
                index=index,
            )
        )
    return gpus


def _drm_gpus() -> list[GpuInfo]:
    gpus: list[GpuInfo] = []
    for card in sorted(DRM_ROOT.glob("card[0-9]*")):
        device = card / "device"
        vendor = _read_text(device / "vendor").lower()
        if vendor not in ("0x1002", "0x8086"):
            continue
        hwmons = sorted((device / "hwmon").glob("hwmon*")) if (device / "hwmon").exists() else []
        temp_path = ""
        for hwmon in hwmons:
            candidate = hwmon / "temp1_input"
            if candidate.exists():
                temp_path = str(candidate)
                break
        usage_path = device / "gpu_busy_percent"
        name_path = device / "product_name"
        vendor_name = "AMD" if vendor == "0x1002" else "Intel"
        name = _read_text(name_path) if name_path.exists() else ""
        label = name or f"{vendor_name} GPU ({card.name})"
        gpus.append(
            GpuInfo(
                id=f"{vendor_name.lower()}:{card.name}",
                label=label,
                kind="amd" if vendor == "0x1002" else "intel",
                temp_path=temp_path,
                usage_path=str(usage_path) if usage_path.exists() else "",
                name_path=str(name_path) if name_path.exists() else "",
            )
        )
    return gpus


def list_gpus() -> list[GpuInfo]:
    # Discrete NVIDIA cards first; integrated GPUs remain selectable.
    return _nvidia_gpus() + _drm_gpus()


def _nvidia_readings() -> dict[int, GpuReading]:
    if not shutil.which("nvidia-smi"):
        return {}
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,temperature.gpu,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0:
        return {}
    readings: dict[int, GpuReading] = {}
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) < 6:
            continue
        try:
            index = int(row[0].strip())
        except ValueError:
            continue
        def number(value: str) -> float | None:
            value = value.strip()
            if value in ("", "[N/A]", "N/A"):
                return None
            try:
                return float(value)
            except ValueError:
                return None
        readings[index] = GpuReading(
            name=row[1].strip(),
            temperature=number(row[2]),
            usage=number(row[3]),
            memory_used=int(number(row[4]) or 0) if number(row[4]) is not None else None,
            memory_total=int(number(row[5]) or 0) if number(row[5]) is not None else None,
        )
    return readings


def read_gpu(info: GpuInfo | None) -> GpuReading | None:
    if info is None:
        return None
    if info.kind == "nvidia":
        return _nvidia_readings().get(info.index)
    temp = _temp_c(Path(info.temp_path)) if info.temp_path else None
    usage_value = _read_int(Path(info.usage_path)) if info.usage_path else None
    usage = float(usage_value) if usage_value is not None else None
    name = info.label
    if info.name_path:
        name = _read_text(Path(info.name_path)) or name
    return GpuReading(name=name, temperature=temp, usage=usage)


def default_gpu(gpus: list[GpuInfo]) -> GpuInfo | None:
    if not gpus:
        return None
    for gpu in gpus:
        if gpu.kind == "nvidia":
            return gpu
    return gpus[0]


class SensorReader:
    """Small stateful sampler that keeps the expensive GPU query cached."""

    def __init__(self, cpu_sensor: str = "", gpu_id: str = "") -> None:
        self.cpu_sensor = cpu_sensor
        self.gpus = list_gpus()
        self.gpu = next((gpu for gpu in self.gpus if gpu.id == gpu_id), None)
        if self.gpu is None:
            self.gpu = default_gpu(self.gpus)
        psutil.cpu_percent(interval=None)  # prime the non-blocking counter
        self._last_gpu: GpuReading | None = None
        self._last_gpu_at = 0.0

    def configure(self, cpu_sensor: str | None = None, gpu_id: str | None = None) -> None:
        if cpu_sensor is not None:
            self.cpu_sensor = cpu_sensor
        if gpu_id is not None:
            self.gpus = list_gpus()
            self.gpu = next((gpu for gpu in self.gpus if gpu.id == gpu_id), None)
            if self.gpu is None:
                self.gpu = default_gpu(self.gpus)
            self._last_gpu = None
            self._last_gpu_at = 0.0

    def read(self, refresh_gpu: bool = True) -> Snapshot:
        cpu_temp, cpu_label = cpu_summary(self.cpu_sensor)
        usage = float(psutil.cpu_percent(interval=None))
        try:
            freq = psutil.cpu_freq()
            frequency = float(freq.current) if freq else None
        except (OSError, AttributeError):
            frequency = None

        if refresh_gpu and time.monotonic() - self._last_gpu_at >= 1.5:
            self._last_gpu = read_gpu(self.gpu)
            self._last_gpu_at = time.monotonic()
        gpu = self._last_gpu

        return Snapshot(
            cpu_temperature=cpu_temp,
            cpu_usage=usage,
            cpu_frequency=frequency,
            cpu_name=cpu_label,
            cpu_model=cpu_model_name(),
            gpu_temperature=gpu.temperature if gpu else None,
            gpu_usage=gpu.usage if gpu else None,
            gpu_name=gpu.name if gpu else (self.gpu.label if self.gpu else "GPU"),
            gpu_memory_used=gpu.memory_used if gpu else None,
            gpu_memory_total=gpu.memory_total if gpu else None,
            ram_usage=float(psutil.virtual_memory().percent),
            system_sensors=list_system_sensors(),
        )
