"""Configuration tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deepcool_control.config import ACCENTS, Config  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_defaults_are_valid(self) -> None:
        config = Config().validate()
        self.assertEqual(config.primary, "cpu_temp")
        self.assertEqual(config.secondary, "gpu_temp")
        self.assertFalse(config.fahrenheit)
        self.assertEqual(config.interval_ms, 1000)
        self.assertEqual(config.accent, "cyan")
        self.assertEqual(config.lighting_device, "")
        self.assertEqual(config.lighting_color, "#22D3EE")
        self.assertEqual(config.lighting_mode, "Direct")
        self.assertEqual(config.lighting_brightness, 100)

    def test_invalid_values_are_repaired(self) -> None:
        config = Config(
            primary="bogus",
            secondary="bogus",
            interval_ms=1,
            auto_cycle_s=9999,
            accent="chartreuse",
            color_scheme="sepia",
            lighting_color="not-a-color",
            lighting_mode="",
            lighting_brightness=999,
        ).validate()
        self.assertEqual(config.primary, "cpu_temp")
        self.assertEqual(config.secondary, "gpu_temp")
        self.assertEqual(config.interval_ms, 250)
        self.assertEqual(config.auto_cycle_s, 120)
        self.assertEqual(config.accent, "cyan")
        self.assertEqual(config.color_scheme, "system")
        self.assertEqual(config.lighting_color, "#22D3EE")
        self.assertEqual(config.lighting_mode, "Direct")
        self.assertEqual(config.lighting_brightness, 100)

    def test_clamps_high_values(self) -> None:
        config = Config(interval_ms=99999, auto_cycle_s=1).validate()
        self.assertEqual(config.interval_ms, 5000)
        self.assertEqual(config.auto_cycle_s, 3)

    def test_secondary_auto_cycle_is_valid(self) -> None:
        config = Config(secondary="auto").validate()
        self.assertEqual(config.secondary, "auto")

    def test_unknown_keys_are_ignored(self) -> None:
        config = Config.from_dict(
            {"primary": "cpu_usage", "accent": "violet", "future_option": True}
        )
        self.assertEqual(config.primary, "cpu_usage")
        self.assertEqual(config.accent, "violet")
        self.assertFalse(hasattr(config, "future_option"))

    def test_save_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = Config(
                primary="auto",
                secondary="gpu_usage",
                fahrenheit=True,
                interval_ms=750,
                accent="emerald",
                lighting_device="MSI Mystic Light",
                lighting_zone="JRAINBOW1",
                lighting_color="#FF8800",
                lighting_mode="Static",
                lighting_brightness=42,
            )
            config.save(path)
            self.assertTrue(path.exists())
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["accent"], "emerald")
            self.assertEqual(raw["lighting_color"], "#FF8800")
            loaded = Config.load(path)
            self.assertEqual(loaded.primary, "auto")
            self.assertEqual(loaded.secondary, "gpu_usage")
            self.assertTrue(loaded.fahrenheit)
            self.assertEqual(loaded.interval_ms, 750)
            self.assertEqual(loaded.accent, "emerald")
            self.assertEqual(loaded.lighting_device, "MSI Mystic Light")
            self.assertEqual(loaded.lighting_zone, "JRAINBOW1")
            self.assertEqual(loaded.lighting_color, "#FF8800")
            self.assertEqual(loaded.lighting_mode, "Static")
            self.assertEqual(loaded.lighting_brightness, 42)

    def test_broken_file_falls_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("{not valid json", encoding="utf-8")
            config = Config.load(path)
            self.assertEqual(config.primary, "cpu_temp")

    def test_accents_are_complete(self) -> None:
        for name, (color, soft) in ACCENTS.items():
            self.assertTrue(color.startswith("#"), name)
            self.assertTrue(soft.startswith("rgba("), name)


if __name__ == "__main__":
    unittest.main()
