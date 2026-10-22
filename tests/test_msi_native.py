"""Native MSI Mystic Light effect and apply tests (no hardware needed)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deepcool_control import daemon, msi_native  # noqa: E402
from deepcool_control.config import Config  # noqa: E402
from deepcool_control.lighting import (  # noqa: E402
    LightingDevice,
    apply_native,
    risk_reasons,
)


class EffectTests(unittest.TestCase):
    def test_every_mode_maps_to_a_valid_effect(self) -> None:
        for mode in msi_native.MODES:
            effect = msi_native.effect_for_mode(mode)
            pixels = msi_native.render_effect(effect, (200, 100, 50), 12, t=1.23)
            self.assertEqual(len(pixels), 12, mode)
            for pixel in pixels:
                for channel in pixel:
                    self.assertGreaterEqual(channel, 0, mode)
                    self.assertLessEqual(channel, 255, mode)

    def test_requested_modes_are_distinct(self) -> None:
        expected = {
            "Static": "static",
            "Breathing": "breathing",
            "Flashing": "flashing",
            "Double flashing": "double_flashing",
            "Meteor": "meteor",
            "Blink": "blink",
            "Color pulse": "color_pulse",
            "Color wave": "wave",
            "Marquee": "marquee",
            "Visor": "visor",
            "Rainbow flashing": "rainbow_flashing",
            "Stack": "stack",
            "Fire": "fire",
        }
        for mode, effect in expected.items():
            self.assertEqual(msi_native.effect_for_mode(mode), effect)

    def test_static_is_exact(self) -> None:
        self.assertEqual(
            msi_native.render_effect("static", (1, 2, 3), 4), [(1, 2, 3)] * 4
        )


class ZoneTests(unittest.TestCase):
    def test_zone_aliases(self) -> None:
        self.assertEqual(msi_native.resolve_zone("JRAINBOW2"), "JRAINBOW2")
        self.assertEqual(msi_native.resolve_zone("jargb2"), "JRAINBOW2")
        self.assertEqual(msi_native.resolve_zone("JRGB1"), "JRGB1")
        self.assertIsNone(msi_native.resolve_zone("all"))

    def test_render_uses_second_argb_slots(self) -> None:
        session = msi_native.NativeSession()
        session.zones["JRAINBOW2"].update(
            enabled=True, color=(255, 0, 0), effect="static", brightness=100
        )
        pixels = session.render(t=0)
        self.assertEqual(len(pixels), msi_native.LEDS_TOTAL)
        self.assertTrue(all(p == (255, 0, 0) for p in pixels[42:82]))
        self.assertTrue(all(p == (0, 0, 0) for p in pixels[:42]))
        self.assertTrue(all(p == (0, 0, 0) for p in pixels[82:]))


class ApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.device = LightingDevice(
            index=-1,
            name="MSI MYSTIC LIGHT (native)",
            modes=msi_native.MODES,
            zones=tuple(zone.key for zone in msi_native.ZONES),
            native=True,
        )

    def test_native_apply_forwards_zone_and_effect(self) -> None:
        with mock.patch.object(msi_native, "session") as session:
            apply_native(
                self.device,
                "#FF8000",
                mode="Double flashing",
                brightness=40,
                zone_index=3,
                write_log=False,
            )
        session.return_value.apply.assert_called_once_with(
            "JRAINBOW2",
            (255, 128, 0),
            "double_flashing",
            brightness=40,
        )

    def test_native_is_not_risky(self) -> None:
        self.assertEqual(
            risk_reasons(
                self.device,
                mode="Meteor",
                brightness=100,
                zone_index=None,
            ),
            (),
        )


class BackgroundLightingTests(unittest.TestCase):
    def _config(self, **changes: object) -> Config:
        config = Config(
            lighting_device="MSI MYSTIC LIGHT (native)",
            lighting_zone="JRAINBOW2",
            lighting_color="#FF8000",
            lighting_mode="Meteor",
            lighting_brightness=40,
            lighting_safe_mode=False,
            service=True,
        ).validate()
        for key, value in changes.items():
            setattr(config, key, value)
        return config.validate()

    def test_native_key_for_background_service(self) -> None:
        key = daemon._native_lighting_key(self._config())
        self.assertEqual(key, ("JRAINBOW2", (255, 128, 0), "meteor", 40))

    def test_native_key_skips_safe_or_non_native_devices(self) -> None:
        self.assertIsNone(
            daemon._native_lighting_key(self._config(lighting_safe_mode=True))
        )
        self.assertIsNone(
            daemon._native_lighting_key(
                self._config(lighting_device="MSI PRO B650M-A WIFI (MS-7D77)")
            )
        )
        self.assertIsNone(
            daemon._native_lighting_key(self._config(lighting_device=""))
        )

    def test_background_service_applies_native_state(self) -> None:
        state: dict[str, object] = {"key": None, "active": False}
        config = self._config()
        with (
            mock.patch.object(msi_native, "find_devices", return_value=[object()]),
            mock.patch.object(msi_native, "session") as session,
        ):
            daemon._sync_native_lighting(config, state)

        session.return_value.apply.assert_called_once_with(
            "JRAINBOW2",
            (255, 128, 0),
            "meteor",
            brightness=40,
        )
        self.assertTrue(state["active"])
        self.assertEqual(state["key"], daemon._native_lighting_key(config))

    def test_background_service_off_writes_black(self) -> None:
        state: dict[str, object] = {"key": None, "active": False}
        config = self._config(
            lighting_mode="Off",
            lighting_color="#000000",
            lighting_brightness=0,
        )
        with (
            mock.patch.object(msi_native, "find_devices", return_value=[object()]),
            mock.patch.object(msi_native, "session") as session,
        ):
            daemon._sync_native_lighting(config, state)

        session.return_value.apply.assert_called_once_with(
            "JRAINBOW2",
            (0, 0, 0),
            "off",
            brightness=0,
        )


if __name__ == "__main__":
    unittest.main()
