"""Headless display daemon used by the systemd user service."""

from __future__ import annotations

import logging
import signal
import threading
import time

from . import lighting, msi_native
from .config import Config, config_path
from .device import (
    DeviceError,
    DeviceSession,
    PermissionDenied,
    find_supported_device,
)
from .protocol import build_status_packet, convert_temperature
from .sensors import SensorReader

LOG = logging.getLogger("deepcool-control")

_stop = False


def _handle_signal(_signum: int, _frame: object) -> None:
    global _stop
    _stop = True


def _values(snapshot, mode: str, fahrenheit: bool) -> tuple[float, float]:
    if mode == "cpu_temp":
        if snapshot.cpu_temperature is None:
            return 0.0, snapshot.cpu_usage
        return convert_temperature(snapshot.cpu_temperature, fahrenheit), snapshot.cpu_usage
    if mode == "cpu_usage":
        return snapshot.cpu_usage, snapshot.cpu_usage
    if mode == "gpu_temp":
        if snapshot.gpu_temperature is None:
            return 0.0, snapshot.gpu_usage or 0.0
        return convert_temperature(snapshot.gpu_temperature, fahrenheit), snapshot.gpu_usage or 0.0
    if mode == "gpu_usage":
        value = snapshot.gpu_usage or 0.0
        return value, value
    return 0.0, 0.0


def _config_mtime() -> int:
    try:
        return config_path().stat().st_mtime_ns
    except OSError:
        return 0


NativeKey = tuple[str, tuple[int, int, int], str, int]


def _native_lighting_key(config: Config) -> NativeKey | None:
    """Return the native MSI lighting state requested by the config."""

    if config.lighting_safe_mode or not config.lighting_device:
        return None
    if "native" not in config.lighting_device.lower():
        return None

    effect = msi_native.effect_for_mode(config.lighting_mode)
    color = config.lighting_color.lstrip("#")
    try:
        rgb = (
            int(color[0:2], 16),
            int(color[2:4], 16),
            int(color[4:6], 16),
        )
    except (TypeError, ValueError):
        return None

    zone = msi_native.resolve_zone(config.lighting_zone) or ""
    brightness = 0 if effect == "off" else max(
        0, min(100, int(config.lighting_brightness))
    )
    return zone, rgb, effect, brightness


def _sync_native_lighting(config: Config, state: dict[str, object]) -> None:
    """Keep the native MSI animation in sync with the saved config."""

    key = _native_lighting_key(config)
    if key is None:
        if state.get("active"):
            msi_native.stop_session()
            state["active"] = False
            state["key"] = None
            LOG.info("Native MSI lighting stopped")
        return

    if key == state.get("key"):
        # Animated sessions can lose their worker if the controller is
        # unplugged.  Restart it once the device comes back.
        if key[2] in msi_native.ANIMATED_EFFECTS and msi_native.session().running:
            return
        if key[2] not in msi_native.ANIMATED_EFFECTS:
            return
        state["key"] = None
        state["active"] = False

    if not msi_native.find_devices():
        if state.get("active"):
            msi_native.stop_session()
            state["active"] = False
            state["key"] = None
            LOG.info("Native MSI controller disconnected; lighting paused")
        return

    zone, rgb, effect, brightness = key
    try:
        msi_native.session().apply(
            zone or None,
            rgb,
            effect,
            brightness=brightness,
        )
    except OSError as exc:
        LOG.warning("Native MSI lighting update failed: %s", exc)
        state["key"] = None
        state["active"] = False
        return

    state["key"] = key
    state["active"] = True
    LOG.info(
        "Native MSI lighting: zone=%s effect=%s color=#%02X%02X%02X brightness=%d%%",
        zone or "all",
        effect,
        rgb[0],
        rgb[1],
        rgb[2],
        brightness,
    )


GpuKey = tuple[str, str, str, int]


def _gpu_lighting_key(config: Config) -> GpuKey | None:
    """Return the saved non-MSI GPU lighting state, if enabled."""

    if not config.gpu_lighting_enabled:
        return None
    device = config.gpu_lighting_device.strip()
    mode = config.gpu_lighting_mode.strip()
    color = config.gpu_lighting_color.strip()
    if not (device and mode and color) or "ZOTAC" not in device.upper():
        return None
    try:
        brightness = max(0, min(100, int(config.gpu_lighting_brightness)))
    except (TypeError, ValueError):
        brightness = 100
    return device, mode, color.upper(), brightness


def _apply_gpu_lighting(key: GpuKey, state: dict[str, object]) -> None:
    """Apply the GPU effect once; never touch the native MSI controller."""

    device, mode, color, brightness = key
    try:
        lighting.apply_gpu_preset(mode, color, brightness=brightness)
    except Exception as exc:  # keep the display loop alive
        state["failed"] = True
        state["next_retry"] = time.monotonic() + 10.0
        LOG.warning("GPU lighting update failed: %s", exc)
    else:
        state["key"] = key
        state["failed"] = False
        LOG.info(
            "GPU lighting: device=%s effect=%s color=%s brightness=%d%%",
            device,
            mode,
            color,
            brightness,
        )
    finally:
        state["applying"] = False


def _sync_gpu_lighting(config: Config, state: dict[str, object]) -> None:
    """Start a one-shot GPU update when the saved effect changes."""

    key = _gpu_lighting_key(config)
    if key is None or key == state.get("key"):
        return
    if state.get("applying"):
        return
    now = time.monotonic()
    if state.get("failed") and now < float(state.get("next_retry", 0.0)):
        return
    state["applying"] = True
    threading.Thread(
        target=_apply_gpu_lighting,
        args=(key, state),
        name="gpu-lighting",
        daemon=True,
    ).start()


def run_daemon(config: Config | None = None) -> int:
    global _stop
    config = (config or Config.load()).validate()
    config_mtime = _config_mtime()
    next_config_check = 0.0
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    reader = SensorReader(config.cpu_sensor, config.gpu_sensor)
    session: DeviceSession | None = None
    auto_started = time.monotonic()
    auto_usage = False
    secondary_auto_started = time.monotonic()
    secondary_auto_usage = False
    next_retry = 0.0
    next_native_check = 0.0
    next_gpu_check = 0.0
    last_error = ""
    native_state: dict[str, object] = {"key": None, "active": False}
    gpu_state: dict[str, object] = {
        "key": None,
        "applying": False,
        "failed": False,
        "next_retry": 0.0,
    }

    LOG.info("DeepCool Control daemon starting")
    _sync_native_lighting(config, native_state)
    _sync_gpu_lighting(config, gpu_state)
    next_native_check = time.monotonic() + 5.0
    next_gpu_check = time.monotonic() + 5.0
    while not _stop:
        now = time.monotonic()

        if now >= next_native_check:
            next_native_check = now + 5.0
            _sync_native_lighting(config, native_state)

        if now >= next_gpu_check:
            next_gpu_check = now + 5.0
            _sync_gpu_lighting(config, gpu_state)

        # Pick up changes made in the GUI while this service owns the display.
        if now >= next_config_check:
            next_config_check = now + 2.0
            mtime = _config_mtime()
            if mtime and mtime != config_mtime:
                config_mtime = mtime
                new_config = Config.load().validate()
                if new_config != config:
                    config = new_config
                    reader.configure(config.cpu_sensor, config.gpu_sensor)
                    auto_started = time.monotonic()
                    secondary_auto_started = time.monotonic()
                    LOG.info("Configuration reloaded")
                    _sync_native_lighting(config, native_state)
                    _sync_gpu_lighting(config, gpu_state)

        if session is None and now >= next_retry:
            info = find_supported_device()
            if info is None:
                if last_error != "no-device":
                    LOG.info("Waiting for a supported DeepCool display")
                    last_error = "no-device"
                next_retry = now + 5.0
            else:
                candidate = DeviceSession(info)
                try:
                    candidate.open()
                except PermissionDenied:
                    if last_error != "permission":
                        LOG.error(
                            "Permission denied for %s. Install the udev rule or run the app's "
                            "'Grant access' action.",
                            info.path,
                        )
                        last_error = "permission"
                    next_retry = now + 15.0
                except BlockingIOError:
                    if last_error != "busy":
                        LOG.info("Another controller owns the display; retrying")
                        last_error = "busy"
                    next_retry = now + 5.0
                except DeviceError as exc:
                    LOG.warning("Could not open display: %s", exc)
                    next_retry = now + 5.0
                else:
                    session = candidate
                    last_error = ""
                    LOG.info("Connected to %s (%s)", info.display_name, info.serial)
                    auto_started = time.monotonic()
                    secondary_auto_started = time.monotonic()

        if session is not None:
            snapshot = reader.read()
            primary = config.primary
            if primary == "auto":
                if time.monotonic() - auto_started >= config.auto_cycle_s:
                    auto_usage = not auto_usage
                    auto_started = time.monotonic()
                primary = "cpu_usage" if auto_usage else "cpu_temp"
            primary_value, primary_percent = _values(snapshot, primary, config.fahrenheit)

            secondary = config.secondary
            if secondary == "auto":
                if time.monotonic() - secondary_auto_started >= config.auto_cycle_s:
                    secondary_auto_usage = not secondary_auto_usage
                    secondary_auto_started = time.monotonic()
                secondary = "gpu_usage" if secondary_auto_usage else "gpu_temp"
            if secondary == "off":
                secondary_value = secondary_percent = 0.0
            else:
                secondary_value, secondary_percent = _values(
                    snapshot, secondary, config.fahrenheit
                )
            packet = build_status_packet(
                primary_mode=primary,
                primary_value=primary_value,
                primary_percent=primary_percent,
                secondary_mode=secondary,
                secondary_value=secondary_value,
                secondary_percent=secondary_percent,
                fahrenheit=config.fahrenheit,
            )
            try:
                session.write(packet)
            except DeviceError as exc:
                LOG.warning("Display write failed: %s", exc)
                session.close()
                session = None
                next_retry = time.monotonic() + 3.0

        remaining = config.interval_ms / 1000.0
        deadline = time.monotonic() + remaining
        while not _stop and time.monotonic() < deadline:
            time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))

    msi_native.stop_session()
    if session is not None:
        session.close()
    LOG.info("DeepCool Control daemon stopped")
    return 0
