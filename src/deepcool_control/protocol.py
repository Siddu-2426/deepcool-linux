"""HID protocol for DeepCool CH-series digital displays.

The CH360 DIGITAL (USB ``3633:0015``) exposes a single 64-byte HID output
report.  The report mirrors the two three-digit readouts and two ten-cell
usage bars that are physically printed on the case:

``D0`` report id (16), ``D1`` primary mode, ``D2`` primary bar (1-10),
``D3..D5`` primary digits, ``D6`` secondary mode, ``D7`` secondary bar,
``D8..D10`` secondary digits.  The remaining bytes are unused.

Mode bytes: 19 = temperature in °C, 35 = temperature in °F, 76 = usage in %.
Sending mode 170 once performs the status-bar start-up animation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

REPORT_ID = 0x10
PACKET_SIZE = 64

MODE_TEMP_C = 19
MODE_TEMP_F = 35
MODE_USAGE = 76
MODE_ANIMATION = 170

PRIMARY_MODES = ("cpu_temp", "cpu_usage", "auto")
SECONDARY_MODES = ("gpu_temp", "gpu_usage", "auto", "off")

MODE_LABELS = {
    "cpu_temp": "CPU temperature",
    "cpu_usage": "CPU usage",
    "gpu_temp": "GPU temperature",
    "gpu_usage": "GPU usage",
    "auto": "Auto cycle",
    "off": "Off",
}


def _round_half_up(value: float) -> int:
    """Match the firmware's round-half-away-from-zero behaviour."""

    if value >= 0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))


def encode_digits(value: float | int) -> tuple[int, int, int]:
    """Split a value into three display digits, clamped to what the panel has."""

    try:
        number = _round_half_up(float(value))
    except (TypeError, ValueError):
        number = 0
    number = max(0, min(999, number))
    return (number // 100, (number // 10) % 10, number % 10)


def bar_cells(percent: float | int | None) -> int:
    """Convert a usage percentage to one of the ten cells on the status bar."""

    if percent is None:
        return 0
    try:
        value = float(percent)
    except (TypeError, ValueError):
        return 0
    value = max(0.0, min(100.0, value))
    # The panel shows a single lit cell at idle instead of an empty bar.
    if value < 15:
        return 1
    return max(1, min(10, _round_half_up(value / 10.0)))


def convert_temperature(celsius: float, fahrenheit: bool) -> float:
    if fahrenheit:
        # Match the vendor software, which truncates rather than rounds.
        return float(int(32 + 1.8 * celsius))
    return float(celsius)


@dataclass(frozen=True)
class StatusPacket:
    primary_mode: str
    primary_value: float
    primary_percent: float
    secondary_mode: str
    secondary_value: float
    secondary_percent: float
    fahrenheit: bool = False

    def to_bytes(self) -> bytes:
        if self.primary_mode not in ("cpu_temp", "cpu_usage"):
            raise ValueError(f"primary mode must be resolved, got {self.primary_mode!r}")
        if self.secondary_mode not in ("gpu_temp", "gpu_usage", "off"):
            raise ValueError(f"invalid secondary mode {self.secondary_mode!r}")

        data = bytearray(PACKET_SIZE)
        data[0] = REPORT_ID

        if self.primary_mode == "cpu_usage":
            data[1] = MODE_USAGE
        else:
            data[1] = MODE_TEMP_F if self.fahrenheit else MODE_TEMP_C
        data[2] = bar_cells(self.primary_percent)
        data[3], data[4], data[5] = encode_digits(self.primary_value)

        if self.secondary_mode == "off":
            data[6] = 0
            data[7] = 0
            data[8] = data[9] = data[10] = 0
        else:
            if self.secondary_mode == "gpu_usage":
                data[6] = MODE_USAGE
            else:
                data[6] = MODE_TEMP_F if self.fahrenheit else MODE_TEMP_C
            data[7] = bar_cells(self.secondary_percent)
            data[8], data[9], data[10] = encode_digits(self.secondary_value)

        return bytes(data)


def build_status_packet(
    primary_mode: str,
    primary_value: float,
    primary_percent: float,
    secondary_mode: str,
    secondary_value: float,
    secondary_percent: float,
    fahrenheit: bool = False,
) -> bytes:
    return StatusPacket(
        primary_mode=primary_mode,
        primary_value=primary_value,
        primary_percent=primary_percent,
        secondary_mode=secondary_mode,
        secondary_value=secondary_value,
        secondary_percent=secondary_percent,
        fahrenheit=fahrenheit,
    ).to_bytes()


def build_animation_packet() -> bytes:
    data = bytearray(PACKET_SIZE)
    data[0] = REPORT_ID
    data[1] = MODE_ANIMATION
    return bytes(data)
