"""Custom-drawn widgets: hardware preview, sparklines and stat cards."""

from __future__ import annotations

import math
from collections.abc import Sequence

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

SEGMENTS = {
    "0": "ABCDEF",
    "1": "BC",
    "2": "ABGED",
    "3": "ABGCD",
    "4": "FGBC",
    "5": "AFGCD",
    "6": "AFGECD",
    "7": "ABC",
    "8": "ABCDEFG",
    "9": "ABCDFG",
}


def _rgba(value: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    color = Gdk.RGBA()
    if not color.parse(value):
        color.parse("#22d3ee")
    return (color.red, color.green, color.blue, alpha)


def _rounded_rect(cr, x: float, y: float, width: float, height: float, radius: float) -> None:
    radius = min(radius, width / 2.0, height / 2.0)
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


class SegmentedPreview(Gtk.DrawingArea):
    """A faithful, animated rendering of the CH-series front panel."""

    def __init__(self) -> None:
        super().__init__()
        self.set_content_width(540)
        self.set_content_height(300)
        self.set_hexpand(True)
        self._accent = "#22d3ee"
        self._animations = True
        self._primary_mode = "cpu_temp"
        self._secondary_mode = "gpu_temp"
        self._primary_value: float | None = 0
        self._secondary_value: float | None = 0
        self._primary_percent = 0.0
        self._secondary_percent = 0.0
        self._fahrenheit = False
        self._connected = False
        self._auto = False
        self._shown_primary = 0.0
        self._shown_secondary = 0.0
        self._target_primary = 0.0
        self._target_secondary = 0.0
        self._animating = False
        self._phase = 0.0
        self.set_draw_func(self._draw)
        self.add_tick_callback(self._tick)

    @property
    def accent(self) -> str:
        return self._accent

    def set_accent(self, color: str) -> None:
        self._accent = color
        self.queue_draw()

    def set_animations(self, enabled: bool) -> None:
        self._animations = enabled
        self.queue_draw()

    def set_state(
        self,
        *,
        primary_mode: str,
        primary_value: float | None,
        primary_percent: float,
        secondary_mode: str,
        secondary_value: float | None,
        secondary_percent: float,
        fahrenheit: bool,
        connected: bool,
        auto: bool,
    ) -> None:
        self._primary_mode = primary_mode
        self._secondary_mode = secondary_mode
        self._primary_value = primary_value
        self._secondary_value = secondary_value if secondary_mode != "off" else None
        self._fahrenheit = fahrenheit
        self._connected = connected
        self._auto = auto
        self._target_primary = 0.0 if primary_value is None else max(0.0, min(10.0, primary_percent / 10.0))
        self._target_secondary = (
            0.0
            if secondary_mode == "off" or secondary_value is None
            else max(0.0, min(10.0, secondary_percent / 10.0))
        )
        if not self._animations:
            self._shown_primary = self._target_primary
            self._shown_secondary = self._target_secondary
        self.queue_draw()

    def _tick(self, _widget: Gtk.Widget, _clock: Gdk.FrameClock) -> bool:
        changed = False
        self._phase += 0.06
        for attribute, target in (
            ("_shown_primary", self._target_primary),
            ("_shown_secondary", self._target_secondary),
        ):
            current = getattr(self, attribute)
            if abs(current - target) > 0.005:
                setattr(self, attribute, current + (target - current) * 0.22)
                changed = True
            elif current != target:
                setattr(self, attribute, target)
                changed = True
        if changed:
            self.queue_draw()
        return True

    def _draw(self, area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        scale = min(width / 540.0, height / 300.0)
        cr.save()
        cr.translate((width - 540 * scale) / 2, (height - 300 * scale) / 2)
        cr.scale(scale, scale)
        self._draw_panel(cr)
        cr.restore()

    def _draw_panel(self, cr) -> None:
        accent = _rgba(self._accent)
        # Outer case
        _rounded_rect(cr, 4, 4, 532, 292, 28)
        gradient = cairo.LinearGradient(4, 4, 532, 292)
        gradient.add_color_stop_rgba(0, 0.055, 0.07, 0.095, 1)
        gradient.add_color_stop_rgba(1, 0.024, 0.031, 0.045, 1)
        cr.set_source(gradient)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.09)
        cr.set_line_width(1.2)
        cr.stroke()

        # Soft accent glow in the corners
        glow = _rgba(self._accent, 0.12 if self._connected else 0.035)
        for cx, cy, radius in ((470, 54, 120), (72, 250, 100)):
            radial = _radial(cx, cy, radius, glow)
            cr.set_source(radial)
            cr.arc(cx, cy, radius, 0, math.tau)
            cr.fill()

        # Header row
        self._text(cr, "DEEPCOOL", 34, 29, 10.5, (1, 1, 1, 0.48), bold=True, letter_spacing=1800)
        self._text(cr, "CH360 DIGITAL", 34, 47, 9.0, (1, 1, 1, 0.26))
        status_text = "LIVE" if self._connected else "PREVIEW"
        status_color = _rgba("#34d399") if self._connected else (1, 1, 1, 0.32)
        pulse = 0.55 + 0.45 * (math.sin(self._phase) * 0.5 + 0.5) if self._connected else 1.0
        cr.set_source_rgba(status_color[0], status_color[1], status_color[2], pulse)
        cr.arc(415, 34, 4.5, 0, math.tau)
        cr.fill()
        self._text(cr, status_text, 426, 27, 9.5, (1, 1, 1, 0.55), bold=True, letter_spacing=900)

        if self._auto:
            self._pill(cr, 476, 23, 52, 21, "AUTO")

        # Two readout rows
        self._draw_readout(
            cr,
            top=62,
            label="CPU",
            value=self._primary_value,
            percent=self._shown_primary,
            mode=self._primary_mode,
            accent=accent,
        )
        # Divider
        cr.set_source_rgba(1, 1, 1, 0.07)
        cr.set_line_width(1)
        cr.move_to(34, 151)
        cr.line_to(506, 151)
        cr.stroke()
        self._draw_readout(
            cr,
            top=171,
            label="GPU",
            value=self._secondary_value,
            percent=self._shown_secondary,
            mode=self._secondary_mode,
            accent=accent,
        )

    def _draw_readout(self, cr, *, top: int, label: str, value, percent: float, mode: str, accent) -> None:
        off = mode == "off" or value is None
        dim = 0.18 if off else 0.52
        unit = "%" if mode.endswith("usage") else ("°F" if self._fahrenheit else "°C")
        title = label
        if mode.endswith("usage"):
            title = f"{label} LOAD"
        elif mode.endswith("temp"):
            title = f"{label} TEMP"

        self._text(cr, title, 34, top + 2, 11.5, (1, 1, 1, dim), bold=True, letter_spacing=500)
        if off:
            self._text(cr, "OFF", 34, top + 22, 10.0, (1, 1, 1, 0.2))

        # Digits
        text = "--" if off else f"{max(0, min(999, int(round(float(value))))) :03d}"
        digits = list(text)
        x = 250
        for character in digits:
            self._digit(cr, character, x, top, 38, 68, 8.5, accent, dim if off else 1.0)
            x += 47

        # Unit
        self._text(cr, unit, 398, top + 42, 17.0, (1, 1, 1, 0.42 if not off else 0.15), bold=True)

        # Ten-cell bar
        self._bar(cr, 34, top + 85, 460, 10, percent, accent, off)

    def _digit(self, cr, character: str, x: float, y: float, width: float, height: float, thickness: float, accent, alpha: float) -> None:
        segments = SEGMENTS.get(character)
        mid = y + height / 2
        pts = {
            "A": ((x + thickness / 2, y), (x + width - thickness / 2, y)),
            "B": ((x + width, y + thickness / 2), (x + width, mid - thickness / 2)),
            "C": ((x + width, mid + thickness / 2), (x + width, y + height - thickness / 2)),
            "D": ((x + thickness / 2, y + height), (x + width - thickness / 2, y + height)),
            "E": ((x, mid + thickness / 2), (x, y + height - thickness / 2)),
            "F": ((x, y + thickness / 2), (x, mid - thickness / 2)),
            "G": ((x + thickness / 2, mid), (x + width - thickness / 2, mid)),
        }
        cr.set_line_cap(1)  # cairo.LINE_CAP_ROUND
        for name, (start, end) in pts.items():
            on = segments is not None and name in segments
            cr.save()
            cr.set_line_width(thickness if on else thickness * 0.55)
            if on:
                cr.set_source_rgba(accent[0], accent[1], accent[2], 0.16 * alpha)
                cr.set_line_width(thickness + 7)
                cr.move_to(*start)
                cr.line_to(*end)
                cr.stroke()
                cr.set_source_rgba(0.88, 0.97, 1.0, 0.92 * alpha)
            else:
                cr.set_source_rgba(1, 1, 1, 0.035)
            cr.set_line_width(thickness if on else thickness * 0.45)
            cr.move_to(*start)
            cr.line_to(*end)
            cr.stroke()
            cr.restore()

    def _bar(self, cr, x: float, y: float, width: float, height: float, level: float, accent, off: bool) -> None:
        gap = 5.0
        cells = 10
        cell_width = (width - gap * (cells - 1)) / cells
        for index in range(cells):
            cx = x + index * (cell_width + gap)
            _rounded_rect(cr, cx, y, cell_width, height, height / 2)
            fill = 0.0
            if not off:
                fill = max(0.0, min(1.0, level - index))
            if fill > 0.01:
                cr.set_source_rgba(accent[0], accent[1], accent[2], 0.92 * fill)
            else:
                cr.set_source_rgba(1, 1, 1, 0.07)
            cr.fill()

    def _pill(self, cr, x: float, y: float, width: float, height: float, text: str) -> None:
        _rounded_rect(cr, x, y, width, height, height / 2)
        cr.set_source_rgba(*_rgba(self._accent, 0.16))
        cr.fill_preserve()
        cr.set_source_rgba(*_rgba(self._accent, 0.55))
        cr.set_line_width(1)
        cr.stroke()
        self._text(cr, text, x + 12, y + 5.5, 8.0, _rgba(self._accent), bold=True, letter_spacing=700)

    @staticmethod
    def _text(cr, text: str, x: float, y: float, size: float, color, bold: bool = False, letter_spacing: int = 0) -> None:
        layout = PangoCairo.create_layout(cr)
        description = Pango.FontDescription()
        description.set_family("Adwaita Sans")
        description.set_size(int(size * Pango.SCALE))
        if bold:
            description.set_weight(Pango.Weight.BOLD)
        layout.set_font_description(description)
        attributes = Pango.AttrList()
        if letter_spacing:
            attributes.insert(Pango.attr_letter_spacing_new(letter_spacing))
        layout.set_attributes(attributes)
        layout.set_text(text, -1)
        cr.set_source_rgba(*color)
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, layout)


def _radial(cx: float, cy: float, radius: float, color):
    pattern = cairo.RadialGradient(cx, cy, 0, cx, cy, radius)
    pattern.add_color_stop_rgba(0, color[0], color[1], color[2], color[3])
    pattern.add_color_stop_rgba(1, color[0], color[1], color[2], 0)
    return pattern


class Sparkline(Gtk.DrawingArea):
    def __init__(self, height: int = 46, max_value: float = 100.0) -> None:
        super().__init__()
        self.set_content_height(height)
        self.set_hexpand(True)
        self._values: list[float] = []
        self._color = "#22d3ee"
        self._max = max_value
        self.set_draw_func(self._draw)

    def set_color(self, color: str) -> None:
        self._color = color
        self.queue_draw()

    def set_values(self, values: Sequence[float], max_value: float | None = None) -> None:
        self._values = [float(v) for v in values][-60:]
        if max_value is not None:
            self._max = max_value
        self.queue_draw()

    def _draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        if width <= 2 or height <= 2:
            return
        color = _rgba(self._color)
        if len(self._values) < 2:
            cr.set_source_rgba(1, 1, 1, 0.06)
            cr.set_line_width(1.5)
            cr.move_to(0, height - 3)
            cr.line_to(width, height - 3)
            cr.stroke()
            return
        values = self._values
        low = min(values)
        high = max(values)
        span = max(1.0, high - low)
        # Give the line a little breathing room while keeping absolute context.
        low = max(0.0, low - span * 0.15)
        high = min(self._max, high + span * 0.15)
        if high - low < 2:
            # Keep nearly flat series visually centred instead of hugging the floor.
            middle = (high + low) / 2
            low = max(0.0, middle - 2.0)
            high = min(self._max, low + 4.0)
            if high - low < 2:
                low = max(0.0, high - 4.0)
                high = low + 4.0
        step = width / max(1, len(values) - 1)

        def point(index: int, value: float) -> tuple[float, float]:
            x = index * step
            y = height - 2 - ((value - low) / (high - low)) * (height - 6)
            return x, y

        path = []
        for index, value in enumerate(values):
            path.append(point(index, value))

        # Fill
        cr.move_to(path[0][0], height)
        for x, y in path:
            cr.line_to(x, y)
        cr.line_to(path[-1][0], height)
        cr.close_path()
        cr.set_source_rgba(color[0], color[1], color[2], 0.10)
        cr.fill()

        # Line
        cr.set_line_width(2.0)
        cr.set_line_join(1)
        cr.set_line_cap(1)
        cr.set_source_rgba(color[0], color[1], color[2], 0.9)
        for index, (x, y) in enumerate(path):
            if index == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()

        # End dot
        cr.arc(path[-1][0] - 1, path[-1][1], 2.8, 0, math.tau)
        cr.set_source_rgba(color[0], color[1], color[2], 1.0)
        cr.fill()


class StatCard(Gtk.Box):
    def __init__(self, icon: str, title: str, accent: str, max_value: float = 100.0) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("stat-card")
        self.set_hexpand(True)
        self._accent = accent
        self._max = max_value

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        image = Gtk.Image.new_from_icon_name(icon)
        image.add_css_class("stat-icon")
        image.set_pixel_size(18)
        header.append(image)
        self._title = Gtk.Label(label=title, xalign=0)
        self._title.add_css_class("stat-title")
        self._title.set_hexpand(True)
        header.append(self._title)
        self.append(header)

        value_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        value_row.set_valign(Gtk.Align.END)
        self._value = Gtk.Label(label="--")
        self._value.add_css_class("stat-value")
        self._value.set_xalign(0)
        value_row.append(self._value)
        self._unit = Gtk.Label(label="")
        self._unit.add_css_class("stat-unit")
        self._unit.set_valign(Gtk.Align.END)
        self._unit.set_margin_bottom(5)
        value_row.append(self._unit)
        self.append(value_row)

        self._subtitle = Gtk.Label(label="Waiting for sensors…", xalign=0)
        self._subtitle.add_css_class("stat-subtitle")
        self._subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        self.append(self._subtitle)

        self.sparkline = Sparkline(max_value=max_value)
        self.sparkline.set_color(accent)
        self.sparkline.set_margin_top(4)
        self.append(self.sparkline)

    def set_accent(self, accent: str) -> None:
        self._accent = accent
        self.sparkline.set_color(accent)

    def update(self, value: str, unit: str, subtitle: str, history: Sequence[float] | None = None) -> None:
        self._value.set_text(value)
        self._unit.set_text(unit)
        self._subtitle.set_text(subtitle)
        if history is not None:
            self.sparkline.set_values(history, self._max)

    def set_available(self, available: bool) -> None:
        self.set_opacity(1.0 if available else 0.55)


def section_title(title: str, subtitle: str = "") -> Gtk.Widget:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
    label = Gtk.Label(label=title, xalign=0)
    label.add_css_class("section-title")
    box.append(label)
    if subtitle:
        sub = Gtk.Label(label=subtitle, xalign=0, wrap=True)
        sub.add_css_class("section-subtitle")
        box.append(sub)
    return box


def card() -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
    box.add_css_class("card")
    return box


def pill_label(text: str, css_class: str) -> Gtk.Label:
    label = Gtk.Label(label=text)
    label.add_css_class("pill")
    label.add_css_class(css_class)
    return label
