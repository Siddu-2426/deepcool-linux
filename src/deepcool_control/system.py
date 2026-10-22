"""Desktop integration: autostart, systemd user service and udev permissions."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

RULE_NAME = "99-deepcool-digital.rules"
RULE_PATH = Path("/etc/udev/rules.d") / RULE_NAME
PACKAGE_RULE_PATH = Path("/usr/lib/udev/rules.d") / RULE_NAME
MSI_RULE_NAME = "99-deepcool-msi-mystic-light.rules"
MSI_RULE_PATH = Path("/etc/udev/rules.d") / MSI_RULE_NAME
MSI_PACKAGE_RULE_PATH = Path("/usr/lib/udev/rules.d") / MSI_RULE_NAME
SERVICE_NAME = "deepcool-control.service"
AUTOSTART_NAME = "deepcool-control.desktop"

UDEV_RULE = """# DeepCool CH-series digital displays (CH360/CH560/MORPHEUS)
# GROUP="wheel" is a persistent fallback for the lingering user service that
# starts before login.  TAG+="uaccess" still grants the active desktop user
# access on systems where that user is not in wheel.
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="3633", TAG+="uaccess", GROUP="wheel", MODE="0660"
"""

MSI_UDEV_RULE = """# MSI Mystic Light motherboards (1462:7d77 on MS-7D77).
# Persistent group access lets the lingering user service drive the native
# per-LED backend before a graphical login session exists.
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1462", ATTRS{idProduct}=="7d77", TAG+="uaccess", GROUP="wheel", MODE="0660"
"""


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"))


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"))


def autostart_path() -> Path:
    return _config_home() / "autostart" / AUTOSTART_NAME


def service_path() -> Path:
    return _config_home() / "systemd" / "user" / SERVICE_NAME


def launch_command() -> str:
    installed = shutil.which("deepcool-control")
    if installed:
        return installed
    # Running straight from a source checkout: create a stable command line.
    package_root = Path(__file__).resolve().parents[2]
    launcher = package_root / "deepcool-control"
    if launcher.exists():
        return str(launcher)
    return f"{shlex.quote(os.sys.executable)} -m deepcool_control"


def set_autostart(enabled: bool) -> tuple[bool, str]:
    path = autostart_path()
    if not enabled:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            return False, f"Could not remove autostart entry: {exc}"
        return True, "Autostart disabled"

    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""[Desktop Entry]
Type=Application
Name=DeepCool Control
Comment=Control the CH-series digital display
Exec={launch_command()}
Icon=io.github.deepcool.Control
Terminal=false
X-GNOME-Autostart-enabled=true
Categories=Utility;System;
"""
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return False, f"Could not write autostart entry: {exc}"
    return True, "DeepCool Control will start with your desktop"


def _write_service() -> Path:
    path = service_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""[Unit]
Description=DeepCool Control display daemon
# Do not wait for graphical-session.target.  With lingering enabled the user
# manager starts at boot, so the display and cabinet lighting are active
# before the login prompt.  The MSI panel is host-streamed and cannot be
# driven earlier than the operating system and this service.
# Keep retrying forever if the panel is busy or temporarily unavailable.
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart={launch_command()} --daemon
Restart=always
RestartSec=3
# Give the daemon a moment to release the hidraw lock on logout.
TimeoutStopSec=5
Environment=PYTHONUNBUFFERED=1
# The patched ZOTAC OpenRGB build lives in ~/.local/bin and must be preferred
# over the distribution package.  systemd user services do not inherit the
# desktop shell's PATH.
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
"""
    path.write_text(content, encoding="utf-8")
    return path


def _systemctl(*args: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def set_service(enabled: bool) -> tuple[bool, str]:
    path = service_path()
    if not enabled:
        _systemctl("disable", "--now", SERVICE_NAME)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            return False, f"Could not remove service: {exc}"
        _systemctl("daemon-reload")
        return True, "Background service stopped and disabled"

    try:
        _write_service()
    except OSError as exc:
        return False, f"Could not write service: {exc}"
    reload_result = _systemctl("daemon-reload")
    if reload_result.returncode != 0:
        return False, reload_result.stderr.strip() or "systemctl daemon-reload failed"
    result = _systemctl("enable", "--now", SERVICE_NAME)
    if result.returncode != 0:
        return False, result.stderr.strip() or "Could not start the background service"
    return True, "Background service is running"


def stop_service() -> tuple[bool, str]:
    result = _systemctl("stop", SERVICE_NAME)
    if result.returncode != 0:
        return False, result.stderr.strip() or "Could not stop the service"
    return True, "Background service stopped"


def service_active() -> bool:
    try:
        result = _systemctl("is-active", SERVICE_NAME, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "active"


def service_enabled() -> bool:
    try:
        result = _systemctl("is-enabled", SERVICE_NAME, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() in ("enabled", "enabled-runtime")


def udev_rule_installed() -> bool:
    return RULE_PATH.exists() or PACKAGE_RULE_PATH.exists()


def msi_udev_rule_installed() -> bool:
    return MSI_RULE_PATH.exists() or MSI_PACKAGE_RULE_PATH.exists()


def install_udev_rule(force: bool = False) -> tuple[bool, str]:
    """Install persistent udev permissions for the display and MSI RGB.

    ``TAG+="uaccess"`` alone only grants access after a desktop login.  The
    background service starts from the lingering user manager during boot, so
    both rules also assign the devices to the ``wheel`` group.  That makes the
    very first daemon start at boot able to drive the panel and cabinet ARGB.
    """

    rules = ((RULE_PATH, UDEV_RULE), (MSI_RULE_PATH, MSI_UDEV_RULE))
    existing = [path for path, _content in rules if path.exists()]
    missing = [
        (path, content)
        for path, content in rules
        if force or not path.exists()
    ]
    if not missing:
        return True, "Permission rules are already installed"

    pkexec = shutil.which("pkexec")
    if not pkexec:
        if existing:
            return (
                False,
                "The rules are installed but not active. Run: sudo udevadm control --reload-rules "
                "&& sudo udevadm trigger --action=add --subsystem-match=hidraw",
            )
        return (
            False,
            "pkexec was not found. Install data/99-deepcool-digital.rules and "
            "data/99-deepcool-msi-mystic-light.rules in /etc/udev/rules.d, then "
            "run sudo udevadm control --reload-rules && sudo udevadm trigger "
            "--action=add --subsystem-match=hidraw",
        )

    temp_paths: list[str] = []
    parts: list[str] = []
    try:
        for destination_path, content in missing:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".rules", delete=False, encoding="utf-8"
            ) as handle:
                handle.write(content)
                temp_paths.append(handle.name)
            parts.append(
                "install -m 0644 "
                f"{shlex.quote(temp_paths[-1])} "
                f"{shlex.quote(str(destination_path))}"
            )
        parts.append("udevadm control --reload-rules")
        # A synthetic "add" event is required for group ownership and the
        # uaccess ACL to be applied to already-present hidraw nodes.
        parts.append("udevadm trigger --action=add --subsystem-match=hidraw")
        command = " && ".join(parts)
        try:
            result = subprocess.run(
                [pkexec, "sh", "-c", command],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"Could not run pkexec: {exc}"
    finally:
        for temp_path in temp_paths:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        if result.returncode in (126, 127):
            message = message or "Authentication was cancelled"
        return False, message or "Installing the permission rules failed"
    if existing:
        return True, "Permissions refreshed. Reconnect the device if it is still busy."
    return True, "Permissions installed. Reconnect the device if it is still busy."
