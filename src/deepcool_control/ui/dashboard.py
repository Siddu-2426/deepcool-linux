"""Overview page."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango  # noqa: E402

from ..config import ACCENTS  # noqa: E402
from ..controller import Controller  # noqa: E402
from .widgets import SegmentedPreview, StatCard, card, section_title  # noqa: E402

MODE_BUTTONS = [
    ("cpu_temp", "CPU °C"),
    ("cpu_usage", "CPU %"),
    ("gpu_temp", "GPU °C"),
    ("gpu_usage", "GPU %"),
    ("auto", "Auto"),
]


class SensorRow(Gtk.Box):
    def __init__(self, title: str, icon: str) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.add_css_class("sensor-row")
        self.set_margin_top(2)
        self.set_margin_bottom(2)
        image = Gtk.Image.new_from_icon_name(icon)
        image.set_pixel_size(18)
        image.add_css_class("sensor-icon")
        self.append(image)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_hexpand(True)
        self._title = Gtk.Label(label=title, xalign=0)
        self._title.add_css_class("sensor-name")
        text.append(self._title)
        self._subtitle = Gtk.Label(label="", xalign=0)
        self._subtitle.add_css_class("sensor-detail")
        self._subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(self._subtitle)
        self.append(text)
        self._value = Gtk.Label(label="--")
        self._value.add_css_class("sensor-value")
        self.append(self._value)

    def update(self, title: str, subtitle: str, value: str) -> None:
        self._title.set_text(title)
        self._subtitle.set_text(subtitle)
        self._subtitle.set_tooltip_text(subtitle)
        self._value.set_text(value)


class DashboardPage(Gtk.ScrolledWindow):
    def __init__(self, controller: Controller, window) -> None:
        super().__init__()
        self.controller = controller
        self.window = window
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_hexpand(True)
        self.set_vexpand(True)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(1160)
        clamp.set_tightening_threshold(760)
        self.set_child(clamp)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        outer.set_margin_top(26)
        outer.set_margin_bottom(32)
        outer.set_margin_start(28)
        outer.set_margin_end(28)
        clamp.set_child(outer)

        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label="Overview", xalign=0)
        title.add_css_class("page-title")
        titles.append(title)
        subtitle = Gtk.Label(
            label="Live readings mirrored to your case display.", xalign=0
        )
        subtitle.add_css_class("page-subtitle")
        titles.append(subtitle)
        heading.append(titles)

        self._live_badge = Gtk.Label(label="LIVE")
        self._live_badge.add_css_class("live-badge")
        self._live_badge.set_valign(Gtk.Align.CENTER)
        heading.append(self._live_badge)
        outer.append(heading)

        # ------------------------------------------------------------- hero
        hero = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=26)
        hero.add_css_class("hero-card")
        hero.set_margin_top(2)
        self.hero = hero

        self.preview = SegmentedPreview()
        self.preview.set_hexpand(True)
        self.preview.set_size_request(520, 300)
        hero.append(self.preview)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        side.set_size_request(286, -1)
        side.set_valign(Gtk.Align.CENTER)
        self.hero_side = side
        self._device_name = Gtk.Label(label="CH360 DIGITAL", xalign=0)
        self._device_name.add_css_class("hero-title")
        side.append(self._device_name)
        self._device_meta = Gtk.Label(label="Looking for a display…", xalign=0)
        self._device_meta.add_css_class("hero-meta")
        self._device_meta.set_wrap(True)
        side.append(self._device_meta)

        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._status_pill = Gtk.Label(label="Disconnected")
        self._status_pill.add_css_class("status-pill")
        self._status_pill.add_css_class("disconnected")
        status_row.append(self._status_pill)
        side.append(status_row)

        quick = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        quick.set_margin_top(6)
        quick_label = Gtk.Label(label="QUICK MODE", xalign=0)
        quick_label.add_css_class("eyebrow")
        quick.append(quick_label)
        mode_grid = Gtk.Grid(column_spacing=7, row_spacing=7, column_homogeneous=True)
        self._mode_buttons: dict[str, Gtk.ToggleButton] = {}
        first: Gtk.ToggleButton | None = None
        for index, (mode, label) in enumerate(MODE_BUTTONS):
            button = Gtk.ToggleButton(label=label)
            button.add_css_class("mode-chip")
            if first is not None:
                button.set_group(first)
            else:
                first = button
            button.connect("toggled", self._on_mode_toggled, mode)
            self._mode_buttons[mode] = button
            mode_grid.attach(button, index % 3, index // 3, 1, 1)
        quick.append(mode_grid)
        side.append(quick)

        settings_button = Gtk.Button(label="Open display settings")
        settings_button.add_css_class("flat")
        settings_button.add_css_class("hero-link")
        settings_button.connect("clicked", lambda _b: window.show_page("display"))
        side.append(settings_button)
        hero.append(side)
        outer.append(hero)

        # ------------------------------------------------------------ cards
        cards_label = section_title("Live metrics", "Sampled every second from this machine.")
        outer.append(cards_label)

        self._accent = controller.config.accent_color
        self.card_cpu_temp = StatCard(
            "temperature-symbolic", "CPU temperature", self._accent, 105
        )
        self.card_cpu_usage = StatCard(
            "power-profile-performance-symbolic", "CPU usage", self._accent, 100
        )
        self.card_gpu_temp = StatCard(
            "video-display-symbolic", "GPU temperature", self._accent, 105
        )
        self.card_gpu_usage = StatCard(
            "applications-graphics-symbolic", "GPU usage", self._accent, 100
        )

        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_homogeneous(True)
        flow.set_column_spacing(14)
        flow.set_row_spacing(14)
        flow.set_max_children_per_line(4)
        flow.set_min_children_per_line(4)
        flow.set_valign(Gtk.Align.START)
        self.metrics_flow = flow
        for widget in (
            self.card_cpu_temp,
            self.card_cpu_usage,
            self.card_gpu_temp,
            self.card_gpu_usage,
        ):
            flow.insert(widget, -1)
        outer.append(flow)

        # ----------------------------------------------------------- bottom
        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        bottom.set_homogeneous(True)

        sensors_card = card()
        sensors_card.set_hexpand(True)
        sensors_card.append(section_title("Sensors", "What the display is reading right now."))
        self.row_cpu = SensorRow("CPU", "temperature-symbolic")
        self.row_gpu = SensorRow("GPU", "video-display-symbolic")
        self.row_ram = SensorRow("Memory", "computer-symbolic")
        self.row_storage = SensorRow("Storage", "drive-harddisk-symbolic")
        for row in (self.row_cpu, self.row_gpu, self.row_ram, self.row_storage):
            sensors_card.append(row)
        details = Gtk.Button(label="Sensor sources")
        details.add_css_class("flat")
        details.add_css_class("inline-link")
        details.set_halign(Gtk.Align.START)
        details.connect("clicked", lambda _b: window.show_page("sensors"))
        sensors_card.append(details)
        bottom.append(sensors_card)

        status_card = card()
        status_card.set_hexpand(True)
        status_card.append(section_title("Display status", "Packet and connection details."))
        self.status_rows: dict[str, Gtk.Label] = {}
        for key, title_text in (
            ("showing", "Showing"),
            ("refresh", "Refresh rate"),
            ("units", "Temperature unit"),
            ("packet", "Last packet"),
        ):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.add_css_class("sensor-row")
            label = Gtk.Label(label=title_text, xalign=0)
            label.set_hexpand(True)
            label.add_css_class("sensor-name")
            row.append(label)
            value = Gtk.Label(label="—")
            value.add_css_class("sensor-value")
            row.append(value)
            self.status_rows[key] = value
            status_card.append(row)
        bottom.append(status_card)
        outer.append(bottom)

        controller.connect("metrics-changed", lambda _c: self._update())
        controller.connect("config-changed", lambda _c: self._sync_config())
        controller.connect("state-changed", lambda _c: self._update_state())
        self._sync_config()
        self._update_state()
        self._update()

    # -------------------------------------------------------------- handlers
    def _on_mode_toggled(self, button: Gtk.ToggleButton, mode: str) -> None:
        if not button.get_active():
            return
        if self.controller.config.primary != mode:
            self.controller.configure(primary=mode)
        self.controller.send_now()

    def _sync_config(self) -> None:
        primary = self.controller.config.primary
        for mode, button in self._mode_buttons.items():
            button.set_active(mode == primary)
        fahrenheit = self.controller.config.fahrenheit
        self.status_rows["units"].set_text("Fahrenheit (°F)" if fahrenheit else "Celsius (°C)")
        self.status_rows["refresh"].set_text(f"{self.controller.config.interval_ms / 1000:g} s")
        self.preview.set_accent(self.controller.config.accent_color)
        self.preview.set_animations(self.controller.config.animations)
        for card_widget in (
            self.card_cpu_temp,
            self.card_cpu_usage,
            self.card_gpu_temp,
            self.card_gpu_usage,
        ):
            card_widget.set_accent(self.controller.config.accent_color)

    def _update_state(self) -> None:
        c = self.controller
        writable = c.writable or c.demo
        self._device_name.set_text(c.device_label)
        if c.connected:
            serial = f"SN {c.device_serial}" if c.device_serial else "USB HID"
            self._device_meta.set_text(serial)
            if writable:
                self._status_pill.set_text("Connected")
                self._status_pill.remove_css_class("disconnected")
                self._status_pill.remove_css_class("busy")
                self._status_pill.add_css_class("connected")
            elif c.permission_required:
                self._status_pill.set_text("Permission needed")
                self._status_pill.remove_css_class("connected")
                self._status_pill.remove_css_class("disconnected")
                self._status_pill.add_css_class("busy")
            elif c.service_owner:
                self._status_pill.set_text("Background service")
                self._status_pill.remove_css_class("connected")
                self._status_pill.remove_css_class("disconnected")
                self._status_pill.add_css_class("busy")
            else:
                self._status_pill.set_text("Read-only")
                self._status_pill.remove_css_class("connected")
                self._status_pill.remove_css_class("disconnected")
                self._status_pill.add_css_class("busy")
            if writable:
                self._live_badge.set_text("LIVE")
                self._live_badge.add_css_class("active")
            else:
                self._live_badge.set_text("PREVIEW")
                self._live_badge.remove_css_class("active")
        else:
            self._device_meta.set_text("Connect a supported DeepCool display over USB.")
            self._status_pill.set_text("Disconnected")
            self._status_pill.remove_css_class("connected")
            self._status_pill.remove_css_class("busy")
            self._status_pill.add_css_class("disconnected")
            self._live_badge.set_text("PREVIEW")
            self._live_badge.remove_css_class("active")
        self._update()

    def _update(self) -> None:
        c = self.controller
        fahrenheit = c.config.fahrenheit
        temp_unit = "°F" if fahrenheit else "°C"

        cpu_temp = c.cpu_temp
        gpu_temp = c.gpu_temp
        if fahrenheit and c.cpu_temp:
            cpu_temp = 32 + 1.8 * c.cpu_temp
        if fahrenheit and c.gpu_temp:
            gpu_temp = 32 + 1.8 * c.gpu_temp

        cpu_history = list(c.history["cpu_temp"])
        gpu_history = list(c.history["gpu_temp"])
        if fahrenheit:
            cpu_history = [32 + 1.8 * value for value in cpu_history]
            gpu_history = [32 + 1.8 * value for value in gpu_history]

        self.card_cpu_temp.update(
            f"{cpu_temp:.0f}" if c.cpu_temp else "--",
            temp_unit,
            f"{c.cpu_model} · {c.cpu_sensor_label}",
            cpu_history,
        )
        self.card_cpu_usage.update(
            f"{c.cpu_usage:.0f}",
            "%",
            f"{c.cpu_frequency:.0f} MHz" if c.cpu_frequency else "Processor load",
            list(c.history["cpu_usage"]),
        )
        self.card_gpu_temp.set_available(c.gpu_available)
        self.card_gpu_temp.update(
            f"{gpu_temp:.0f}" if c.gpu_available else "--",
            temp_unit,
            c.gpu_name if c.gpu_available else "No compatible GPU found",
            gpu_history,
        )
        self.card_gpu_usage.set_available(c.gpu_available)
        memory = ""
        if c.snapshot.gpu_memory_total:
            memory = f" · {c.snapshot.gpu_memory_used or 0} / {c.snapshot.gpu_memory_total} MiB"
        self.card_gpu_usage.update(
            f"{c.gpu_usage:.0f}" if c.gpu_available else "--",
            "%",
            (c.gpu_name + memory) if c.gpu_available else "No compatible GPU found",
            list(c.history["gpu_usage"]),
        )

        self.row_cpu.update(
            "CPU",
            c.cpu_sensor_label,
            f"{cpu_temp:.1f} {temp_unit}" if c.cpu_temp else "—",
        )
        self.row_gpu.update(
            "GPU",
            c.gpu_name,
            f"{gpu_temp:.0f} {temp_unit} · {c.gpu_usage:.0f}%" if c.gpu_available else "—",
        )
        self.row_ram.update("Memory", "System RAM", f"{c.ram_usage:.0f}%")
        storage = next((s for s in c.snapshot.system_sensors if "nvme" in s.chip), None)
        if storage and storage.value is not None:
            self.row_storage.update("Storage", "NVMe composite", f"{storage.value:.0f} °C")
        else:
            self.row_storage.update("Storage", "No NVMe sensor", "—")

        primary_mode = c.effective_primary
        secondary_mode = c.effective_secondary
        primary_value = cpu_temp if primary_mode == "cpu_temp" else c.cpu_usage
        secondary_value = (
            gpu_temp if secondary_mode == "gpu_temp" else c.gpu_usage
        )
        if secondary_mode == "off":
            secondary_value = None
        if not c.gpu_available and secondary_mode != "off":
            secondary_value = None
        self.preview.set_state(
            primary_mode=primary_mode,
            primary_value=primary_value,
            primary_percent=c.cpu_usage,
            secondary_mode=secondary_mode,
            secondary_value=secondary_value,
            secondary_percent=c.gpu_usage,
            fahrenheit=fahrenheit,
            connected=c.writable or c.demo,
            auto=c.config.primary == "auto",
        )

        showing = {
            "cpu_temp": "CPU temperature",
            "cpu_usage": "CPU usage",
            "gpu_temp": "GPU temperature",
            "gpu_usage": "GPU usage",
        }
        self.status_rows["showing"].set_text(
            f"{showing.get(primary_mode, primary_mode)} / {showing.get(secondary_mode, 'Off')}"
        )
        self.status_rows["packet"].set_text(c.last_write)
        for mode, button in self._mode_buttons.items():
            if mode.startswith("gpu"):
                button.set_sensitive(c.gpu_available)
