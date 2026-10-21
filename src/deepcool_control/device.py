"""hidraw access and DeepCool device discovery."""

from __future__ import annotations

import errno
import fcntl
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .protocol import PACKET_SIZE, build_animation_packet

DEEPCOOL_VID = 0x3633

# PID -> product name.  Only the CH-series protocol entries are write-safe here.
KNOWN_PRODUCTS: dict[int, str] = {
    0x0001: "AK400 DIGITAL",
    0x0002: "AK620 DIGITAL",
    0x0003: "AK500 DIGITAL",
    0x0004: "AK500S DIGITAL",
    0x0005: "CH560 DIGITAL",
    0x0006: "LS520 SE DIGITAL",
    0x0007: "MORPHEUS",
    0x0008: "AG400 DIGITAL",
    0x0009: "MYSTIQUE",
    0x000A: "LD240",
    0x000B: "LD360",
    0x000D: "LQ240",
    0x000E: "LQ360",
    0x0013: "CH170 DIGITAL",
    0x0015: "CH360 DIGITAL",
    0x0016: "CH270 DIGITAL",
    0x001B: "CH690 DIGITAL",
    0x0021: "AK620 G2 DIGITAL",
}

# Products that use the same 64-byte report as the CH360.
CH_SERIES_PIDS = {0x0005, 0x0007, 0x0015}

HIDRAW_ROOT = Path("/sys/class/hidraw")


class DeviceError(RuntimeError):
    pass


class PermissionDenied(DeviceError):
    pass


@dataclass(frozen=True)
class DeviceInfo:
    path: str
    vid: int
    pid: int
    name: str
    serial: str
    product: str

    @property
    def supported(self) -> bool:
        return self.vid == DEEPCOOL_VID and self.pid in CH_SERIES_PIDS

    @property
    def display_name(self) -> str:
        return self.product or self.name or f"DeepCool {self.pid:04X}"

    @property
    def key(self) -> str:
        return f"{self.vid:04x}:{self.pid:04x}:{self.serial or self.path}"


def _read(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return default


def _parse_uevent(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in _read(path).splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def _usb_parent(hid_device: Path) -> Path | None:
    """Walk up from the HID device node to the USB device directory."""

    for parent in [hid_device, *hid_device.parents]:
        if (parent / "idVendor").exists() and (parent / "idProduct").exists():
            return parent
    return None


def _info_from_hidraw(entry: Path) -> DeviceInfo | None:
    uevent = _parse_uevent(entry / "device" / "uevent")
    hid_id = uevent.get("HID_ID", "")
    match = re.match(r"^([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+)$", hid_id)
    if not match:
        return None
    _bus, vid, pid = (int(part, 16) for part in match.groups())
    if vid != DEEPCOOL_VID:
        return None

    hid_name = uevent.get("HID_NAME", "")
    usb = _usb_parent((entry / "device").resolve())
    serial = _read(usb / "serial") if usb else ""
    product = KNOWN_PRODUCTS.get(pid, "")
    name = hid_name or product or f"DeepCool {pid:04X}"

    return DeviceInfo(
        path=f"/dev/{entry.name}",
        vid=vid,
        pid=pid,
        name=name,
        serial=serial,
        product=product,
    )


def discover_devices() -> list[DeviceInfo]:
    """Return every connected DeepCool hidraw device, including unsupported ones."""

    devices: list[DeviceInfo] = []
    try:
        entries = sorted(HIDRAW_ROOT.glob("hidraw*"))
    except OSError:
        return devices
    for entry in entries:
        try:
            info = _info_from_hidraw(entry)
        except (OSError, ValueError):
            continue
        if info is not None:
            devices.append(info)
    return devices


def find_supported_device() -> DeviceInfo | None:
    for info in discover_devices():
        if info.supported:
            return info
    return None


class ControlLock:
    """Advisory lock that keeps the GUI and the systemd daemon from fighting."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_lock_path()
        self._fd: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        self._fd = fd

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    @property
    def held(self) -> bool:
        return self._fd is not None


def default_lock_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "deepcool-control" / "control.lock"
    return Path(f"/tmp/deepcool-control-{os.getuid()}") / "control.lock"


class DeviceSession:
    """Owns the hidraw file descriptor and the inter-process lock."""

    def __init__(self, info: DeviceInfo, lock_path: Path | None = None) -> None:
        self.info = info
        self.lock = ControlLock(lock_path)
        self._fd: int | None = None
        self.last_error = ""

    def open(self) -> None:
        self.lock.acquire()
        try:
            # Keep the GUI responsive if the panel stops draining its interrupt
            # endpoint.  A blocking hidraw write can otherwise freeze the whole
            # GTK main loop and stop the display from being refreshed.
            fd = os.open(self.info.path, os.O_RDWR | os.O_NONBLOCK)
        except OSError as exc:
            self.lock.release()
            if exc.errno in (errno.EACCES, errno.EPERM):
                raise PermissionDenied(
                    f"Cannot open {self.info.path}: permission denied"
                ) from exc
            raise DeviceError(f"Cannot open {self.info.path}: {exc.strerror}") from exc
        self._fd = fd
        try:
            self.start_animation()
        except DeviceError:
            self.close()
            raise

    def start_animation(self) -> None:
        self.write(build_animation_packet())

    def write(self, data: bytes) -> None:
        if len(data) != PACKET_SIZE:
            raise ValueError(f"expected {PACKET_SIZE} bytes, got {len(data)}")
        if self._fd is None:
            raise DeviceError("device is not open")
        # A 64-byte HID report can be accepted immediately; retry briefly if the
        # kernel reports a full interrupt-out queue.
        for attempt in range(6):
            try:
                written = os.write(self._fd, data)
                if written == PACKET_SIZE:
                    return
                raise DeviceError(f"short HID write ({written}/{PACKET_SIZE})")
            except OSError as exc:
                if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    time.sleep(0.01 * (attempt + 1))
                    continue
                if exc.errno in (errno.ENODEV, errno.EIO, errno.EPIPE):
                    raise DeviceError("the display was disconnected") from exc
                raise DeviceError(f"HID write failed: {exc.strerror}") from exc
        raise DeviceError("HID write timed out")

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None
        self.lock.release()

    def __enter__(self) -> "DeviceSession":
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
