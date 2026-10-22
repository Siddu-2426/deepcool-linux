"""Settings and integration page."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from .. import system  # noqa: E402
from ..config import ACCENTS, VERSION  # noqa: E402
from ..controller import Controller  # noqa: E402
from .widgets import card, section_title  # noqa: E402

SCHEMES = [("system", "Follow system"), ("light", "Light"), ("dark", "Dark")]
SCHEME_VALUES = {
    "system": Adw.ColorScheme.DEFAULT,
    "light": Adw.ColorScheme.FORCE_LIGHT,
    "dark": Adw.ColorScheme.FORCE_DARK,
}


class SettingsPage(Gtk.ScrolledWindow):
    def __init__(self, controller: Controller, window) -> None:
        super().__init__()
        self.controller = controller
        self.window = window
        self._syncing = False
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_hexpand(True)
        self.set_vexpand(True)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(1000)
        clamp.set_tightening_threshold(700)
        self.set_child(clamp)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        outer.set_margin_top(26)
        outer.set_margin_bottom(32)
        outer.set_margin_start(28)
        outer.set_margin_end(28)
        clamp.set_child(outer)

        title = Gtk.Label(label="Settings", xalign=0)
        title.add_css_class("page-title")
        outer.append(title)
        subtitle = Gtk.Label(
            label="Appearance, startup behaviour and system access.",
            xalign=0,
            wrap=True,
        )
        subtitle.add_css_class("page-subtitle")
        outer.append(subtitle)

        # Appearance
        appearance = Adw.PreferencesGroup()
        appearance.set_title("Appearance")
        self.scheme_row = Adw.ComboRow(title="Colour scheme")
        self.scheme_row.set_model(Gtk.StringList.new([label for _, label in SCHEMES]))
        self.scheme_row.connect("notify::selected", self._on_scheme)
        appearance.add(self.scheme_row)

        accent_row = Adw.ActionRow()
        accent_row.set_title("Accent colour")
        accent_row.set_subtitle("Used by the preview glow, charts and highlights.")
        swatches = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        swatches.set_valign(Gtk.Align.CENTER)
        self._swatches: dict[str, Gtk.ToggleButton] = {}
        first: Gtk.ToggleButton | None = None
        for name, (color, _soft) in ACCENTS.items():
            button = Gtk.ToggleButton()
            button.set_tooltip_text(name.title())
            button.add_css_class("accent-swatch")
            button.add_css_class(f"swatch-{name}")
            button.set_size_request(26, 26)
            if first is None:
                first = button
            else:
                button.set_group(first)
            button.connect("toggled", self._on_accent, name)
            self._swatches[name] = button
            swatches.append(button)
        accent_row.add_suffix(swatches)
        appearance.add(accent_row)

        self.animations_row = Adw.SwitchRow(title="Animate the preview")
        self.animations_row.set_subtitle("Smooth bar transitions and a subtle live pulse.")
        self.animations_row.connect("notify::active", self._on_animations)
        appearance.add(self.animations_row)
        outer.append(appearance)

        # Startup
        startup = Adw.PreferencesGroup()
        startup.set_title("Startup")
        self.autostart_row = Adw.SwitchRow(title="Start at login")
        self.autostart_row.set_subtitle("Open the window when you sign in to your desktop.")
        self.autostart_row.connect("notify::active", self._on_autostart)
        startup.add(self.autostart_row)

        self.service_row = Adw.SwitchRow(title="Background service")
        self.service_row.set_subtitle(
            "Keep the display and cabinet lighting running after the window "
            "closes (systemd user service)."
        )
        self.service_row.connect("notify::active", self._on_service)
        startup.add(self.service_row)
        outer.append(startup)

        # Access
        access = Adw.PreferencesGroup()
        access.set_title("Device access")
        access.set_description("Fedora grants hidraw access through a udev rule.")
        self.access_row = Adw.ActionRow()
        self.access_row.set_title("Display permissions")
        self.access_row.add_prefix(Gtk.Image.new_from_icon_name("channel-secure-symbolic"))
        grant = Gtk.Button(label="Grant access")
        grant.add_css_class("suggested-action")
        grant.set_valign(Gtk.Align.CENTER)
        grant.connect("clicked", self._grant_access)
        self.access_row.add_suffix(grant)
        access.add(self.access_row)

        self.service_state_row = Adw.ActionRow()
        self.service_state_row.set_title("Background service status")
        self.service_state_row.set_subtitle("—")
        access.add(self.service_state_row)
        outer.append(access)

        # Diagnostics
        diagnostics = Adw.PreferencesGroup()
        diagnostics.set_title("Diagnostics")
        self.diag_rows: dict[str, Adw.ActionRow] = {}
        for key, title_text in (
            ("device", "Device"),
            ("serial", "Serial number"),
            ("packet", "Last packet"),
            ("mode", "Current readout"),
        ):
            row = Adw.ActionRow(title=title_text)
            row.set_subtitle("—")
            diagnostics.add(row)
            self.diag_rows[key] = row
        copy_row = Adw.ActionRow()
        copy_row.set_title("Copy diagnostics")
        copy_row.set_subtitle("Device, permissions, service and sensor information.")
        copy = Gtk.Button(label="Copy")
        copy.set_valign(Gtk.Align.CENTER)
        copy.connect("clicked", self._copy_diagnostics)
        copy_row.add_suffix(copy)
        diagnostics.add(copy_row)
        outer.append(diagnostics)

        # About
        about = card()
        about.append(section_title("DeepCool Control", f"Version {VERSION} · MIT licensed"))
        text = Gtk.Label(
            label=(
                "A native GTK4 companion for DeepCool CH-series digital displays. "
                "Built from the USB protocol used by CH360 DIGITAL, CH560 DIGITAL and MORPHEUS."
            ),
            xalign=0,
            wrap=True,
        )
        text.add_css_class("about-text")
        about.append(text)
        open_about = Gtk.Button(label="About DeepCool Control")
        open_about.add_css_class("flat")
        open_about.set_halign(Gtk.Align.START)
        open_about.connect("clicked", lambda _b: window.show_about())
        about.append(open_about)
        outer.append(about)

        controller.connect("config-changed", lambda _c: self._sync())
        controller.connect("state-changed", lambda _c: self._update_status())
        self._sync()
        self._update_status()

    # ------------------------------------------------------------------ sync
    def _sync(self) -> None:
        self._syncing = True
        config = self.controller.config
        scheme_index = next(
            (index for index, (key, _label) in enumerate(SCHEMES) if key == config.color_scheme),
            0,
        )
        self.scheme_row.set_selected(scheme_index)
        for name, button in self._swatches.items():
            button.set_active(name == config.accent)
        self.animations_row.set_active(config.animations)
        self.autostart_row.set_active(config.autostart)
        self.service_row.set_active(config.service)
        self._syncing = False
        Adw.StyleManager.get_default().set_color_scheme(SCHEME_VALUES[config.color_scheme])

    def _update_status(self) -> None:
        c = self.controller
        self.diag_rows["device"].set_subtitle(c.device_label)
        self.diag_rows["serial"].set_subtitle(c.device_serial or "—")
        self.diag_rows["packet"].set_subtitle(c.last_write)
        self.diag_rows["mode"].set_subtitle(
            f"{c.effective_primary} / {c.effective_secondary}"
        )
        installed = system.udev_rule_installed()
        if c.permission_required:
            self.access_row.set_subtitle(
                "Permission denied. Use Grant access to refresh the udev ACL."
            )
        elif installed:
            self.access_row.set_subtitle("Permission rule installed. The display is ready.")
        else:
            self.access_row.set_subtitle("Not installed. Needed for display access without root.")
        service_text = "Running" if system.service_active() else "Stopped"
        if system.service_enabled() and service_text == "Stopped":
            service_text = "Enabled, not running"
        self.service_state_row.set_subtitle(service_text)

    # -------------------------------------------------------------- handlers
    def _on_scheme(self, row: Adw.ComboRow, _pspec) -> None:
        if self._syncing:
            return
        index = row.get_selected()
        if 0 <= index < len(SCHEMES):
            self.controller.set_color_scheme(SCHEMES[index][0])

    def _on_accent(self, button: Gtk.ToggleButton, name: str) -> None:
        if self._syncing or not button.get_active():
            return
        self.controller.set_accent(name)

    def _on_animations(self, row: Adw.SwitchRow, _pspec) -> None:
        if self._syncing:
            return
        self.controller.set_animations(row.get_active())

    def _on_autostart(self, row: Adw.SwitchRow, _pspec) -> None:
        if self._syncing:
            return
        if not self.controller.toggle_autostart(row.get_active()):
            self._syncing = True
            row.set_active(not row.get_active())
            self._syncing = False

    def _on_service(self, row: Adw.SwitchRow, _pspec) -> None:
        if self._syncing:
            return
        if not self.controller.toggle_service(row.get_active()):
            self._syncing = True
            row.set_active(not row.get_active())
            self._syncing = False
        self._update_status()

    def _grant_access(self, _button: Gtk.Button) -> None:
        self.controller.install_permissions()

    def _copy_diagnostics(self, _button: Gtk.Button) -> None:
        c = self.controller
        text = "\n".join(
            [
                f"DeepCool Control {VERSION}",
                f"device={c.device_label}",
                f"serial={c.device_serial or '-'}",
                f"connected={c.connected} writable={c.writable}",
                f"permission_required={c.permission_required} service_owner={c.service_owner}",
                f"udev_rule={system.udev_rule_installed()}",
                f"service_active={system.service_active()}",
                f"cpu={c.cpu_model} sensor={c.cpu_sensor_label}",
                f"gpu={c.gpu_name}",
                f"config={c.config.to_dict()}",
            ]
        )
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)
        self.controller.emit("toast", "Diagnostics copied to clipboard", "success")
