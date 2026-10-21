"""Sensor source selection page."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..controller import Controller  # noqa: E402
from ..sensors import list_cpu_temp_sensors, list_gpus  # noqa: E402
from .widgets import StatCard, card, section_title  # noqa: E402


class SensorsPage(Gtk.ScrolledWindow):
    def __init__(self, controller: Controller, window) -> None:
        super().__init__()
        self.controller = controller
        self.window = window
        self._syncing = False
        self._system_ids: tuple[str, ...] = ()
        self._system_rows: list[Adw.ActionRow] = []
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

        title = Gtk.Label(label="Sensors", xalign=0)
        title.add_css_class("page-title")
        outer.append(title)
        subtitle = Gtk.Label(
            label="Pick the hardware source used for each readout. Everything is read locally.",
            xalign=0,
            wrap=True,
        )
        subtitle.add_css_class("page-subtitle")
        outer.append(subtitle)

        # Highlight cards
        highlight = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        highlight.set_homogeneous(True)
        accent = controller.config.accent_color
        self.cpu_card = StatCard("temperature-symbolic", "CPU package", accent, 105)
        self.gpu_card = StatCard("video-display-symbolic", "Graphics card", accent, 105)
        highlight.append(self.cpu_card)
        highlight.append(self.gpu_card)
        outer.append(highlight)

        # Source selection
        sources = Adw.PreferencesGroup()
        sources.set_title("Sources")
        sources.set_description("Only temperature and utilisation sources are used by the display.")

        self.cpu_source_row = Adw.ComboRow(title="CPU temperature")
        self.cpu_source_row.connect("notify::selected", self._on_cpu_source)
        sources.add(self.cpu_source_row)

        self.gpu_source_row = Adw.ComboRow(title="GPU")
        self.gpu_source_row.connect("notify::selected", self._on_gpu_source)
        sources.add(self.gpu_source_row)

        refresh_row = Adw.ActionRow()
        refresh_row.set_title("Refresh sensor list")
        refresh_row.set_subtitle("Rescan hwmon and graphics devices after hardware changes.")
        refresh = Gtk.Button(label="Rescan")
        refresh.set_valign(Gtk.Align.CENTER)
        refresh.connect("clicked", self._rescan)
        refresh_row.add_suffix(refresh)
        sources.add(refresh_row)
        outer.append(sources)

        # System sensors
        self.system_group = Adw.PreferencesGroup()
        self.system_group.set_title("Other hardware")
        self.system_group.set_description("Useful context, not required by the display.")
        outer.append(self.system_group)

        note = card()
        note.append(
            section_title(
                "How readings are chosen",
                "CPU temperature prefers k10temp Tctl, then Tccd1 or the package sensor. "
                "GPU readings use nvidia-smi for NVIDIA cards and sysfs for AMD or Intel cards. "
                "No telemetry leaves this computer.",
            )
        )
        outer.append(note)

        controller.connect("metrics-changed", lambda _c: self._update())
        controller.connect("config-changed", lambda _c: self._sync_sources())
        self._sync_sources()
        self._update()

    def _rescan(self, _button: Gtk.Button) -> None:
        self._sync_sources(force=True)
        self._system_ids = ()
        self._update()
        self.controller.emit("toast", "Sensor list refreshed", "success")

    def _sync_sources(self, force: bool = False) -> None:
        self._syncing = True
        sensors = list_cpu_temp_sensors()
        labels = [
            f"{sensor.label} · {sensor.chip}" if sensor.chip not in sensor.label else sensor.label
            for sensor in sensors
        ] or ["No CPU sensor found"]
        self._cpu_ids = [sensor.id for sensor in sensors]
        self.cpu_source_row.set_model(Gtk.StringList.new(labels))
        selected = 0
        wanted = self.controller.config.cpu_sensor
        if wanted in self._cpu_ids:
            selected = self._cpu_ids.index(wanted)
        elif self._cpu_ids:
            # Mirror the reader's fallback choice.
            selected = 0
        self.cpu_source_row.set_selected(selected)
        self.cpu_source_row.set_sensitive(bool(self._cpu_ids))

        gpus = list_gpus()
        gpu_labels = [gpu.label for gpu in gpus] or ["No GPU found"]
        self._gpu_ids = [gpu.id for gpu in gpus]
        self.gpu_source_row.set_model(Gtk.StringList.new(gpu_labels))
        gpu_selected = 0
        wanted_gpu = self.controller.config.gpu_sensor
        if wanted_gpu in self._gpu_ids:
            gpu_selected = self._gpu_ids.index(wanted_gpu)
        elif self._gpu_ids:
            # NVIDIA devices are listed first, matching default_gpu().
            gpu_selected = 0
        self.gpu_source_row.set_selected(gpu_selected)
        self.gpu_source_row.set_sensitive(bool(self._gpu_ids))
        self._syncing = False

    def _on_cpu_source(self, row: Adw.ComboRow, _pspec) -> None:
        if self._syncing:
            return
        index = row.get_selected()
        if 0 <= index < len(self._cpu_ids):
            self.controller.configure(cpu_sensor=self._cpu_ids[index])

    def _on_gpu_source(self, row: Adw.ComboRow, _pspec) -> None:
        if self._syncing:
            return
        index = row.get_selected()
        if 0 <= index < len(self._gpu_ids):
            self.controller.configure(gpu_sensor=self._gpu_ids[index])

    def _update(self) -> None:
        c = self.controller
        fahrenheit = c.config.fahrenheit
        unit = "°F" if fahrenheit else "°C"
        cpu_value = 32 + 1.8 * c.cpu_temp if fahrenheit and c.cpu_temp else c.cpu_temp
        gpu_value = 32 + 1.8 * c.gpu_temp if fahrenheit and c.gpu_temp else c.gpu_temp
        self.cpu_card.update(
            f"{cpu_value:.1f}" if c.cpu_temp else "--",
            unit,
            f"{c.cpu_model} · {c.cpu_sensor_label}",
            [32 + 1.8 * v if fahrenheit else v for v in c.history["cpu_temp"]],
        )
        self.gpu_card.set_available(c.gpu_available)
        self.gpu_card.update(
            f"{gpu_value:.1f}" if c.gpu_available else "--",
            unit,
            c.gpu_name if c.gpu_available else "No compatible GPU found",
            [32 + 1.8 * v if fahrenheit else v for v in c.history["gpu_temp"]],
        )

        sensors = c.snapshot.system_sensors
        ids = tuple(sensor.id for sensor in sensors)
        if ids != self._system_ids:
            self._system_ids = ids
            for row in self._system_rows:
                self.system_group.remove(row)
            self._system_rows.clear()
            if not sensors:
                row = Adw.ActionRow(title="No extra sensors detected")
                self.system_group.add(row)
                self._system_rows.append(row)
            for sensor in sensors:
                row = Adw.ActionRow(title=sensor.label or sensor.chip)
                row.set_subtitle(sensor.chip)
                value = Gtk.Label(label=f"{(sensor.value or 0):.1f} °C" if sensor.value is not None else "—")
                value.add_css_class("sensor-value")
                row.add_suffix(value)
                self.system_group.add(row)
                self._system_rows.append(row)
        else:
            for row, sensor in zip(self._system_rows, sensors):
                suffix = row.get_last_child()
                if isinstance(suffix, Gtk.Label):
                    suffix.set_text(f"{sensor.value:.1f} °C" if sensor.value is not None else "—")
