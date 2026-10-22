"""Command line entry point and GTK application for DeepCool Control."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import sys
from pathlib import Path

from .config import APP_ID, APP_NAME, VERSION, Config


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _install_icon_path() -> Path | None:
    candidate = _project_root() / "data" / "icons"
    return candidate if candidate.exists() else None


def _print_devices() -> int:
    from .device import discover_devices
    from .sensors import list_cpu_temp_sensors, list_gpus, list_system_sensors

    devices = discover_devices()
    print(f"{APP_NAME} {VERSION}")
    print()
    if not devices:
        print("Devices: none found")
    else:
        print("Devices:")
        for info in devices:
            access = "?"
            try:
                mode = os.stat(info.path).st_mode
                access = "read/write" if mode & stat.S_IWUSR else "read-only"
            except OSError:
                access = "unavailable"
            support = "supported" if info.supported else "not supported by this app"
            print(
                f"  {info.path}  {info.vid:04x}:{info.pid:04x}  "
                f"{info.display_name}  serial={info.serial or '-'}  "
                f"[{support}, user {access}]"
            )
    print()
    cpu_sensors = list_cpu_temp_sensors()
    print("CPU temperature sources:")
    for sensor in cpu_sensors or []:
        print(f"  {sensor.display}  ({sensor.id})")
    if not cpu_sensors:
        print("  none")
    print()
    gpus = list_gpus()
    print("Graphics devices:")
    for gpu in gpus or []:
        print(f"  {gpu.label}  ({gpu.id})")
    if not gpus:
        print("  none")
    print()
    system_sensors = list_system_sensors()
    print("Other temperature sources:")
    for sensor in system_sensors or []:
        print(f"  {sensor.display}  ({sensor.chip})")
    if not system_sensors:
        print("  none")
    return 0 if any(info.supported for info in devices) else 1


def _print_doctor() -> int:
    from .device import discover_devices
    from .sensors import cpu_model_name, list_gpus
    from . import lighting, system

    print(f"{APP_NAME} {VERSION}")
    print(f"Python: {platform.python_version()}")
    print(f"Platform: {platform.platform()}")
    print(f"Desktop: {os.environ.get('XDG_CURRENT_DESKTOP', 'unknown')}")
    print(f"Session: {os.environ.get('XDG_SESSION_TYPE', 'unknown')}")
    print()

    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk

        print(
            "GTK: "
            f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"
        )
        print(
            "libadwaita: "
            f"{Adw.get_major_version()}.{Adw.get_minor_version()}.{Adw.get_micro_version()}"
        )
    except Exception as exc:
        print(f"GTK: unavailable ({exc})")
    print(f"psutil: {'available' if shutil.which('python3') else 'unknown'}")
    print(f"nvidia-smi: {'available' if shutil.which('nvidia-smi') else 'not found'}")
    print(f"CPU: {cpu_model_name()}")
    gpus = list_gpus()
    print(f"GPU: {gpus[0].label if gpus else 'not detected'}")
    print()

    devices = discover_devices()
    print(f"DeepCool devices: {len(devices)}")
    for info in devices:
        try:
            mode = oct(os.stat(info.path).st_mode & 0o777)
            writable = os.access(info.path, os.W_OK)
        except OSError as exc:
            mode, writable = f"error: {exc}", False
        print(
            f"  {info.path} {info.vid:04x}:{info.pid:04x} {info.display_name} "
            f"serial={info.serial or '-'} mode={mode} writable={writable} "
            f"supported={info.supported}"
        )
    if not devices:
        print("  none")
    print()

    print(f"udev rule: {'installed' if system.udev_rule_installed() else 'missing'}")
    print(f"service: {'active' if system.service_active() else 'inactive'}")
    print(f"service enabled: {system.service_enabled()}")
    print(f"service file: {system.service_path()}")
    print(f"autostart file: {system.autostart_path()}")
    print(f"config file: {_config_path()}")
    openrgb = lighting.find_binary()
    print(f"OpenRGB: {openrgb or 'not found'}")
    if openrgb is not None:
        try:
            rgb_devices = lighting.list_devices(openrgb)
        except lighting.LightingError as exc:
            print(f"OpenRGB devices: error: {exc}")
        else:
            print(f"OpenRGB devices: {len(rgb_devices)}")
            for device in rgb_devices:
                zones = ", ".join(device.zones) or "-"
                print(
                    f"  [{device.index}] {device.name} "
                    f"zones={zones} modes={len(device.modes)}"
                )
    print()
    if not any(info.supported and os.access(info.path, os.W_OK) for info in devices):
        print("No writable supported display found. Install the udev rule using the app.")
        return 1
    return 0


def _config_path() -> Path:
    from .config import config_path

    return config_path()


def _run_gui(demo: bool = False) -> int:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, Gtk

    from .controller import Controller
    from .ui.window import MainWindow

    class DeepCoolApplication(Adw.Application):
        def __init__(self) -> None:
            super().__init__(
                application_id=APP_ID,
                flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
            )
            self.controller: Controller | None = None
            self.window: MainWindow | None = None
            self._css_loaded = False
            self._stopped = False

            quit_action = Gio.SimpleAction.new("quit", None)
            quit_action.connect("activate", lambda *_args: self.quit())
            self.add_action(quit_action)

            about_action = Gio.SimpleAction.new("about", None)
            about_action.connect("activate", self._show_about)
            self.add_action(about_action)

        def _show_about(self, *_args) -> None:
            if self.window is not None:
                self.window.show_about()

        def _load_css(self) -> None:
            display = Gdk.Display.get_default()
            if display is None:
                return
            css_path = Path(__file__).with_name("ui") / "style.css"
            provider = Gtk.CssProvider()
            try:
                provider.load_from_path(str(css_path))
            except Exception as exc:  # pragma: no cover - startup diagnostics
                print(f"Could not load stylesheet: {exc}", file=sys.stderr)
            else:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
                )
            icon_path = _install_icon_path()
            if icon_path is not None:
                theme = Gtk.IconTheme.get_for_display(display)
                theme.add_search_path(str(icon_path))
            Gtk.Window.set_default_icon_name(APP_ID)
            self._css_loaded = True

        def do_activate(self) -> None:
            if not self._css_loaded:
                self._load_css()
            if self.window is None:
                self.controller = Controller(Config.load())
                self.window = MainWindow(self, self.controller)
                start_page = os.environ.get("DEEPCOOL_START_PAGE", "")
                if start_page:
                    self.window.show_page(start_page, animate=False)
                self._apply_scheme()
                self.window.present()
                self.controller.start()
            else:
                self.window.present()

        def _apply_scheme(self) -> None:
            if self.controller is None:
                return
            mapping = {
                "system": Adw.ColorScheme.DEFAULT,
                "light": Adw.ColorScheme.FORCE_LIGHT,
                "dark": Adw.ColorScheme.FORCE_DARK,
            }
            Adw.StyleManager.get_default().set_color_scheme(
                mapping.get(self.controller.config.color_scheme, Adw.ColorScheme.DEFAULT)
            )

        def do_shutdown(self) -> None:
            if self.controller is not None and not self._stopped:
                self._stopped = True
                self.controller.shutdown()
            Adw.Application.do_shutdown(self)

        def do_startup(self) -> None:
            Adw.Application.do_startup(self)
            self.set_accels_for_action("app.quit", ["<Control>q"])
            self.set_accels_for_action("app.about", ["F1"])

    if demo:
        os.environ["DEEPCOOL_DEMO"] = "1"
    app = DeepCoolApplication()
    try:
        return app.run([sys.argv[0]])
    except KeyboardInterrupt:
        return 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deepcool-control",
        description="Native GTK4 control app for DeepCool CH-series digital displays.",
    )
    parser.add_argument("--version", action="store_true", help="show the version and exit")
    parser.add_argument("--daemon", action="store_true", help="run the background display daemon")
    parser.add_argument("--list", action="store_true", help="list DeepCool devices and sensor sources")
    parser.add_argument("--doctor", action="store_true", help="print diagnostics for troubleshooting")
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="run the interface with simulated readings and no hardware access",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"{APP_NAME} {VERSION}")
        return 0
    if args.daemon:
        from .daemon import run_daemon

        return run_daemon()
    if args.list:
        return _print_devices()
    if args.doctor:
        return _print_doctor()
    return _run_gui(demo=args.simulate)


if __name__ == "__main__":
    raise SystemExit(main())
