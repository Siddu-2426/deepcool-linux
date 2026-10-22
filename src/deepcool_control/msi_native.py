"""Native MSI Mystic Light backend for 185-byte motherboards.

This is the control path recovered from MSI Center 2.x.  It talks to the
motherboard's HID RGB controller directly through ``/dev/hidraw``:

* report ``0x52`` (185 bytes) selects direct mode;
* report ``0x53`` (725 bytes) carries 240 RGB pixels.

Firmware effect modes are accepted by the controller but do not drive the
ARGB fans on the reference MS-7D77 board.  Effects are therefore rendered on
the host and streamed as per-LED frames, exactly like the standalone
``msi-mysticlight`` application.
"""

from __future__ import annotations

import errno
import fcntl
import glob
import math
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

VENDOR_ID = 0x1462
PRODUCT_ID = 0x7D77

REPORT_CONFIG = 0x52
REPORT_PER_LED = 0x53
CONFIG_LEN = 185
FRAME_LEN = 725
LEDS_TOTAL = 240
FPS = 30

PER_LED_HDR = bytes([REPORT_PER_LED, 0x25, 0x06, 0x00, 0x00])

# Config-packet offsets (verified on MS-7D77).
OFF_JRGB1 = 1
OFF_JPIPE1 = 11
OFF_JPIPE2 = 21
OFF_JRAINBOW1 = 31
OFF_JRAINBOW2 = 42
OFF_JCORSAIR = 53
OFF_JRGB2 = 174


@dataclass(frozen=True)
class MsiZone:
    key: str
    label: str
    offset: int
    start: int
    count: int
    packet_size: int = 10

    @property
    def end(self) -> int:
        return self.start + self.count


ZONES: tuple[MsiZone, ...] = (
    MsiZone("JRGB1", "JRGB1 (12 V)", OFF_JRGB1, 0, 1),
    MsiZone("JRGB2", "JRGB2 (12 V)", OFF_JRGB2, 1, 1),
    MsiZone("JRAINBOW1", "JRAINBOW1", OFF_JRAINBOW1, 2, 40, packet_size=11),
    MsiZone("JRAINBOW2", "JRAINBOW2", OFF_JRAINBOW2, 42, 40, packet_size=11),
)

ZONE_BY_KEY = {zone.key: zone for zone in ZONES}
ZONE_ALIASES = {
    "jrgb1": "JRGB1",
    "jrgb2": "JRGB2",
    "jrainbow1": "JRAINBOW1",
    "jrainbow2": "JRAINBOW2",
    "jargb1": "JRAINBOW1",
    "jargb2": "JRAINBOW2",
    "jargbv21": "JRAINBOW1",
    "jargbv22": "JRAINBOW2",
    "argb1": "JRAINBOW1",
    "argb2": "JRAINBOW2",
    "case": "JRAINBOW2",
}

# Display names exposed to the Lighting page.  The first group is rendered on
# the host; names from OpenRGB's MSI mode list are accepted as aliases.
MODES = (
    "Direct",
    "Static",
    "Breathing",
    "Flashing",
    "Double flashing",
    "Meteor",
    "Blink",
    "Color pulse",
    "Color wave",
    "Marquee",
    "Visor",
    "Rainbow flashing",
    "Stack",
    "Fire",
    "Rainbow",
    "Rainbow wave",
    "Color cycle",
    "Lightning",
    "Color ring",
    "Planetary",
    "Double meteor",
    "Energy",
    "Clock",
    "Off",
)

_MODE_TO_EFFECT = {
    "direct": "static",
    "static": "static",
    "breathing": "breathing",
    "flashing": "flashing",
    "double flashing": "double_flashing",
    "lightning": "lightning",
    "meteor": "meteor",
    "color ring": "color_ring",
    "planetary": "planetary",
    "double meteor": "double_meteor",
    "energy": "energy",
    "blink": "blink",
    "clock": "clock",
    "color pulse": "color_pulse",
    "color shift": "color_cycle",
    "color wave": "wave",
    "marquee": "marquee",
    "rainbow wave": "rainbow_wave",
    "visor": "visor",
    "rainbow flashing": "rainbow_flashing",
    "color ring double flashing": "double_flashing",
    "stack": "stack",
    "fire": "fire",
    "rainbow": "rainbow",
    "color cycle": "color_cycle",
    "off": "off",
}

ANIMATED_EFFECTS = frozenset(_MODE_TO_EFFECT.values()) - {"static", "off"}


def effect_for_mode(mode: str) -> str:
    """Map an OpenRGB/DeepCool mode name to a host-rendered effect."""

    return _MODE_TO_EFFECT.get(str(mode or "").strip().lower(), "static")


def resolve_zone(name: str | None) -> str | None:
    if not name:
        return None
    return ZONE_ALIASES.get(name.strip().lower().replace("-", "").replace("_", ""))


@dataclass(frozen=True)
class MsiDeviceInfo:
    path: str
    name: str
    serial: str

    @property
    def description(self) -> str:
        return "MSI Mystic Light (185-byte, native)"


def _read_uevent(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    result: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def find_devices(
    vid: int = VENDOR_ID, pid: int = PRODUCT_ID
) -> list[MsiDeviceInfo]:
    """Return connected MSI Mystic Light HID controllers."""

    found: list[MsiDeviceInfo] = []
    for node in sorted(glob.glob("/dev/hidraw*")):
        name = os.path.basename(node)
        uevent = _read_uevent(Path("/sys/class/hidraw") / name / "device" / "uevent")
        haystack = uevent.get("HID_ID", "").upper()
        if f"0003:{vid:08X}:{pid:08X}" not in haystack:
            continue
        serial = uevent.get("HID_UNIQ", "") or uevent.get("HID_PHYS", "")
        found.append(
            MsiDeviceInfo(
                path=node,
                name=uevent.get("HID_NAME", "MSI Mystic Light").strip()
                or "MSI Mystic Light",
                serial=serial,
            )
        )
    return found


def _ioc(direction: int, typ: str, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord(typ) << 8) | nr


_HIDIOCGFEATURE = lambda size: _ioc(3, "H", 0x07, size)  # noqa: E731
_HIDIOCSFEATURE = lambda size: _ioc(3, "H", 0x06, size)  # noqa: E731


class MsiHid:
    """Thin feature-report transport for one hidraw node."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.fd: int | None = None

    def open(self) -> None:
        if self.fd is None:
            try:
                self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EPERM):
                    raise PermissionError(
                        f"Cannot open {self.path}: permission denied"
                    ) from exc
                raise

    def close(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            finally:
                self.fd = None

    def __enter__(self) -> "MsiHid":
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def read_config(self) -> bytearray:
        self.open()
        assert self.fd is not None
        buf = bytearray([REPORT_CONFIG] + [0] * (CONFIG_LEN - 1))
        fcntl.ioctl(self.fd, _HIDIOCGFEATURE(CONFIG_LEN), buf)
        return buf

    def write_config(self, packet: Sequence[int]) -> None:
        if len(packet) != CONFIG_LEN:
            raise ValueError(f"config packet must be {CONFIG_LEN} bytes")
        buf = bytearray(packet)
        buf[0] = REPORT_CONFIG
        self._write(buf, CONFIG_LEN)

    def write_frame(self, pixels: Sequence[Sequence[int]]) -> None:
        if len(pixels) != LEDS_TOTAL:
            raise ValueError(f"expected {LEDS_TOTAL} pixels")
        buf = bytearray(FRAME_LEN)
        buf[:5] = PER_LED_HDR
        for index, pixel in enumerate(pixels):
            base = 5 + index * 3
            buf[base] = pixel[0] & 0xFF
            buf[base + 1] = pixel[1] & 0xFF
            buf[base + 2] = pixel[2] & 0xFF
        self._write(buf, FRAME_LEN)

    def _write(self, buf: bytearray, size: int) -> None:
        self.open()
        assert self.fd is not None
        try:
            result = fcntl.ioctl(self.fd, _HIDIOCSFEATURE(size), buf)
        except OSError as exc:
            raise OSError(f"feature report write failed: {exc}") from exc
        if result != size:
            raise OSError(f"short feature report write: {result}/{size}")

    def enable_direct_mode(self) -> None:
        packet = bytearray(CONFIG_LEN)
        packet[0] = REPORT_CONFIG

        def zone(
            offset: int,
            flags: int,
            *,
            cflags: int = 0x80,
            extra: int | None = None,
        ) -> None:
            packet[offset] = 1
            packet[offset + 4] = flags
            packet[offset + 8] = cflags
            if extra is not None:
                packet[offset + 10] = extra

        # This mirrors the full MSI Center packet, including unused headers.
        zone(OFF_JRGB1, 0x08)
        zone(OFF_JPIPE1, 0x2A)
        zone(OFF_JPIPE2, 0x2A)
        zone(OFF_JRAINBOW1, 0x29, extra=0x28)
        zone(OFF_JRAINBOW2, 0x29, extra=0x28)
        zone(OFF_JCORSAIR, 0x29, cflags=0x82)
        packet[OFF_JCORSAIR + 9] = 0x78
        zone(OFF_JCORSAIR + 11, 0x28)
        # Onboard sync master: direct mode, custom colour, ARGB sync group.
        packet[74:84] = bytes([0x25, 0, 0, 0, 0xA9, 0, 0, 0, 0x87, 0x04])
        zone(OFF_JRGB2, 0x2A)
        self.write_config(packet)


# ------------------------------------------------------------------ effects


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    h %= 1.0
    i = int(h * 6)
    f = h * 6 - i
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    r, g, b = (
        (v, t, p),
        (q, v, p),
        (p, v, t),
        (p, q, v),
        (t, p, v),
        (v, p, q),
    )[i % 6]
    return int(r * 255), int(g * 255), int(b * 255)


def _scale(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return (
        int(color[0] * factor),
        int(color[1] * factor),
        int(color[2] * factor),
    )


def _noise(index: int, t: float) -> float:
    """Deterministic 0..1 flicker without importing random."""

    value = math.sin(index * 12.9898 + t * 78.233) * 43758.5453
    return value - math.floor(value)


def render_effect(
    effect: str,
    color: tuple[int, int, int],
    count: int,
    *,
    speed: float = 0.5,
    t: float = 0.0,
) -> list[tuple[int, int, int]]:
    speed = max(0.05, speed)
    count = max(1, count)

    if effect == "off":
        return [(0, 0, 0)] * count
    if effect == "static":
        return [tuple(color)] * count
    if effect == "breathing":
        factor = 0.12 + 0.88 * (0.5 + 0.5 * math.sin(t * 2 * math.pi * speed))
        return [_scale(color, factor)] * count
    if effect == "flashing":
        on = int(t * 2 * speed) % 2 == 0
        return [tuple(color) if on else (0, 0, 0)] * count
    if effect == "double_flashing":
        cycle = (t * speed) % 1.2
        on = cycle < 0.12 or 0.24 <= cycle < 0.36
        return [tuple(color) if on else (0, 0, 0)] * count
    if effect == "blink":
        on = int(t * speed) % 2 == 0
        return [tuple(color) if on else (0, 0, 0)] * count
    if effect == "color_pulse":
        factor = 0.25 + 0.75 * (0.5 + 0.5 * math.sin(t * 2 * math.pi * speed))
        hue = (t * speed * 0.08) % 1.0
        tint = _hsv_to_rgb(hue, 0.35, 1.0)
        mixed = tuple(
            int((color[i] * (1 - 0.35)) + (tint[i] * 0.35)) for i in range(3)
        )
        return [_scale(mixed, factor)] * count
    if effect == "rainbow":
        shift = t * speed
        return [
            _hsv_to_rgb((index / count + shift) % 1.0, 1.0, 1.0)
            for index in range(count)
        ]
    if effect == "rainbow_flashing":
        shift = t * speed
        on = int(t * 2 * speed) % 2 == 0
        if not on:
            return [(0, 0, 0)] * count
        return [
            _hsv_to_rgb((index / count + shift) % 1.0, 1.0, 1.0)
            for index in range(count)
        ]
    if effect == "color_cycle":
        return [_hsv_to_rgb((t * speed) % 1.0, 1.0, 1.0)] * count
    if effect == "wave":
        shift = t * speed
        return [
            _hsv_to_rgb(
                ((index / count) * 0.5 + shift) % 1.0,
                1.0,
                0.45
                + 0.55
                * (0.5 + 0.5 * math.sin((index / count) * 6.283 + t * 4 * speed)),
            )
            for index in range(count)
        ]
    if effect == "meteor":
        head = (t * speed * count * 1.5) % (count + 8) - 4
        result = []
        for index in range(count):
            distance = head - index
            factor = max(0.0, 1.0 - abs(distance) / 5.0) if distance >= -0.5 else 0.0
            result.append(_scale(color, factor))
        return result
    if effect == "double_meteor":
        span = count + 8
        head1 = (t * speed * count * 1.5) % span - 4
        head2 = (head1 + count / 2) % span - 4
        result = []
        for index in range(count):
            factor = 0.0
            for head in (head1, head2):
                distance = head - index
                if distance >= -0.5:
                    factor = max(factor, max(0.0, 1.0 - abs(distance) / 5.0))
            result.append(_scale(color, factor))
        return result
    if effect == "marquee":
        position = int(t * speed * 12) % count
        result = [(0, 0, 0)] * count
        for offset in range(5):
            result[(position + offset) % count] = tuple(color)
        return result
    if effect == "visor":
        phase = (t * speed) % 2.0
        triangle = phase if phase <= 1.0 else 2.0 - phase
        position = int(triangle * (count - 1))
        result = [(0, 0, 0)] * count
        for offset, factor in ((-2, 0.2), (-1, 0.55), (0, 1.0), (1, 0.55), (2, 0.2)):
            index = position + offset
            if 0 <= index < count:
                result[index] = _scale(color, factor)
        return result
    if effect == "stack":
        step = int(t * speed * 4) % (count + 1)
        return [tuple(color) if index < step else (0, 0, 0) for index in range(count)]
    if effect == "fire":
        result = []
        for index in range(count):
            flicker = _noise(index, t * 6 * speed)
            heat = 0.35 + 0.65 * flicker
            if index > count * 0.65:
                heat *= 0.75
            red = min(255, int(255 * heat))
            green = min(255, int(110 * heat * heat))
            blue = min(255, int(20 * heat * heat * heat))
            result.append((red, green, blue))
        return result
    if effect == "lightning":
        strike = _noise(int(t * 8 * speed), t) > 0.92
        if strike:
            return [(255, 255, 255)] * count
        return [tuple(color)] * count
    if effect == "color_ring":
        return [
            _hsv_to_rgb(((index / count) + t * speed * 0.25) % 1.0, 1.0, 1.0)
            for index in range(count)
        ]
    if effect == "planetary":
        shift = t * speed
        return [_hsv_to_rgb((shift + index / count) % 1.0, 0.9, 0.9) for index in range(count)]
    if effect == "energy":
        shift = t * speed
        return [
            _scale(
                color,
                max(
                    0.05,
                    abs(
                        math.sin(
                            (index / count) * math.pi * 3 + t * 4 * speed + shift
                        )
                    ),
                ),
            )
            for index in range(count)
        ]
    if effect == "clock":
        return [tuple(color)] * count
    return [tuple(color)] * count


# ------------------------------------------------------------------ session


class NativeSession:
    """Owns the HID device and renders effects on the host."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self.device: MsiHid | None = None
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pixels: list[tuple[int, int, int]] = [(0, 0, 0)] * LEDS_TOTAL
        self.last_error = ""
        self.zones = {
            zone.key: {
                "enabled": False,
                "color": (255, 255, 255),
                "effect": "static",
                "brightness": 100,
            }
            for zone in ZONES
        }

    # -- public API ---------------------------------------------------
    def apply(
        self,
        zone_name: str | None,
        color: tuple[int, int, int],
        effect: str,
        *,
        brightness: int = 100,
        speed: int = 50,
    ) -> None:
        target = resolve_zone(zone_name)
        with self._lock:
            keys = [target] if target else [zone.key for zone in ZONES]
            for key in keys:
                self.zones[key].update(
                    enabled=True,
                    color=tuple(color),
                    effect=effect,
                    brightness=max(0, min(100, int(brightness))),
                    speed=max(1, min(100, int(speed))),
                )
            animated = any(
                self.zones[key]["enabled"]
                and self.zones[key]["effect"] in ANIMATED_EFFECTS
                for key in self.zones
            )
        if animated:
            # Open once on the caller's thread so permission errors reach the
            # UI instead of silently killing the animation worker.
            self._open()
            self._start()
        else:
            self._stop_thread()
            self._write_once()

    def stop(self) -> None:
        self._stop_thread()
        with self._lock:
            if self.device is not None:
                self.device.close()

    @property
    def running(self) -> bool:
        """Whether the animation worker is currently alive."""

        return self._thread is not None and self._thread.is_alive()

    def render(self, t: float | None = None) -> list[tuple[int, int, int]]:
        now = time.monotonic() if t is None else t
        pixels: list[tuple[int, int, int]] = [(0, 0, 0)] * LEDS_TOTAL
        with self._lock:
            state = {
                key: dict(value) for key, value in self.zones.items()
            }
        for zone in ZONES:
            config = state[zone.key]
            if not config["enabled"]:
                continue
            count = zone.count
            colors = render_effect(
                config["effect"],
                config["color"],
                count,
                speed=config.get("speed", 50) / 100.0,
                t=now,
            )
            factor = config["brightness"] / 100.0
            for index, color in enumerate(colors):
                target = zone.start + index
                if target < LEDS_TOTAL:
                    pixels[target] = _scale(color, factor)
        return pixels

    # -- internals ----------------------------------------------------
    def _open(self) -> MsiHid:
        path = self.path
        if path is None:
            devices = find_devices()
            if not devices:
                raise OSError("no MSI Mystic Light HID device found")
            path = devices[0].path
            self.path = path
        if self.device is None or self.device.path != path:
            if self.device is not None:
                self.device.close()
            self.device = MsiHid(path)
        self.device.open()
        return self.device

    def _write_once(self) -> None:
        error: OSError | None = None
        try:
            device = self._open()
            device.enable_direct_mode()
            pixels = self.render()
            device.write_frame(pixels)
            self._pixels = pixels
            self.last_error = ""
        except OSError as exc:
            self.last_error = str(exc)
            error = exc
        finally:
            if self.device is not None:
                self.device.close()
        if error is not None:
            raise error

    def _start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="deepcool-msi-rgb", daemon=True
        )
        self._thread.start()

    def _stop_thread(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.5)
        self._thread = None

    def _run(self) -> None:
        interval = 1.0 / FPS
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                device = self._open()
                device.enable_direct_mode()
                while not self._stop.is_set():
                    frame_started = time.monotonic()
                    pixels = self.render()
                    device.write_frame(pixels)
                    self._pixels = pixels
                    self.last_error = ""
                    delay = interval - (time.monotonic() - frame_started)
                    if delay > 0:
                        self._stop.wait(delay)
            except OSError as exc:
                self.last_error = str(exc)
                if self.device is not None:
                    self.device.close()
                self._stop.wait(1.0)
            if self._stop.is_set():
                break
            if time.monotonic() - started < 0.1:
                self._stop.wait(0.1)


_session: NativeSession | None = None
_session_lock = threading.Lock()


def session() -> NativeSession:
    global _session
    with _session_lock:
        if _session is None:
            _session = NativeSession()
        return _session


def stop_session() -> None:
    global _session
    with _session_lock:
        current = _session
    if current is not None:
        current.stop()
