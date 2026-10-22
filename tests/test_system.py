"""Desktop integration tests that do not touch the live systemd instance."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deepcool_control import system  # noqa: E402


class UdevRuleTests(unittest.TestCase):
    def test_rules_keep_uaccess_and_add_persistent_group_access(self) -> None:
        for rule in (system.UDEV_RULE, system.MSI_UDEV_RULE):
            with self.subTest(rule=rule):
                self.assertIn('TAG+="uaccess"', rule)
                self.assertIn('GROUP="wheel"', rule)
                self.assertIn('MODE="0660"', rule)


class ServiceUnitTests(unittest.TestCase):
    def test_service_starts_without_graphical_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deepcool-control.service"
            with (
                mock.patch.object(system, "service_path", return_value=path),
                mock.patch.object(
                    system, "launch_command", return_value="/usr/bin/deepcool-control"
                ),
            ):
                written = system._write_service()
                content = written.read_text(encoding="utf-8")

        self.assertEqual(written, path)
        self.assertNotIn("After=graphical-session.target", content)
        self.assertIn("WantedBy=default.target", content)
        self.assertIn("Environment=PATH=%h/.local/bin", content)
        self.assertIn("ExecStart=/usr/bin/deepcool-control --daemon", content)


if __name__ == "__main__":
    unittest.main()
