"""OpenRGB output parsing and command tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deepcool_control.lighting import (  # noqa: E402
    LightingDevice,
    LightingError,
    build_apply_command,
    list_devices,
    normalize_color,
    parse_devices,
)

SAMPLE = """Connection attempt failed
[i2c_smbus_linux] Failed to read i2c device PCI device ID
0: MSI PRO B650M-A WIFI (MS-7D77)
  Type:           Motherboard
  Description:    MSI Mystic Light Device (185-byte)
  Version:        HID: /dev/hidraw3
  Location:       HID: /dev/hidraw3
  Serial:         7D7723122707
  Modes: Direct Static Breathing 'Double flashing' ['Rainbow wave']
  Zones: JRGB1 JRGB2 JRAINBOW1 JRAINBOW2
  LEDs: JRGB1 JRGB2

1: Test Controller
  Type: LED Strip
  Modes: Direct
  Zones: 'Front RGB' Rear
"""


class ParseTests(unittest.TestCase):
    def test_parses_devices_and_active_mode(self) -> None:
        devices = parse_devices(SAMPLE)
        self.assertEqual(len(devices), 2)
        first = devices[0]
        self.assertEqual(first.index, 0)
        self.assertEqual(first.name, "MSI PRO B650M-A WIFI (MS-7D77)")
        self.assertEqual(first.type, "Motherboard")
        self.assertEqual(first.location, "HID: /dev/hidraw3")
        self.assertEqual(first.serial, "7D7723122707")
        self.assertEqual(first.active_mode, "Rainbow wave")
        self.assertIn("Double flashing", first.modes)
        self.assertIn("Rainbow wave", first.modes)
        self.assertEqual(
            first.zones, ("JRGB1", "JRGB2", "JRAINBOW1", "JRAINBOW2")
        )
        self.assertEqual(first.leds, ("JRGB1", "JRGB2"))

    def test_quoted_zone_names(self) -> None:
        zones = parse_devices(SAMPLE)[1].zones
        self.assertEqual(zones, ("Front RGB", "Rear"))

    def test_ignores_log_noise_and_empty_output(self) -> None:
        self.assertEqual(parse_devices(""), [])
        self.assertEqual(parse_devices("Connection attempt failed\n"), [])

    def test_missing_openrgb_binary_raises(self) -> None:
        with self.assertRaises(LightingError):
            list_devices("/nonexistent/openrgb")


class ColorTests(unittest.TestCase):
    def test_normalizes_colors(self) -> None:
        self.assertEqual(normalize_color("22d3ee"), "#22D3EE")
        self.assertEqual(normalize_color("#ff8800"), "#FF8800")

    def test_rejects_invalid_colors(self) -> None:
        for value in ("red", "#FFF", "#GG0000", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_color(value)


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.device = LightingDevice(
            index=0,
            name="MSI",
            modes=("Direct", "Static"),
            zones=("JRGB1", "JRAINBOW1"),
        )

    def test_builds_zone_command(self) -> None:
        command = build_apply_command(
            self.device,
            "#22d3ee",
            mode="Static",
            brightness=40,
            zone_index=1,
            binary="/usr/bin/openrgb",
        )
        self.assertEqual(
            command,
            [
                "/usr/bin/openrgb",
                "--device",
                "0",
                "--zone",
                "1",
                "--mode",
                "Static",
                "--color",
                "22D3EE",
                "--brightness",
                "40",
            ],
        )

    def test_omits_optional_arguments(self) -> None:
        command = build_apply_command(
            self.device,
            "#000000",
            mode=None,
            binary="openrgb",
        )
        self.assertEqual(
            command,
            ["openrgb", "--device", "0", "--color", "000000"],
        )

    def test_clamps_brightness(self) -> None:
        command = build_apply_command(
            self.device,
            "#FFFFFF",
            brightness=999,
            binary="openrgb",
        )
        self.assertEqual(command[-1], "100")


if __name__ == "__main__":
    unittest.main()
