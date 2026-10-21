"""Display configuration page."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..controller import Controller  # noqa: E402
from .widgets import SegmentedPreview, card, section_title  # noqa: E402

PRIMARY = [
    ("cpu_temp", "CPU temperature"),
    ("cpu_usage", "CPU usage"),
    ("auto", "Auto cycle"),
]
SECONDARY = [
    ("gpu_temp", "GPU temperature"),
    ("gpu_usage", "GPU usage"),
    ("auto", "Auto cycle"),
    ("off", "Off"),
]
UNITS = [False, True]


class DisplayPage(Gtk.ScrolledWindow):
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

        title = Gtk.Label(label="Display", xalign=0)
        title.add_css_class("page-title")
        outer.append(title)
        subtitle = Gtk.Label(
            label="Choose what the two readouts show. Changes are applied immediately.",
            xalign=0,
            wrap=True,
        )
        subtitle.add_css_class("page-subtitle")
        outer.append(subtitle)

        # Preview card
        preview_card = card()
        preview_card.append(section_title("Live preview", "This is exactly what the panel receives."))
        self.preview = SegmentedPreview()
        self.preview.set_content_height(280)
        self.preview.set_margin_top(4)
        preview_card.append(self.preview)
        outer.append(preview_card)

        # Readouts
        readouts = Adw.PreferencesGroup()
        readouts.set_title("Readouts")
        readouts.set_description("The primary and secondary values are independent. Either can auto-cycle.")
        self.primary_row = Adw.ComboRow(title="Primary readout")
        self.primary_row.set_model(Gtk.StringList.new([label for _, label in PRIMARY]))
        self.primary_row.connect("notify::selected", self._on_primary)
        readouts.add(self.primary_row)

        self.secondary_row = Adw.ComboRow(title="Secondary readout")
        self.secondary_row.set_model(Gtk.StringList.new([label for _, label in SECONDARY]))
        self.secondary_row.connect("notify::selected", self._on_secondary)
        readouts.add(self.secondary_row)
        outer.append(readouts)

        # Behaviour
        behaviour = Adw.PreferencesGroup()
        behaviour.set_title("Behaviour")

        self.unit_row = Adw.ComboRow(title="Temperature unit")
        self.unit_row.set_model(Gtk.StringList.new(["Celsius (°C)", "Fahrenheit (°F)"]))
        self.unit_row.connect("notify::selected", self._on_unit)
        behaviour.add(self.unit_row)

        self.interval_row = Adw.SpinRow.new_with_range(0.25, 5.0, 0.25)
        self.interval_row.set_title("Refresh interval")
        self.interval_row.set_subtitle("How often a new packet is written to the display.")
        self.interval_row.set_digits(2)
        self.interval_row.connect("notify::value", self._on_interval)
        behaviour.add(self.interval_row)

        self.auto_row = Adw.SpinRow.new_with_range(3, 120, 1)
        self.auto_row.set_title("Auto cycle every")
        self.auto_row.set_subtitle("Used by either readout when Auto cycle is selected.")
        self.auto_row.set_digits(0)
        self.auto_row.connect("notify::value", self._on_auto)
        behaviour.add(self.auto_row)
        outer.append(behaviour)

        # Actions / explanation
        actions = Adw.PreferencesGroup()
        actions.set_title("Status bar")
        info = Adw.ActionRow()
        info.set_title("Ten-cell load bars")
        info.set_subtitle("The bars always follow CPU and GPU utilisation, even in temperature mode.")
        info.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
        actions.add(info)

        send_row = Adw.ActionRow()
        send_row.set_title("Send a packet now")
        send_row.set_subtitle("Useful after reconnecting the display.")
        button = Gtk.Button(label="Send now")
        button.add_css_class("suggested-action")
        button.set_valign(Gtk.Align.CENTER)
        button.connect("clicked", self._send_now)
        send_row.add_suffix(button)
        actions.add(send_row)
        outer.append(actions)

        controller.connect("config-changed", lambda _c: self._sync())
        controller.connect("metrics-changed", lambda _c: self._refresh_preview())
        self._sync()

    def _sync(self) -> None:
        self._syncing = True
        config = self.controller.config
        primary_map = [key for key, _ in PRIMARY]
        secondary_map = [key for key, _ in SECONDARY]
        self.primary_row.set_selected(primary_map.index(config.primary) if config.primary in primary_map else 0)
        self.secondary_row.set_selected(
            secondary_map.index(config.secondary) if config.secondary in secondary_map else 0
        )
        self.unit_row.set_selected(1 if config.fahrenheit else 0)
        self.interval_row.set_value(config.interval_ms / 1000.0)
        self.auto_row.set_value(config.auto_cycle_s)
        self.preview.set_accent(config.accent_color)
        self.preview.set_animations(config.animations)
        self._syncing = False
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        c = self.controller
        fahrenheit = c.config.fahrenheit
        cpu_temp = c.cpu_temp
        gpu_temp = c.gpu_temp
        if fahrenheit:
            cpu_temp = 32 + 1.8 * cpu_temp if cpu_temp else 0
            gpu_temp = 32 + 1.8 * gpu_temp if gpu_temp else 0
        primary_value = cpu_temp if c.effective_primary == "cpu_temp" else c.cpu_usage
        secondary_mode = c.effective_secondary
        secondary_value = gpu_temp if secondary_mode == "gpu_temp" else c.gpu_usage
        if secondary_mode == "off" or not c.gpu_available:
            secondary_value = None
        self.preview.set_state(
            primary_mode=c.effective_primary,
            primary_value=primary_value,
            primary_percent=c.cpu_usage,
            secondary_mode=secondary_mode,
            secondary_value=secondary_value,
            secondary_percent=c.gpu_usage,
            fahrenheit=fahrenheit,
            connected=c.writable or c.demo,
            auto=c.config.primary == "auto",
        )

    def _on_primary(self, row: Adw.ComboRow, _pspec) -> None:
        if self._syncing:
            return
        index = row.get_selected()
        if 0 <= index < len(PRIMARY):
            self.controller.configure(primary=PRIMARY[index][0])

    def _on_secondary(self, row: Adw.ComboRow, _pspec) -> None:
        if self._syncing:
            return
        index = row.get_selected()
        if 0 <= index < len(SECONDARY):
            self.controller.configure(secondary=SECONDARY[index][0])

    def _on_unit(self, row: Adw.ComboRow, _pspec) -> None:
        if self._syncing:
            return
        self.controller.configure(fahrenheit=row.get_selected() == 1)

    def _on_interval(self, row: Adw.SpinRow, _pspec) -> None:
        if self._syncing:
            return
        self.controller.configure(interval_ms=int(round(row.get_value() * 1000)))

    def _on_auto(self, row: Adw.SpinRow, _pspec) -> None:
        if self._syncing:
            return
        self.controller.configure(auto_cycle_s=int(round(row.get_value())))

    def _send_now(self, _button: Gtk.Button) -> None:
        self.controller.send_now()
