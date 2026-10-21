"""Headless display daemon used by the systemd user service."""

from __future__ import annotations

import logging
import signal
import time

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
    last_error = ""

    LOG.info("DeepCool Control daemon starting")
    while not _stop:
        now = time.monotonic()

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

    if session is not None:
        session.close()
    LOG.info("DeepCool Control daemon stopped")
    return 0
