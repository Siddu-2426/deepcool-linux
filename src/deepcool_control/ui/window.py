"""Main application window."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk, Pango  # noqa: E402

from .. import lighting, system  # noqa: E402
from ..config import APP_NAME, VERSION  # noqa: E402
from ..controller import Controller  # noqa: E402
from .dashboard import DashboardPage  # noqa: E402
from .display_page import DisplayPage  # noqa: E402
from .lighting_page import LightingPage  # noqa: E402
from .sensors_page import SensorsPage  # noqa: E402
from .settings_page import SettingsPage  # noqa: E402

PAGES = (
    ("dashboard", "Overview", "view-grid-symbolic"),
    ("display", "Display", "video-display-symbolic"),
    ("lighting", "Lighting", "preferences-color-symbolic"),
    ("sensors", "Sensors", "applications-utilities-symbolic"),
    ("settings", "Settings", "emblem-system-symbolic"),
)

ACCENT_CSS = """
@define-color accent_color {color};
@define-color accent_soft {soft};
@define-color accent_glow {glow};
@define-color accent_faint {faint};
"""


class MainWindow(Adw.ApplicationWindow):
    """Adw window with a compact sidebar and a stack of configuration pages."""

    def __init__(self, application: Gtk.Application, controller: Controller) -> None:
        super().__init__(application=application)
        self.controller = controller
        self._closed = False
        self._background_notified = False
        self._nav_rows: dict[str, Gtk.ListBoxRow] = {}
        self._accent_provider = Gtk.CssProvider()
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(display, self._accent_provider, 900)

        self.set_title(APP_NAME)
        self.set_default_size(1220, 820)
        self.set_size_request(900, 620)
        self.add_css_class("deepcool-window")

        self._build_actions()

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(self._build_header())
        toolbar.set_content(self._build_body())

        self._toasts = Adw.ToastOverlay()
        self._toasts.set_child(toolbar)
        self.set_content(self._toasts)

        self._apply_accent()
        self._update_status()
        self.show_page("dashboard", animate=False)

        controller.connect("state-changed", lambda _c: self._update_status())
        controller.connect("config-changed", lambda _c: self._apply_accent())
        controller.connect("toast", self._on_toast)
        self.connect("close-request", self._on_close)

    # ------------------------------------------------------------------ shell
    def _build_header(self) -> Adw.HeaderBar:
        header = Adw.HeaderBar()
        header.add_css_class("app-header")

        self._window_title = Adw.WindowTitle(
            title=APP_NAME,
            subtitle="Display and case lighting",
        )
        header.set_title_widget(self._window_title)

        self._header_status = Gtk.Label(label="Preview")
        self._header_status.add_css_class("status-pill")
        self._header_status.add_css_class("compact")
        self._header_status.add_css_class("disconnected")
        self._header_status.set_tooltip_text("Display connection status")
        header.pack_end(self._header_status)

        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh.set_tooltip_text("Send the current readings now (Ctrl+R)")
        refresh.add_css_class("flat")
        refresh.connect("clicked", lambda _b: self._send_now())
        header.pack_end(refresh)

        menu = Gio.Menu()
        menu.append("Send reading now", "win.send-now")
        menu.append("Lighting controls", "win.show-lighting")
        menu.append("Grant device access", "win.grant-access")
        menu.append("About DeepCool Control", "app.about")
        menu.append("Quit", "app.quit")
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_menu_model(menu)
        menu_button.set_tooltip_text("Main menu")
        menu_button.add_css_class("flat")
        header.pack_end(menu_button)
        return header

    def _build_body(self) -> Gtk.Widget:
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.set_hexpand(True)
        body.set_vexpand(True)

        self._banner = Adw.Banner(
            title="Allow access to the display to send readings",
            button_label="Grant access",
        )
        self._banner.set_revealed(False)
        self._banner.connect("button-clicked", lambda _b: self.controller.install_permissions())
        body.append(self._banner)

        columns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        columns.set_hexpand(True)
        columns.set_vexpand(True)
        columns.append(self._build_sidebar())
        columns.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        columns.append(self._build_stack())
        body.append(columns)
        return body

    def _build_sidebar(self) -> Gtk.Widget:
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar.add_css_class("sidebar")
        sidebar.set_size_request(238, -1)

        section = Gtk.Label(label="CONTROL", xalign=0)
        section.add_css_class("eyebrow")
        section.set_margin_top(22)
        section.set_margin_bottom(8)
        section.set_margin_start(24)
        section.set_margin_end(18)
        sidebar.append(section)

        self._nav = Gtk.ListBox()
        self._nav.add_css_class("nav-list")
        self._nav.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._nav.set_activate_on_single_click(True)
        self._nav.connect("row-activated", self._on_nav_activated)
        for name, title, icon in PAGES:
            row = Gtk.ListBoxRow()
            row.add_css_class("nav-row")
            row.set_name(name)
            row.set_tooltip_text(title)
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=13)
            content.set_margin_top(9)
            content.set_margin_bottom(9)
            content.set_margin_start(13)
            content.set_margin_end(13)
            image = Gtk.Image.new_from_icon_name(icon)
            image.set_pixel_size(18)
            image.add_css_class("nav-icon")
            content.append(image)
            label = Gtk.Label(label=title, xalign=0)
            label.add_css_class("nav-label")
            label.set_hexpand(True)
            content.append(label)
            row.set_child(content)
            self._nav.append(row)
            self._nav_rows[name] = row
        sidebar.append(self._nav)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        sidebar.append(spacer)

        device = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        device.add_css_class("device-mini")
        device.set_margin_start(14)
        device.set_margin_end(14)
        device.set_margin_bottom(12)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._mini_dot = Gtk.Box()
        self._mini_dot.add_css_class("status-dot")
        self._mini_dot.add_css_class("disconnected")
        self._mini_dot.set_size_request(8, 8)
        self._mini_dot.set_valign(Gtk.Align.CENTER)
        top.append(self._mini_dot)
        device_label = Gtk.Label(label="DEVICE", xalign=0)
        device_label.add_css_class("eyebrow")
        top.append(device_label)
        device.append(top)

        self._mini_name = Gtk.Label(label="No display found", xalign=0)
        self._mini_name.add_css_class("mini-name")
        self._mini_name.set_ellipsize(Pango.EllipsizeMode.END)
        device.append(self._mini_name)

        self._mini_meta = Gtk.Label(label="Connect over USB", xalign=0)
        self._mini_meta.add_css_class("mini-meta")
        self._mini_meta.set_ellipsize(Pango.EllipsizeMode.END)
        device.append(self._mini_meta)

        self._mini_action = Gtk.Button(label="Manage")
        self._mini_action.add_css_class("flat")
        self._mini_action.add_css_class("mini-action")
        self._mini_action.set_halign(Gtk.Align.START)
        self._mini_action.connect("clicked", self._on_mini_action)
        device.append(self._mini_action)
        sidebar.append(device)

        version = Gtk.Label(label=f"Version {VERSION}", xalign=0)
        version.add_css_class("sidebar-version")
        version.set_margin_start(24)
        version.set_margin_bottom(16)
        sidebar.append(version)
        return sidebar

    def _build_stack(self) -> Gtk.Widget:
        self._stack = Gtk.Stack()
        self._stack.set_hexpand(True)
        self._stack.set_vexpand(True)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(160)
        self._dashboard = DashboardPage(self.controller, self)
        self._stack.add_named(self._dashboard, "dashboard")
        self._stack.add_named(DisplayPage(self.controller, self), "display")
        self._stack.add_named(LightingPage(self.controller, self), "lighting")
        self._stack.add_named(SensorsPage(self.controller, self), "sensors")
        self._stack.add_named(SettingsPage(self.controller, self), "settings")
        self._stack.connect("notify::visible-child-name", self._on_page_changed)
        self._install_breakpoints()
        return self._stack

    def _install_breakpoints(self) -> None:
        """Stack the dashboard hero and metrics on smaller desktop windows."""

        condition = Adw.BreakpointCondition.parse("max-width: 1180px")
        if condition is None:
            return
        breakpoint = Adw.Breakpoint.new(condition)
        breakpoint.add_setter(self._dashboard.hero, "orientation", Gtk.Orientation.VERTICAL)
        breakpoint.add_setter(self._dashboard.hero, "spacing", 18)
        breakpoint.add_setter(self._dashboard.hero_side, "width-request", -1)
        breakpoint.add_setter(self._dashboard.hero_side, "valign", Gtk.Align.START)
        breakpoint.add_setter(self._dashboard.metrics_flow, "min-children-per-line", 2)
        breakpoint.add_setter(self._dashboard.metrics_flow, "max-children-per-line", 2)
        self.add_breakpoint(breakpoint)

    # ------------------------------------------------------------------ nav
    def show_page(self, name: str, animate: bool = True) -> None:
        if name not in self._nav_rows:
            return
        if not animate:
            previous = self._stack.get_transition_type()
            self._stack.set_transition_type(Gtk.StackTransitionType.NONE)
            self._stack.set_visible_child_name(name)
            self._stack.set_transition_type(previous)
        else:
            self._stack.set_visible_child_name(name)
        self._nav.select_row(self._nav_rows[name])
        self._banner.set_revealed(self.controller.permission_required)

    def _on_nav_activated(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        name = row.get_name()
        if name:
            self.show_page(name)

    def _on_page_changed(self, _stack: Gtk.Stack, _pspec) -> None:
        name = self._stack.get_visible_child_name()
        if not name:
            return
        row = self._nav_rows.get(name)
        if row is not None and self._nav.get_selected_row() is not row:
            self._nav.select_row(row)

    # -------------------------------------------------------------- actions
    def _build_actions(self) -> None:
        actions = {
            "show-overview": lambda: self.show_page("dashboard"),
            "show-display": lambda: self.show_page("display"),
            "show-lighting": lambda: self.show_page("lighting"),
            "show-sensors": lambda: self.show_page("sensors"),
            "show-settings": lambda: self.show_page("settings"),
            "send-now": self._send_now,
            "grant-access": self.controller.install_permissions,
            "close-window": self.close,
        }
        for name, callback in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _action, _param, fn=callback: fn())
            self.add_action(action)

        app = self.get_application()
        if app is not None:
            app.set_accels_for_action("win.show-overview", ["<Control>1"])
            app.set_accels_for_action("win.show-display", ["<Control>2"])
            app.set_accels_for_action("win.show-sensors", ["<Control>3"])
            app.set_accels_for_action("win.show-settings", ["<Control>4", "<Control>comma"])
            app.set_accels_for_action("win.show-lighting", ["<Control>5"])
            app.set_accels_for_action("win.send-now", ["<Control>r"])
            app.set_accels_for_action("win.close-window", ["<Control>w"])
            app.set_accels_for_action("app.quit", ["<Control>q"])

    def _send_now(self) -> None:
        self.controller.send_now()
        if self.controller.writable or self.controller.demo:
            message = "Current readings sent to the display"
        elif self.controller.permission_required:
            message = "Grant access to the display before sending readings"
        elif self.controller.service_owner:
            message = "Take over from the background service before sending readings"
        elif self.controller.connected:
            message = "The display is not writable"
        else:
            message = "No display is connected"
        toast = Adw.Toast.new(message)
        toast.set_timeout(2.5)
        self._toasts.add_toast(toast)

    # ----------------------------------------------------------------- state
    def _apply_accent(self) -> None:
        color = self.controller.config.accent_color
        soft = self.controller.config.accent_soft
        try:
            rgba = Gdk.RGBA()
            rgba.parse(color)
            base = f"rgba({round(rgba.red * 255)}, {round(rgba.green * 255)}, {round(rgba.blue * 255)}, "
        except Exception:
            base = "rgba(34, 211, 238, "
        css = ACCENT_CSS.format(
            color=color,
            soft=soft,
            glow=base + "0.38)",
            faint=base + "0.10)",
        )
        self._accent_provider.load_from_data(css.encode("utf-8"))

    def _update_status(self) -> None:
        c = self.controller
        connected = c.connected
        writable = c.writable

        if connected and writable:
            text, state = "Live", "connected"
        elif connected and c.permission_required:
            text, state = "Permission", "busy"
        elif connected and c.service_owner:
            text, state = "Service", "busy"
        elif connected:
            text, state = "Read-only", "busy"
        else:
            text, state = "Preview", "disconnected"

        for widget in (self._header_status, self._mini_dot):
            widget.remove_css_class("connected")
            widget.remove_css_class("disconnected")
            widget.remove_css_class("busy")
            widget.add_css_class(state)

        self._header_status.set_text(text)
        self._window_title.set_subtitle(
            c.device_label if connected else "CH-series display control"
        )
        if connected:
            self._mini_name.set_text(c.device_label)
            if c.permission_required:
                meta = "Permission needed"
            elif c.service_owner:
                meta = "Background service active"
            elif c.device_serial:
                meta = f"SN {c.device_serial}"
            else:
                meta = "USB HID display"
            self._mini_meta.set_text(meta)
        else:
            self._mini_name.set_text(c.unsupported_label or "No display found")
            self._mini_meta.set_text(
                "Supported model not detected"
                if c.unsupported_label
                else "Connect a CH-series display"
            )

        if c.permission_required:
            self._mini_action.set_label("Grant access")
        elif c.service_owner:
            self._mini_action.set_label("Take over")
        else:
            self._mini_action.set_label("Manage")
        self._mini_action.set_visible(
            connected or bool(c.unsupported_label)
        )
        self._banner.set_revealed(bool(c.permission_required))

    def _on_mini_action(self, _button: Gtk.Button) -> None:
        if self.controller.permission_required:
            self.controller.install_permissions()
        elif self.controller.service_owner:
            self.controller.take_over()
        else:
            self.show_page("settings")

    def _on_toast(self, _controller: Controller, message: str, kind: str) -> None:
        toast = Adw.Toast.new(message)
        toast.set_timeout(4 if kind == "error" else 3)
        toast.set_priority(Adw.ToastPriority.HIGH if kind == "error" else Adw.ToastPriority.NORMAL)
        self._toasts.add_toast(toast)

    # ----------------------------------------------------------------- about
    def show_about(self) -> None:
        dialog = Adw.AboutDialog()
        dialog.set_application_name(APP_NAME)
        dialog.set_application_icon("io.github.deepcool.Control")
        dialog.set_developer_name("DeepCool Control contributors")
        dialog.set_version(VERSION)
        dialog.set_comments(
            "A native GTK4 companion for DeepCool CH-series digital displays. "
            "Reads processor and graphics sensors locally and mirrors them to the "
            "case display over USB HID. Case ARGB can be controlled through "
            "OpenRGB. Independent educational project, not affiliated with DeepCool."
        )
        dialog.set_license_type(Gtk.License.MIT_X11)
        dialog.set_copyright("© 2026 DeepCool Control contributors")
        dialog.set_developers(["DeepCool Control contributors"])
        dialog.set_debug_info(
            f"Device: {self.controller.device_label}\n"
            f"Serial: {self.controller.device_serial or '-'}\n"
            f"Connected: {self.controller.connected}\n"
            f"Writable: {self.controller.writable}\n"
            f"OpenRGB: {lighting.find_binary() or 'not found'}\n"
            f"CPU: {self.controller.cpu_model}\n"
            f"GPU: {self.controller.gpu_name}"
        )
        dialog.present(self)

    # ----------------------------------------------------------------- close
    def _on_close(self, _window: Gtk.Window) -> bool:
        if self._closed:
            return False

        # With the background service enabled, hand both the display and the
        # native MSI lighting over to systemd and let the window close.  The
        # service is started before we release the devices, so it retries if
        # it loses the race and then picks them up as the GUI shuts down.
        if self.controller.config.service:
            ok, message = system.set_service(True)
            if ok:
                self._closed = True
                return False
            self.controller.emit(
                "toast",
                f"Could not start the background service: {message}",
                "error",
            )

        # Without the service, keep this process alive.  Hiding the window
        # leaves the display timer and the native RGB animation thread
        # running; activating the app again only needs to present the window.
        self.set_visible(False)
        if not self._background_notified:
            self._background_notified = True
            app = self.get_application()
            if app is not None:
                notification = Gio.Notification.new(
                    "DeepCool Control is still running"
                )
                notification.set_body(
                    "Display updates and cabinet lighting continue in the "
                    "background. Use Quit from the app menu to stop them."
                )
                notification.set_default_action("app.show-window")
                app.send_notification("background", notification)
        return True
