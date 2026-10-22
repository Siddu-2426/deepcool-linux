"""Case lighting control through the OpenRGB command-line interface.

The DeepCool CH-series display exposes only the 64-byte HID report used by the
numeric panel.  Case and motherboard ARGB is controlled by OpenRGB through the
RGB controller it already supports (for example MSI Mystic Light).
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from . import msi_native

DEFAULT_COLOR = "#22D3EE"
DEFAULT_MODE = "Direct"
SAFE_MAX_BRIGHTNESS = 50
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_DEVICE_RE = re.compile(r"^\s*(\d+):\s*(.+?)\s*$")
_FIELD_RE = re.compile(r"^\s+([A-Za-z][A-Za-z ]*):\s*(.*?)\s*$")
_MODE_RE = re.compile(
    r"""
    \[(?:'([^']*)'|"([^"]*)"|([^\]]+))\]
    |'([^']*)'
    |"([^"]*)"
    |(\S+)
    """,
    re.VERBOSE,
)


class LightingError(RuntimeError):
    """Raised when OpenRGB is unavailable or a lighting update fails."""


@dataclass(frozen=True)
class LightingDevice:
    """A controller reported by ``openrgb --list-devices``."""

    index: int
    name: str
    type: str = ""
    description: str = ""
    location: str = ""
    serial: str = ""
    modes: tuple[str, ...] = ()
    active_mode: str = ""
    zones: tuple[str, ...] = ()
    leds: tuple[str, ...] = ()
    native: bool = False

    @property
    def label(self) -> str:
        return self.name

    @property
    def detail(self) -> str:
        parts = [self.type, self.location or self.description]
        return " · ".join(part for part in parts if part)


def find_binary() -> str | None:
    """Return the OpenRGB executable, honouring ``OPENRGB_BIN`` for testing."""

    override = os.environ.get("OPENRGB_BIN", "").strip()
    if override:
        return override
    return shutil.which("openrgb")


def available() -> bool:
    return find_binary() is not None


def is_mystic_light(device: LightingDevice) -> bool:
    """Return True for the MSI Mystic Light controller family."""

    text = f"{device.name} {device.description} {device.type}".lower()
    return "mystic light" in text


def risk_reasons(
    device: LightingDevice,
    *,
    mode: str | None = DEFAULT_MODE,
    brightness: int | None = None,
    zone_index: int | None = None,
) -> tuple[str, ...]:
    """Describe settings that have a history of hanging RGB controllers.

    These are warnings, not a guarantee of safety.  The MSI Mystic Light
    controller has bricked controllers after firmware effect writes and has
    caused at least one hard shutdown on the reference machine.
    """

    reasons: list[str] = []
    if device.native:
        # Native mode renders effects in user space and only writes the two
        # documented LED reports; there are no firmware effect commands.
        return ()
    if mode and mode != DEFAULT_MODE:
        if is_mystic_light(device):
            reasons.append(
                f"MSI Mystic Light effect mode {mode!r} instead of Direct"
            )
        else:
            reasons.append(f"effect mode {mode!r} instead of Direct")
    if zone_index is None:
        reasons.append("all zones in one write")
    if brightness is not None and int(brightness) > SAFE_MAX_BRIGHTNESS:
        reasons.append(
            f"brightness {int(brightness)}% (above the {SAFE_MAX_BRIGHTNESS}% limit)"
        )
    return tuple(reasons)


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "deepcool-control"


def log_path() -> Path:
    """Path of the append-only lighting command log."""

    return state_dir() / "lighting.log"


def command_text(command: Sequence[str]) -> str:
    """Return a copy/paste-safe representation of an OpenRGB command."""

    return shlex.join(str(part) for part in command)


def record_apply(
    command: Sequence[str],
    *,
    device: LightingDevice,
    color: str,
    mode: str | None = DEFAULT_MODE,
    brightness: int | None = None,
    zone_index: int | None = None,
    zone_name: str | None = None,
    path: Path | None = None,
) -> None:
    """Append the exact command to the lighting log before it is executed.

    Logging is best-effort: a read-only home directory must not prevent the
    requested lighting change.
    """

    target = path or log_path()
    if zone_name:
        zone = zone_name
    else:
        zone = "all zones" if zone_index is None else f"zone {zone_index}"
    level = "default" if brightness is None else f"{int(brightness)}%"
    line = (
        f"{time.strftime('%Y-%m-%d %H:%M:%S%z')} "
        f"device={device.name!r} ({device.index}) zone={zone} "
        f"mode={(mode or DEFAULT_MODE)!r} color={normalize_color(color)} "
        f"brightness={level} command={command_text(command)}\n"
    )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass


def normalize_color(value: str) -> str:
    """Accept ``RRGGBB`` or ``#RRGGBB`` and return ``#RRGGBB``."""

    text = str(value).strip()
    if not text.startswith("#"):
        text = f"#{text}"
    if COLOR_RE.fullmatch(text) is None:
        raise ValueError(f"Invalid RGB color: {value!r}")
    return text.upper()


def _split_names(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    try:
        return tuple(shlex.split(value))
    except ValueError:
        return tuple(value.split())


def _parse_modes(value: str) -> tuple[tuple[str, ...], str]:
    modes: list[str] = []
    active = ""
    for match in _MODE_RE.finditer(value):
        groups = match.groups()
        if groups[0] is not None or groups[1] is not None or groups[2] is not None:
            name = next(group for group in groups[:3] if group is not None).strip()
            if name:
                active = name
        else:
            name = next(group for group in groups[3:] if group is not None).strip()
        if name and name not in modes:
            modes.append(name)
    return tuple(modes), active


def _build_device(index: int, name: str, fields: dict[str, str]) -> LightingDevice:
    modes, active_mode = _parse_modes(fields.get("modes", ""))
    return LightingDevice(
        index=index,
        name=name,
        type=fields.get("type", ""),
        description=fields.get("description", ""),
        location=fields.get("location", "") or fields.get("version", ""),
        serial=fields.get("serial", ""),
        modes=modes,
        active_mode=active_mode,
        zones=_split_names(fields.get("zones", "")),
        leds=_split_names(fields.get("leds", "")),
    )


def parse_devices(output: str) -> list[LightingDevice]:
    """Parse the human-readable output of ``openrgb --list-devices``."""

    devices: list[LightingDevice] = []
    current: tuple[int, str] | None = None
    fields: dict[str, str] = {}

    for raw_line in output.splitlines():
        device_match = _DEVICE_RE.match(raw_line)
        if device_match is not None:
            if current is not None:
                devices.append(_build_device(current[0], current[1], fields))
            current = (int(device_match.group(1)), device_match.group(2).strip())
            fields = {}
            continue

        if current is None:
            continue
        field_match = _FIELD_RE.match(raw_line)
        if field_match is not None:
            fields[field_match.group(1).strip().lower()] = field_match.group(2).strip()

    if current is not None:
        devices.append(_build_device(current[0], current[1], fields))
    return devices


def _clean_output(*parts: str | None) -> str:
    lines: list[str] = []
    for part in parts:
        for line in (part or "").splitlines():
            line = line.strip()
            if not line or line.startswith("Connection attempt failed") or line.startswith("[i2c"):
                continue
            lines.append(line)
    return " ".join(lines)[-600:]


def _native_devices() -> list[LightingDevice]:
    """Build LightingDevice wrappers for connected MSI controllers."""

    try:
        infos = msi_native.find_devices()
    except OSError:
        return []
    devices: list[LightingDevice] = []
    for position, info in enumerate(infos):
        devices.append(
            LightingDevice(
                index=-1 - position,
                name=f"{info.name} (native)",
                type="Motherboard",
                description=info.description,
                location=info.path,
                serial=info.serial,
                modes=msi_native.MODES,
                active_mode="Direct",
                zones=tuple(zone.key for zone in msi_native.ZONES),
                native=True,
            )
        )
    return devices


def list_devices(binary: str | None = None, timeout: float = 10.0) -> list[LightingDevice]:
    """Return native MSI controllers plus controllers detected by OpenRGB."""

    native = _native_devices()
    executable = binary or find_binary()
    if executable is None:
        if native:
            return native
        raise LightingError("OpenRGB is not installed")
    try:
        result = subprocess.run(
            [executable, "--noautoconnect", "--list-devices"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        if native:
            return native
        raise LightingError("OpenRGB is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        if native:
            return native
        raise LightingError("OpenRGB did not respond in time") from exc
    except OSError as exc:
        if native:
            return native
        raise LightingError(f"Could not start OpenRGB: {exc}") from exc

    devices = parse_devices(result.stdout)
    if native:
        # The native path is the working one for these boards; hide the
        # duplicate OpenRGB entry so the Lighting page does not offer a
        # backend that cannot drive the fans.
        return native + [
            device for device in devices if not is_mystic_light(device)
        ]
    if devices:
        return devices
    if result.returncode != 0:
        detail = _clean_output(result.stdout, result.stderr)
        raise LightingError(detail or "OpenRGB could not detect any RGB devices")
    return []


def build_apply_command(
    device: LightingDevice,
    color: str,
    *,
    mode: str | None = DEFAULT_MODE,
    brightness: int | None = None,
    zone_index: int | None = None,
    binary: str | None = None,
) -> list[str]:
    """Build an ``openrgb`` command that applies a color to a device/zone."""

    executable = binary or find_binary() or "openrgb"
    command = [executable, "--noautoconnect", "--device", str(device.index)]
    if zone_index is not None:
        command.extend(["--zone", str(zone_index)])
    if mode:
        command.extend(["--mode", mode])
    command.extend(["--color", normalize_color(color).lstrip("#")])
    if brightness is not None:
        value = max(0, min(100, int(brightness)))
        command.extend(["--brightness", str(value)])
    return command


def apply_native(
    device: LightingDevice,
    color: str,
    *,
    mode: str | None = DEFAULT_MODE,
    brightness: int | None = None,
    zone_index: int | None = None,
    write_log: bool = True,
    log_file: Path | None = None,
) -> None:
    """Apply a colour/effect through the native MSI per-LED backend."""

    normalized = normalize_color(color)
    rgb = (
        int(normalized[1:3], 16),
        int(normalized[3:5], 16),
        int(normalized[5:7], 16),
    )
    effect = msi_native.effect_for_mode(mode or DEFAULT_MODE)
    zone_name = ""
    if zone_index is not None and 0 <= zone_index < len(device.zones):
        zone_name = device.zones[zone_index]
    level = 100 if brightness is None else max(0, min(100, int(brightness)))

    if write_log:
        command = [
            "native-msi",
            "--zone",
            zone_name or "all",
            "--effect",
            effect,
            "--color",
            normalized.lstrip("#"),
            "--brightness",
            str(level),
        ]
        record_apply(
            command,
            device=device,
            color=color,
            mode=mode,
            brightness=brightness,
            zone_index=zone_index,
            zone_name=zone_name or "all zones",
            path=log_file,
        )

    try:
        msi_native.session().apply(
            zone_name,
            rgb,
            effect,
            brightness=level,
        )
    except OSError as exc:
        raise LightingError(f"Native MSI write failed: {exc}") from exc


def stop_native() -> None:
    """Stop the native animation thread, if any."""

    msi_native.stop_session()


def apply_color(
    device: LightingDevice,
    color: str,
    *,
    mode: str | None = DEFAULT_MODE,
    brightness: int | None = None,
    zone_index: int | None = None,
    binary: str | None = None,
    timeout: float = 20.0,
    write_log: bool = True,
    log_file: Path | None = None,
) -> None:
    """Apply a colour through the native MSI path or OpenRGB.

    The exact command is written to :func:`log_path` before the write starts, so
    a shutdown during a firmware effect leaves evidence of what was sent.

    Raises:
        LightingError: if OpenRGB is missing, times out, or reports a failure.
        ValueError: if *color* is not a valid RGB hex color.
    """

    if device.native:
        apply_native(
            device,
            color,
            mode=mode,
            brightness=brightness,
            zone_index=zone_index,
            write_log=write_log,
            log_file=log_file,
        )
        return

    command = build_apply_command(
        device,
        color,
        mode=mode,
        brightness=brightness,
        zone_index=zone_index,
        binary=binary,
    )
    if write_log:
        record_apply(
            command,
            device=device,
            color=color,
            mode=mode,
            brightness=brightness,
            zone_index=zone_index,
            path=log_file,
        )
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise LightingError("OpenRGB is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise LightingError("OpenRGB did not respond in time") from exc
    except OSError as exc:
        raise LightingError(f"Could not start OpenRGB: {exc}") from exc

    if result.returncode != 0:
        detail = _clean_output(result.stdout, result.stderr)
        raise LightingError(detail or f"OpenRGB exited with status {result.returncode}")
