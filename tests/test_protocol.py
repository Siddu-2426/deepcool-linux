"""Protocol encoding tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deepcool_control.protocol import (  # noqa: E402
    MODE_ANIMATION,
    MODE_TEMP_C,
    MODE_TEMP_F,
    MODE_USAGE,
    PACKET_SIZE,
    REPORT_ID,
    bar_cells,
    build_animation_packet,
    build_status_packet,
    convert_temperature,
    encode_digits,
)


class DigitTests(unittest.TestCase):
    def test_splits_three_digits(self) -> None:
        self.assertEqual(encode_digits(0), (0, 0, 0))
        self.assertEqual(encode_digits(7), (0, 0, 7))
        self.assertEqual(encode_digits(65), (0, 6, 5))
        self.assertEqual(encode_digits(123), (1, 2, 3))

    def test_rounds_like_firmware(self) -> None:
        self.assertEqual(encode_digits(65.4), (0, 6, 5))
        self.assertEqual(encode_digits(65.5), (0, 6, 6))
        self.assertEqual(encode_digits(99.5), (1, 0, 0))

    def test_clamps_and_handles_bad_values(self) -> None:
        self.assertEqual(encode_digits(999.9), (9, 9, 9))
        self.assertEqual(encode_digits(-5), (0, 0, 0))
        self.assertEqual(encode_digits(None), (0, 0, 0))  # type: ignore[arg-type]


class BarTests(unittest.TestCase):
    def test_idle_bar_has_one_cell(self) -> None:
        self.assertEqual(bar_cells(0), 1)
        self.assertEqual(bar_cells(14.9), 1)

    def test_bar_follows_utilization(self) -> None:
        self.assertEqual(bar_cells(15), 2)
        self.assertEqual(bar_cells(25), 3)
        self.assertEqual(bar_cells(42), 4)
        self.assertEqual(bar_cells(95), 10)
        self.assertEqual(bar_cells(100), 10)

    def test_bar_clamps_and_handles_missing(self) -> None:
        self.assertEqual(bar_cells(None), 0)
        self.assertEqual(bar_cells(-10), 1)
        self.assertEqual(bar_cells(999), 10)
        self.assertEqual(bar_cells("nonsense"), 0)


class TemperatureTests(unittest.TestCase):
    def test_celsius_is_unchanged(self) -> None:
        self.assertEqual(convert_temperature(51.7, False), 51.7)

    def test_fahrenheit_matches_vendor_truncation(self) -> None:
        self.assertEqual(convert_temperature(50, True), 122.0)
        self.assertEqual(convert_temperature(36.7, True), 98.0)


class PacketTests(unittest.TestCase):
    def test_temperature_packet_layout(self) -> None:
        packet = build_status_packet(
            primary_mode="cpu_temp",
            primary_value=65.6,
            primary_percent=42,
            secondary_mode="gpu_temp",
            secondary_value=51.2,
            secondary_percent=18,
        )
        self.assertEqual(len(packet), PACKET_SIZE)
        self.assertEqual(packet[0], REPORT_ID)
        self.assertEqual(packet[1], MODE_TEMP_C)
        self.assertEqual(packet[2], 4)
        self.assertEqual(tuple(packet[3:6]), (0, 6, 6))
        self.assertEqual(packet[6], MODE_TEMP_C)
        self.assertEqual(packet[7], 2)
        self.assertEqual(tuple(packet[8:11]), (0, 5, 1))
        self.assertEqual(packet[11:], bytes(PACKET_SIZE - 11))

    def test_usage_packet_uses_percent_mode(self) -> None:
        packet = build_status_packet(
            primary_mode="cpu_usage",
            primary_value=25.5,
            primary_percent=25,
            secondary_mode="gpu_usage",
            secondary_value=8,
            secondary_percent=8,
        )
        self.assertEqual(packet[1], MODE_USAGE)
        self.assertEqual(packet[2], 3)
        self.assertEqual(tuple(packet[3:6]), (0, 2, 6))
        self.assertEqual(packet[6], MODE_USAGE)
        self.assertEqual(packet[7], 1)

    def test_fahrenheit_sets_both_modes(self) -> None:
        packet = build_status_packet(
            primary_mode="cpu_temp",
            primary_value=122,
            primary_percent=10,
            secondary_mode="gpu_temp",
            secondary_value=98,
            secondary_percent=12,
            fahrenheit=True,
        )
        self.assertEqual(packet[1], MODE_TEMP_F)
        self.assertEqual(packet[6], MODE_TEMP_F)

    def test_secondary_off_clears_bytes(self) -> None:
        packet = build_status_packet(
            primary_mode="cpu_temp",
            primary_value=50,
            primary_percent=20,
            secondary_mode="off",
            secondary_value=99,
            secondary_percent=99,
        )
        self.assertEqual(tuple(packet[6:11]), (0, 0, 0, 0, 0))

    def test_unknown_primary_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_status_packet("auto", 50, 20, "gpu_temp", 45, 10)

    def test_animation_packet(self) -> None:
        packet = build_animation_packet()
        self.assertEqual(len(packet), PACKET_SIZE)
        self.assertEqual(packet[0], REPORT_ID)
        self.assertEqual(packet[1], MODE_ANIMATION)
        self.assertEqual(packet[2:], bytes(PACKET_SIZE - 2))


if __name__ == "__main__":
    unittest.main()
