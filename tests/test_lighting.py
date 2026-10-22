"""OpenRGB output parsing and command tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deepcool_control.lighting import (  # noqa: E402
    LightingDevice,
    LightingError,
    ZOTAC_DETECTOR_NAMES,
    apply_color,
    apply_gpu_preset,
    build_apply_command,
    ensure_gpu_only_config,
    is_mystic_light,
    list_devices,
    normalize_color,
    parse_devices,
    record_apply,
    risk_reasons,
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
        with mock.patch(
            "deepcool_control.lighting._native_devices", return_value=[]
        ):
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
                "--noautoconnect",
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
            ["openrgb", "--noautoconnect", "--device", "0", "--color", "000000"],
        )

    def test_clamps_brightness(self) -> None:
        command = build_apply_command(
            self.device,
            "#FFFFFF",
            brightness=999,
            binary="openrgb",
        )
        self.assertEqual(command[-1], "100")


class GpuConfigTests(unittest.TestCase):
    def _source_config(self, count: int) -> dict:
        return {
            "Detectors": {
                "detectors": {
                    **{f"Detector {index}": True for index in range(count)},
                    "MSI Mystic Light MS_7D77": True,
                    "ZOTAC GAMING GeForce RTX 4060 Ti 8GB Twin Edge (19DA:1747)": True,
                }
            },
            "Other": {"preserved": True},
        }

    def test_gpu_only_config_disables_every_other_detector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_home = Path(directory) / "config"
            cache_home = Path(directory) / "cache"
            source = config_home / "OpenRGB"
            source.mkdir(parents=True)
            (source / "OpenRGB.json").write_text(
                json.dumps(self._source_config(120)), encoding="utf-8"
            )
            with mock.patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": str(config_home),
                    "XDG_CACHE_HOME": str(cache_home),
                },
            ):
                target = ensure_gpu_only_config(binary=None)
                raw = json.loads((target / "OpenRGB.json").read_text())

        detectors = raw["Detectors"]["detectors"]
        self.assertFalse(detectors["MSI Mystic Light MS_7D77"])
        self.assertFalse(detectors["Detector 0"])
        for name in ZOTAC_DETECTOR_NAMES:
            self.assertTrue(detectors[name])
        self.assertEqual(raw["Other"], {"preserved": True})

    def test_gpu_only_config_generates_a_complete_source(self) -> None:
        generated = {
            "Detectors": {
                "detectors": {
                    "MSI Mystic Light MS_7D77": True,
                    "Some Other Device": True,
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            config_home = Path(directory) / "config"
            cache_home = Path(directory) / "cache"
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "XDG_CONFIG_HOME": str(config_home),
                        "XDG_CACHE_HOME": str(cache_home),
                    },
                ),
                mock.patch(
                    "deepcool_control.lighting._generate_openrgb_config",
                    return_value=generated,
                ) as generate,
            ):
                target = ensure_gpu_only_config(binary="openrgb")
                raw = json.loads((target / "OpenRGB.json").read_text())

        generate.assert_called_once()
        detectors = raw["Detectors"]["detectors"]
        self.assertFalse(detectors["MSI Mystic Light MS_7D77"])
        self.assertTrue(
            detectors["ZOTAC GAMING GeForce RTX 4060 Ti 8GB Twin Edge (19DA:1747)"]
        )

    def test_apply_gpu_preset_uses_gpu_only_config(self) -> None:
        completed = mock.Mock(returncode=0, stdout="", stderr="")
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch(
                "deepcool_control.lighting.ensure_gpu_only_config",
                return_value=Path(directory),
            ),
            mock.patch(
                "deepcool_control.lighting.subprocess.run",
                return_value=completed,
            ) as run,
        ):
            apply_gpu_preset(
                "Breathing",
                "#613583",
                brightness=80,
                binary="openrgb",
                write_log=False,
            )

        command = run.call_args.args[0]
        self.assertIn("--config", command)
        self.assertIn("ZOTAC GPU", command)
        self.assertIn("--mode", command)
        self.assertIn("Breathing", command)
        self.assertIn("--color", command)
        self.assertIn("613583", command)
        self.assertIn("--brightness", command)
        self.assertIn("80", command)


class SafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.device = LightingDevice(
            index=0,
            name="MSI PRO B650M-A WIFI (MS-7D77)",
            type="Motherboard",
            description="MSI Mystic Light Device (185-byte)",
            modes=("Direct", "Meteor"),
            zones=("JRGB1", "JRAINBOW1"),
        )

    def test_detects_mystic_light(self) -> None:
        self.assertTrue(is_mystic_light(self.device))
        self.assertFalse(
            is_mystic_light(
                LightingDevice(index=1, name="Test Controller", type="LED Strip")
            )
        )

    def test_safe_settings_have_no_reasons(self) -> None:
        self.assertEqual(
            risk_reasons(
                self.device,
                mode="Direct",
                brightness=35,
                zone_index=1,
            ),
            (),
        )

    def test_risky_settings_are_reported(self) -> None:
        reasons = risk_reasons(
            self.device,
            mode="Meteor",
            brightness=100,
            zone_index=None,
        )
        self.assertEqual(len(reasons), 3)
        self.assertTrue(any("Meteor" in reason for reason in reasons))
        self.assertTrue(any("all zones" in reason for reason in reasons))
        self.assertTrue(any("100%" in reason for reason in reasons))

    def test_record_apply_writes_exact_command(self) -> None:
        command = build_apply_command(
            self.device,
            "#22D3EE",
            mode="Meteor",
            brightness=100,
            zone_index=1,
            binary="openrgb",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lighting.log"
            record_apply(
                command,
                device=self.device,
                color="#22D3EE",
                mode="Meteor",
                brightness=100,
                zone_index=1,
                path=path,
            )
            text = path.read_text(encoding="utf-8")
        self.assertIn("device='MSI PRO B650M-A WIFI (MS-7D77)'", text)
        self.assertIn("zone=zone 1", text)
        self.assertIn("mode='Meteor'", text)
        self.assertIn("brightness=100%", text)
        self.assertIn(
            "command=openrgb --noautoconnect --device 0 --zone 1 "
            "--mode Meteor --color 22D3EE --brightness 100",
            text,
        )

    def test_apply_color_logs_before_running(self) -> None:
        completed = mock.Mock(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lighting.log"
            with mock.patch(
                "deepcool_control.lighting.subprocess.run",
                return_value=completed,
            ) as run:
                apply_color(
                    self.device,
                    "#22D3EE",
                    mode="Direct",
                    brightness=35,
                    zone_index=1,
                    binary="openrgb",
                    log_file=path,
                )
            self.assertTrue(path.exists())
            self.assertIn("--mode Direct", path.read_text(encoding="utf-8"))
            self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
