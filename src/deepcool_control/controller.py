"""Application controller: device ownership, sampling and packet scheduling."""

from __future__ import annotations

import os
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, GObject  # noqa: E402

from . import system  # noqa: E402
from .config import Config  # noqa: E402
from .device import (  # noqa: E402
    DeviceError,
    DeviceInfo,
    DeviceSession,
    PermissionDenied,
    discover_devices,
    find_supported_device,
)
from .protocol import build_status_packet, convert_temperature  # noqa: E402
from .sensors import SensorReader, Snapshot  # noqa: E402

HISTORY = 60


class Controller(GObject.Object):
    __gsignals__ = {
        "toast": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        "config-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "metrics-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    cpu_temp = GObject.Property(type=float, default=0.0)
    cpu_usage = GObject.Property(type=float, default=0.0)
    cpu_frequency = GObject.Property(type=float, default=0.0)
    gpu_temp = GObject.Property(type=float, default=0.0)
    gpu_usage = GObject.Property(type=float, default=0.0)
    ram_usage = GObject.Property(type=float, default=0.0)
    gpu_available = GObject.Property(type=bool, default=False)
    connected = GObject.Property(type=bool, default=False)
    writable = GObject.Property(type=bool, default=False)
    permission_required = GObject.Property(type=bool, default=False)
    service_owner = GObject.Property(type=bool, default=False)
    demo = GObject.Property(type=bool, default=False)
    device_label = GObject.Property(type=str, default="No display found")
    device_serial = GObject.Property(type=str, default="")
    unsupported_label = GObject.Property(type=str, default="")
    cpu_model = GObject.Property(type=str, default="CPU")
    gpu_name = GObject.Property(type=str, default="GPU")
    cpu_sensor_label = GObject.Property(type=str, default="CPU")
    effective_primary = GObject.Property(type=str, default="cpu_temp")
    effective_secondary = GObject.Property(type=str, default="gpu_temp")
    last_write = GObject.Property(type=str, default="Not sent yet")

    def __init__(self, config: Config | None = None) -> None:
        super().__init__()
        self.config = (config or Config.load()).validate()
        self.reader = SensorReader(self.config.cpu_sensor, self.config.gpu_sensor)
        self.session: DeviceSession | None = None
        self.session_key = ""
        self.info: DeviceInfo | None = None
        self.snapshot = Snapshot()
        self.history = {
            "cpu_temp": deque(maxlen=HISTORY),
            "cpu_usage": deque(maxlen=HISTORY),
            "gpu_temp": deque(maxlen=HISTORY),
            "gpu_usage": deque(maxlen=HISTORY),
        }
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sensors")
        self._sensor_future: Future[Snapshot] | None = None
        self._timers: list[int] = []
        self._last_write_at = 0.0
        self._auto_started = time.monotonic()
        self._auto_usage = False
        self._secondary_auto_started = time.monotonic()
        self._secondary_auto_usage = False
        self._closing = False
        self._demo = os.environ.get("DEEPCOOL_DEMO") == "1"
        self.demo = self._demo
        if self._demo:
            self.device_label = "CH360 DIGITAL"
            self.device_serial = "DEMO-0000"
            self.connected = True
            self.writable = True
            self.unsupported_label = ""

    # ------------------------------------------------------------------ setup
    def start(self) -> None:
        # Register the timers first.  If the initial device probe or packet
        # write fails, the periodic retry loop still runs instead of leaving
        # the app open with no way to recover.
        self._timers.append(GLib.timeout_add(1000, self._sensor_tick))
        self._timers.append(GLib.timeout_add(200, self._write_tick))
        self._timers.append(GLib.timeout_add(2500, self._scan_tick))
        self.scan_device()
        self._sensor_tick()

    def shutdown(self) -> None:
        self._closing = True
        for timer in self._timers:
            GLib.source_remove(timer)
        self._timers.clear()
        self._close_session()
        self._executor.shutdown(wait=False, cancel_futures=True)

    # --------------------------------------------------------------- sampling
    def _sensor_tick(self) -> bool:
        if self._closing:
            return False
        if self._sensor_future is None or self._sensor_future.done():
            self._sensor_future = self._executor.submit(self.reader.read, True)
            self._sensor_future.add_done_callback(self._sensor_done)
        return True

    def _sensor_done(self, future: Future[Snapshot]) -> None:
        try:
            snapshot = future.result()
        except Exception as exc:  # pragma: no cover - defensive
            GLib.idle_add(self._sensor_failed, str(exc))
            return
        GLib.idle_add(self._apply_snapshot, snapshot)

    def _sensor_failed(self, message: str) -> bool:
        if not self._closing:
            self.emit("toast", f"Could not read sensors: {message}", "error")
        self._sensor_future = None
        return False

    def _apply_snapshot(self, snapshot: Snapshot) -> bool:
        if self._closing:
            return False
        self._sensor_future = None
        self.snapshot = snapshot
        self.cpu_temp = float(snapshot.cpu_temperature or 0.0)
        self.cpu_usage = float(snapshot.cpu_usage or 0.0)
        self.cpu_frequency = float(snapshot.cpu_frequency or 0.0)
        self.ram_usage = float(snapshot.ram_usage or 0.0)
        self.cpu_sensor_label = snapshot.cpu_name or "CPU"
        self.cpu_model = snapshot.cpu_model or "CPU"
        self.gpu_available = snapshot.gpu_temperature is not None or snapshot.gpu_usage is not None
        self.gpu_temp = float(snapshot.gpu_temperature or 0.0)
        self.gpu_usage = float(snapshot.gpu_usage or 0.0)
        self.gpu_name = snapshot.gpu_name or "GPU"
        self.history["cpu_temp"].append(self.cpu_temp)
        self.history["cpu_usage"].append(self.cpu_usage)
        self.history["gpu_temp"].append(self.gpu_temp)
        self.history["gpu_usage"].append(self.gpu_usage)
        self._resolve_modes()
        self.emit("metrics-changed")
        return False

    # ----------------------------------------------------------------- device
    def _scan_tick(self) -> bool:
        if self._closing:
            return False
        self.scan_device()
        return True

    def scan_device(self) -> None:
        if self._demo:
            return
        devices = discover_devices()
        supported = next((item for item in devices if item.supported), None)
        unsupported = next((item for item in devices if not item.supported), None)

        if supported is None:
            if self.session is not None:
                self._close_session()
            self.connected = False
            self.writable = False
            self.permission_required = False
            self.service_owner = False
            self.device_label = "No display found"
            self.device_serial = ""
            self.unsupported_label = (
                f"{unsupported.display_name} is connected but not supported yet"
                if unsupported
                else ""
            )
            self.emit("state-changed")
            return

        self.unsupported_label = ""
        self.device_label = supported.display_name
        self.device_serial = supported.serial
        if self.session is not None and self.session_key == supported.key:
            self.connected = True
            self.emit("state-changed")
            return

        if self.session is not None:
            self._close_session()
        self._open_device(supported)
        self.emit("state-changed")

    def _open_device(self, info: DeviceInfo) -> None:
        session = DeviceSession(info)
        try:
            session.open()
        except BlockingIOError:
            self.connected = True
            self.writable = False
            self.service_owner = True
            self.permission_required = False
            self.session = None
            self.emit("toast", "The background service is updating the display", "info")
            return
        except PermissionDenied:
            self.connected = True
            self.writable = False
            self.service_owner = False
            self.permission_required = True
            self.session = None
            self.emit("toast", "Permission needed to access the display", "warning")
            return
        except DeviceError as exc:
            self.connected = False
            self.writable = False
            self.session = None
            self.emit("toast", str(exc), "error")
            return

        self.session = session
        self.session_key = info.key
        self.info = info
        self.connected = True
        self.writable = True
        self.permission_required = False
        self.service_owner = False
        self._last_write_at = 0.0
        self._auto_started = time.monotonic()
        self._secondary_auto_started = time.monotonic()
        try:
            self.send_now()
        except Exception as exc:  # keep the periodic recovery loop alive
            self.emit("toast", f"Display update failed: {exc}", "error")

    def _close_session(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None
            self.session_key = ""
        self.writable = False

    def take_over(self) -> None:
        ok, message = system.stop_service()
        if not ok:
            self.emit("toast", message, "error")
            return
        self._close_session()
        self.service_owner = False
        self.emit("toast", "Background service stopped", "success")
        GLib.timeout_add(250, self._retry_open)

    def _retry_open(self) -> bool:
        if self._demo:
            return False
        info = find_supported_device()
        if info is not None:
            self._open_device(info)
            self.emit("state-changed")
        return False

    def install_permissions(self) -> None:
        # Refresh the rule even if the file exists: the ACL may not have been
        # applied to a display that was already plugged in.
        ok, message = system.install_udev_rule(force=not self.writable)
        self.emit("toast", message, "success" if ok else "error")
        if ok:
            GLib.timeout_add(900, self._retry_open)

    def toggle_service(self, enabled: bool) -> bool:
        if enabled:
            # The daemon owns both hidraw devices while it runs, including
            # the native MSI lighting animation.
            from . import lighting

            lighting.stop_native()
            self._close_session()
            ok, message = system.set_service(True)
        else:
            ok, message = system.set_service(False)
        self.emit("toast", message, "success" if ok else "error")
        if ok:
            self.config.service = enabled
            self.config.save()
            self.emit("config-changed")
            if enabled:
                # Do not race the new daemon for the display.  The GUI keeps
                # showing live state but lets systemd write the packets.
                self.service_owner = True
                self.writable = False
                self.emit("state-changed")
            else:
                GLib.timeout_add(500, self._retry_open)
        return ok

    def toggle_autostart(self, enabled: bool) -> bool:
        ok, message = system.set_autostart(enabled)
        self.emit("toast", message, "success" if ok else "error")
        if ok:
            self.config.autostart = enabled
            self.config.save()
            self.emit("config-changed")
        return ok

    # ------------------------------------------------------------------ output
    def _resolve_modes(self) -> None:
        now = time.monotonic()
        if self.config.primary == "auto":
            if now - self._auto_started >= self.config.auto_cycle_s:
                self._auto_usage = not self._auto_usage
                self._auto_started = now
            primary = "cpu_usage" if self._auto_usage else "cpu_temp"
        else:
            primary = self.config.primary
            self._auto_usage = False

        if self.config.secondary == "auto":
            if now - self._secondary_auto_started >= self.config.auto_cycle_s:
                self._secondary_auto_usage = not self._secondary_auto_usage
                self._secondary_auto_started = now
            secondary = "gpu_usage" if self._secondary_auto_usage else "gpu_temp"
        else:
            secondary = self.config.secondary
            self._secondary_auto_usage = False

        changed = primary != self.effective_primary or secondary != self.effective_secondary
        self.effective_primary = primary
        self.effective_secondary = secondary
        if changed and self.config.animations:
            self.notify("effective-primary")
            self.notify("effective-secondary")

    def _write_tick(self) -> bool:
        if self._closing:
            return False
        if not self._demo and (not self.writable or self.session is None):
            return True
        self._resolve_modes()
        interval = self.config.interval_ms / 1000.0
        now = time.monotonic()
        if now - self._last_write_at < interval:
            return True
        self._last_write_at = now
        try:
            self.send_now(reset_timer=False)
        except Exception as exc:  # defensive: never let the timer disappear
            self.emit("toast", f"Display update failed: {exc}", "error")
            self._close_session()
            self.connected = False
            self.emit("state-changed")
        return True

    def _values_for(self, mode: str) -> tuple[float, float]:
        """Return (display value, usage percentage) for a readout mode."""

        snapshot = self.snapshot
        if mode in ("cpu_temp",):
            celsius = snapshot.cpu_temperature
            if celsius is None:
                return 0.0, snapshot.cpu_usage or 0.0
            return convert_temperature(celsius, self.config.fahrenheit), snapshot.cpu_usage or 0.0
        if mode == "cpu_usage":
            return snapshot.cpu_usage or 0.0, snapshot.cpu_usage or 0.0
        if mode == "gpu_temp":
            celsius = snapshot.gpu_temperature
            if celsius is None:
                return 0.0, snapshot.gpu_usage or 0.0
            return convert_temperature(celsius, self.config.fahrenheit), snapshot.gpu_usage or 0.0
        if mode == "gpu_usage":
            value = snapshot.gpu_usage
            return (value if value is not None else 0.0), (value or 0.0)
        return 0.0, 0.0

    def send_now(self, reset_timer: bool = True) -> None:
        if self._demo:
            self._resolve_modes()
            self.last_write = f"{time.strftime('%H:%M:%S')} · demo"
            if reset_timer:
                self._last_write_at = time.monotonic()
            return
        if not self.writable or self.session is None:
            return
        self._resolve_modes()
        primary_value, primary_percent = self._values_for(self.effective_primary)
        if self.effective_secondary == "off":
            secondary_value = secondary_percent = 0.0
        else:
            secondary_value, secondary_percent = self._values_for(self.effective_secondary)
        packet = build_status_packet(
            primary_mode=self.effective_primary,
            primary_value=primary_value,
            primary_percent=primary_percent,
            secondary_mode=self.effective_secondary,
            secondary_value=secondary_value,
            secondary_percent=secondary_percent,
            fahrenheit=self.config.fahrenheit,
        )
        try:
            self.session.write(packet)
        except DeviceError as exc:
            self.emit("toast", str(exc), "error")
            self._close_session()
            self.connected = False
            self.emit("state-changed")
            return
        self.last_write = time.strftime("%H:%M:%S")
        if reset_timer:
            self._last_write_at = time.monotonic()

    # ----------------------------------------------------------------- config
    def configure(self, **changes: object) -> None:
        notify_output = False
        for key, value in changes.items():
            if not hasattr(self.config, key):
                continue
            if key in ("autostart", "service"):
                continue
            setattr(self.config, key, value)
        self.config.validate()
        self.config.save()
        if "cpu_sensor" in changes or "gpu_sensor" in changes:
            self.reader.configure(self.config.cpu_sensor, self.config.gpu_sensor)
        notify_output = any(
            key in changes
            for key in ("primary", "secondary", "fahrenheit", "interval_ms", "auto_cycle_s")
        )
        if "primary" in changes:
            self._auto_started = time.monotonic()
            self._auto_usage = False
        if "secondary" in changes:
            self._secondary_auto_started = time.monotonic()
            self._secondary_auto_usage = False
        if "auto_cycle_s" in changes:
            self._auto_started = time.monotonic()
            self._auto_usage = False
            self._secondary_auto_started = time.monotonic()
            self._secondary_auto_usage = False
        self.emit("config-changed")
        if notify_output:
            self._resolve_modes()
            self.send_now()

    def set_accent(self, name: str) -> None:
        self.config.accent = name
        self.config.validate()
        self.config.save()
        self.emit("config-changed")

    def set_animations(self, enabled: bool) -> None:
        self.config.animations = enabled
        self.config.save()
        self.emit("config-changed")

    def set_color_scheme(self, scheme: str) -> None:
        self.config.color_scheme = scheme
        self.config.validate()
        self.config.save()
        self.emit("config-changed")
