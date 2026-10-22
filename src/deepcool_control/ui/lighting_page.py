"""Case lighting configuration page backed by OpenRGB."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from .. import lighting  # noqa: E402
from ..controller import Controller  # noqa: E402
from .widgets import card, section_title  # noqa: E402

ALL_ZONES = "All zones"


def _rgba_to_hex(rgba: Gdk.RGBA) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        max(0, min(255, round(rgba.red * 255))),
        max(0, min(255, round(rgba.green * 255))),
        max(0, min(255, round(rgba.blue * 255))),
    )


class LightingPage(Gtk.ScrolledWindow):
    """Device, zone, effect, color and brightness controls for case ARGB."""

    def __init__(self, controller: Controller, window) -> None:
        super().__init__()
        self.controller = controller
        self.window = window
        self._devices: list[lighting.LightingDevice] = []
        self._syncing = False
        self._busy = False
        self._pending_color = controller.config.lighting_color
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

        title = Gtk.Label(label="Lighting", xalign=0)
        title.add_css_class("page-title")
        outer.append(title)
        subtitle = Gtk.Label(
            label="Control case and motherboard ARGB through OpenRGB.",
            xalign=0,
            wrap=True,
        )
        subtitle.add_css_class("page-subtitle")
        outer.append(subtitle)

        self._build_status(outer)
        self._build_controls(outer)
        self._build_help(outer)

        self._update_controls()
        self._load_devices()

    # ------------------------------------------------------------------- ui
    def _build_status(self, outer: Gtk.Box) -> None:
        status = Adw.PreferencesGroup()
        status.set_title("OpenRGB")
        self.status_row = Adw.ActionRow()
        self.status_row.set_title("RGB controller")
        self.status_row.set_subtitle("Looking for OpenRGB…")
        self.status_row.add_prefix(
            Gtk.Image.new_from_icon_name("preferences-color-symbolic")
        )
        self.refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.refresh_button.set_tooltip_text("Refresh RGB controllers")
        self.refresh_button.add_css_class("flat")
        self.refresh_button.connect("clicked", lambda _button: self._load_devices())
        self.status_row.add_suffix(self.refresh_button)
        status.add(self.status_row)
        outer.append(status)

    def _build_controls(self, outer: Gtk.Box) -> None:
        group = Adw.PreferencesGroup()
        group.set_title("Lighting")
        group.set_description(
            "Choose a controller and zone, then apply a color or effect. "
            "The setting is stored by OpenRGB on the RGB controller."
        )

        self.device_row = Adw.ComboRow(title="Controller")
        self.device_row.connect("notify::selected", self._on_device)
        group.add(self.device_row)

        self.zone_row = Adw.ComboRow(title="Zone")
        self.zone_row.set_subtitle("Leave on All zones to update every header.")
        group.add(self.zone_row)

        self.mode_row = Adw.ComboRow(title="Effect")
        self.mode_row.set_subtitle("Direct gives the most predictable single color.")
        group.add(self.mode_row)

        self.color_row = Adw.ActionRow()
        self.color_row.set_title("Color")
        self.color_row.set_subtitle("Choose a color, then press Apply.")
        self.color_button = Gtk.ColorButton()
        self.color_button.set_use_alpha(False)
        self.color_button.set_title("Case lighting color")
        self.color_button.set_tooltip_text("Case lighting color")
        self.color_button.set_valign(Gtk.Align.CENTER)
        self.color_button.connect("color-set", self._on_color_set)
        self.color_row.add_suffix(self.color_button)
        group.add(self.color_row)

        self.brightness_row = Adw.SpinRow.new_with_range(0, 100, 1)
        self.brightness_row.set_title("Brightness")
        self.brightness_row.set_subtitle("Percentage reported by OpenRGB. Not every effect uses it.")
        self.brightness_row.set_digits(0)
        self.brightness_row.set_value(self.controller.config.lighting_brightness)
        group.add(self.brightness_row)

        self.apply_row = Adw.ActionRow()
        self.apply_row.set_title("Apply lighting")
        self.apply_row.set_subtitle("Send the selected color to the controller.")
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_valign(Gtk.Align.CENTER)
        self.off_button = Gtk.Button(label="Turn off")
        self.off_button.add_css_class("flat")
        self.off_button.connect("clicked", self._turn_off)
        buttons.append(self.off_button)
        self.apply_button = Gtk.Button(label="Apply")
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.connect("clicked", self._apply)
        buttons.append(self.apply_button)
        self.apply_row.add_suffix(buttons)
        group.add(self.apply_row)
        outer.append(group)

        self._set_color(self._pending_color)
        self.color_row.set_subtitle(f"{self._pending_color} saved. Press Apply to send.")

    def _build_help(self, outer: Gtk.Box) -> None:
        help_card = card()
        help_card.append(
            section_title(
                "How case lighting works",
                "The DeepCool display's USB protocol only drives the numeric panel. "
                "Case ARGB is controlled separately through OpenRGB and the "
                "motherboard RGB header.",
            )
        )
        install = Gtk.Label(
            label=(
                "If OpenRGB is missing, install it from your distribution "
                "(package name: openrgb), then press Refresh. If a controller is "
                "not detected, sign out and back in so OpenRGB's udev rule is "
                "applied, and close any other RGB software."
            ),
            xalign=0,
            wrap=True,
        )
        install.add_css_class("about-text")
        help_card.append(install)
        outer.append(help_card)

    # -------------------------------------------------------------- devices
    def _load_devices(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._update_controls()
        self.status_row.set_subtitle("Looking for OpenRGB devices…")
        self._run_async(
            lighting.list_devices,
            self._devices_loaded,
            self._devices_failed,
        )

    def _devices_loaded(self, devices: list[lighting.LightingDevice]) -> bool:
        self._busy = False
        self._devices = list(devices)
        self.status_row.set_tooltip_text("")
        if not devices:
            self.status_row.set_subtitle(
                "OpenRGB is installed, but no controllable RGB device was found."
            )
            self._clear_device_controls()
        else:
            self.status_row.set_subtitle(
                f"OpenRGB detected {len(devices)} controller"
                f"{'' if len(devices) == 1 else 's'}."
            )
            self.device_row.set_model(
                Gtk.StringList.new([device.label for device in devices])
            )
            self._select_saved_device()
        self._update_controls()
        return False

    def _devices_failed(self, message: str) -> bool:
        self._busy = False
        self._devices = []
        self.status_row.set_subtitle(message)
        self.status_row.set_tooltip_text(
            "Fedora: sudo dnf install openrgb\n"
            "Debian/Ubuntu: sudo apt install openrgb\n"
            "Then sign out and back in so OpenRGB's udev rule is applied."
        )
        self._clear_device_controls()
        self._update_controls()
        return False

    def _clear_device_controls(self) -> None:
        self._syncing = True
        self.device_row.set_model(Gtk.StringList.new([]))
        self.zone_row.set_model(Gtk.StringList.new([ALL_ZONES]))
        self.zone_row.set_selected(0)
        self.mode_row.set_model(Gtk.StringList.new([lighting.DEFAULT_MODE]))
        self.mode_row.set_selected(0)
        self._syncing = False

    def _select_saved_device(self) -> None:
        config = self.controller.config
        index = next(
            (
                position
                for position, device in enumerate(self._devices)
                if device.name == config.lighting_device
            ),
            0,
        )
        self._syncing = True
        self.device_row.set_selected(index)
        self._sync_device(index, use_config=True)
        self._syncing = False

    def _on_device(self, row: Adw.ComboRow, _pspec) -> None:
        if self._syncing:
            return
        self._sync_device(row.get_selected(), use_config=False)

    def _sync_device(self, index: int, *, use_config: bool) -> None:
        if not 0 <= index < len(self._devices):
            return
        device = self._devices[index]
        config = self.controller.config

        zones = [ALL_ZONES, *device.zones]
        self.zone_row.set_model(Gtk.StringList.new(zones))
        zone_index = 0
        if use_config and config.lighting_zone in device.zones:
            zone_index = device.zones.index(config.lighting_zone) + 1
        self.zone_row.set_selected(zone_index)

        modes = list(device.modes) or [lighting.DEFAULT_MODE]
        self.mode_row.set_model(Gtk.StringList.new(modes))
        mode_index = 0
        if use_config and config.lighting_mode in modes:
            mode_index = modes.index(config.lighting_mode)
        elif device.active_mode in modes:
            mode_index = modes.index(device.active_mode)
        self.mode_row.set_selected(mode_index)

    def _current_device(self) -> lighting.LightingDevice | None:
        index = self.device_row.get_selected()
        if 0 <= index < len(self._devices):
            return self._devices[index]
        return None

    def _selected_zone(self) -> tuple[str, int | None]:
        device = self._current_device()
        if device is None:
            return "", None
        index = self.zone_row.get_selected()
        if 0 < index <= len(device.zones):
            return device.zones[index - 1], index - 1
        return "", None

    def _selected_mode(self) -> str:
        model = self.mode_row.get_model()
        index = self.mode_row.get_selected()
        if model is None or index < 0 or index >= model.get_n_items():
            return ""
        return model.get_string(index)

    # --------------------------------------------------------------- actions
    def _on_color_set(self, button: Gtk.ColorButton) -> None:
        self._pending_color = _rgba_to_hex(button.get_rgba())
        self.color_row.set_subtitle(
            f"{self._pending_color} selected. Press Apply to send."
        )

    def _apply(self, _button: Gtk.Button | None = None) -> None:
        self._send(color=self._pending_color)

    def _turn_off(self, _button: Gtk.Button) -> None:
        device = self._current_device()
        mode = "Direct" if device and "Direct" in device.modes else self._selected_mode()
        self._pending_color = "#000000"
        self._set_color(self._pending_color)
        self._send(color=self._pending_color, brightness=0, mode=mode)

    def _send(
        self,
        *,
        color: str,
        brightness: int | None = None,
        mode: str | None = None,
    ) -> None:
        if self._busy:
            return
        device = self._current_device()
        if device is None:
            self.controller.emit("toast", "No RGB controller selected", "error")
            return
        try:
            color = lighting.normalize_color(color)
        except ValueError as exc:
            self.controller.emit("toast", str(exc), "error")
            return

        mode = self._selected_mode() if mode is None else mode
        if brightness is None:
            brightness = int(round(self.brightness_row.get_value()))
        zone_name, zone_index = self._selected_zone()

        self.controller.configure(
            lighting_device=device.name,
            lighting_zone=zone_name,
            lighting_color=color,
            lighting_mode=mode or lighting.DEFAULT_MODE,
            lighting_brightness=brightness,
        )
        self._pending_color = color
        self._set_color(color)
        self.color_row.set_subtitle(f"{color} selected. Press Apply to send.")
        self._busy = True
        self.apply_row.set_subtitle("Applying lighting…")
        self._update_controls()
        self._run_async(
            lambda: lighting.apply_color(
                device,
                color,
                mode=mode or None,
                brightness=brightness,
                zone_index=zone_index,
            ),
            self._apply_done,
            self._apply_failed,
        )

    def _apply_done(self, _result: object) -> bool:
        self._busy = False
        self.apply_row.set_subtitle("Applied. Press Apply again after changing the controls.")
        self._update_controls()
        self.controller.emit("toast", "Case lighting updated", "success")
        return False

    def _apply_failed(self, message: str) -> bool:
        self._busy = False
        self.apply_row.set_subtitle("Could not apply lighting.")
        self._update_controls()
        self.controller.emit("toast", f"Lighting update failed: {message}", "error")
        return False

    # --------------------------------------------------------------- helpers
    def _set_color(self, color: str) -> None:
        rgba = Gdk.RGBA()
        if rgba.parse(color):
            self.color_button.set_rgba(rgba)

    def _update_controls(self) -> None:
        enabled = bool(self._devices) and not self._busy
        for widget in (
            self.device_row,
            self.zone_row,
            self.mode_row,
            self.color_row,
            self.brightness_row,
            self.apply_button,
            self.off_button,
            self.color_button,
        ):
            widget.set_sensitive(enabled)
        self.refresh_button.set_sensitive(not self._busy)

    @staticmethod
    def _run_async(function, on_success, on_failure) -> None:
        def worker() -> None:
            try:
                result = function()
            except Exception as exc:  # pragma: no cover - UI boundary
                GLib.idle_add(on_failure, str(exc))
            else:
                GLib.idle_add(on_success, result)

        threading.Thread(target=worker, daemon=True).start()
