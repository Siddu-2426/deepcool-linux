# DeepCool Control

<img src="data/icons/hicolor/scalable/apps/io.github.deepcool.Control.svg" width="96" align="right" alt="DeepCool Control icon">

Native GTK4/libadwaita application for DeepCool CH-series digital case
displays. It reads CPU and GPU sensors locally and drives the two three-digit
readouts and ten-cell load bars over USB HID. Case ARGB can be controlled from
the Lighting page. MSI Mystic Light boards use a native HID backend; other
controllers use OpenRGB.

![Overview](docs/screenshots/overview.png)

> **Independent project.** DeepCool Control is not affiliated with, endorsed by,
> or supported by DeepCool. DeepCool and its product names are trademarks of
> their respective owners. Use this software at your own risk.

## Supported devices

| Device | USB ID | Status |
|---|---|---|
| CH360 DIGITAL | `3633:0015` | Supported; used as the reference device |
| CH560 DIGITAL | `3633:0005` | Protocol-compatible; not hardware-verified |
| MORPHEUS | `3633:0007` | Protocol-compatible; not hardware-verified |

Only these display product IDs are accessed. The display itself does not expose
RGB; case lighting is controlled separately from the Lighting page. MSI Mystic
Light motherboards (USB `1462:7d77`) are handled by the native HID backend, so
they do not need OpenRGB.

## Install

Download the `.rpm` or `.deb` from the latest release.

### Fedora and RHEL

```bash
sudo dnf install ./deepcool-control-*.rpm
```

The RPM is `noarch`, built on Fedora 44, and has no distribution suffix in its
filename.

### Debian and Ubuntu

```bash
sudo apt install ./deepcool-control_*.deb
```

The package installs the application, desktop entry, icon, and hidraw
permission rules for the display and for MSI Mystic Light controllers.
Reconnect the display (or run `udevadm trigger`) after installing.

## Run

```bash
deepcool-control
```

Both readouts can independently cycle between temperature and usage. Use the
Display and Sensors pages to choose sources, units, refresh interval, and
auto-cycle timing.

### Keep the display running

Enable **Settings → Background service**. This creates a systemd user unit that
keeps the panel updated after the window is closed.

```bash
systemctl --user status deepcool-control
journalctl --user -u deepcool-control -f
```

To keep the service running after logout:

```bash
loginctl enable-linger "$USER"
```

The panel has no independent power state. It stays lit while the PC is powered
and the USB cable is connected.

## Case lighting

The **Lighting** page controls case and motherboard ARGB. This is a separate
control path from the DeepCool display: the display's USB protocol only drives
the numeric panel.

### MSI Mystic Light (native)

The native MSI backend was reverse-engineered and verified on this board:

| Motherboard | USB ID | Cabinet ARGB header | Lighting page zone | Status |
|---|---|---|---|---|
| MSI PRO B650M-A WIFI (MS-7D77) | `1462:7d77` | `JARGB_V2_2` | `JRAINBOW2` | Supported; reference board |

The cabinet fans are wired to **`JARGB_V2_2`**, exposed as **`JRAINBOW2`** in
the Lighting page. `JARGB_V2_1` is exposed as `JRAINBOW1` but is unused on the
reference system. Each JARGB header exposes 40 addressable LEDs in the native
240-pixel frame.

On this board the controller accepts the documented zone/effect packet
(`0x52`), but its firmware effect engine does **not** drive the `JARGB_V2_2`
fans. The native backend therefore switches the controller to direct mode and
streams the per-LED frame (`0x53`). Static writes one frame and releases the
HID device; animated effects render on the host at 30 fps and keep it open.
No firmware, EEPROM, fan, or voltage commands are sent.

Native effects: `Static`, `Breathing`, `Flashing`, `Double flashing`, `Meteor`,
`Blink`, `Color pulse`, `Color wave`, `Marquee`, `Visor`, `Rainbow flashing`,
`Stack`, `Fire`, `Rainbow`, `Rainbow wave`, `Color cycle`, `Lightning`,
`Color ring`, `Planetary`, `Double meteor`, `Energy`, `Clock`, and `Off`.

The package installs the MSI hidraw permission rule
(`99-deepcool-msi-mystic-light.rules`) so the app can open `1462:7d77` without
root.

Other controllers are controlled through OpenRGB. The packages recommend it;
install it if you have a non-MSI controller:

```bash
sudo dnf install openrgb
sudo apt install openrgb
```

Choose the controller and zone, pick a color, and press **Apply**. Only one RGB
writer may use a controller at a time; close MSI Center, OpenRGB effects, and
other RGB tools before applying. If OpenRGB cannot see a non-MSI controller,
sign out and back in so its udev rule is applied.

### Lighting safety

Safe mode is enabled by default. It allows only **Direct** mode, one ARGB zone,
and at most **50%** brightness. **Preview** shows the exact native or OpenRGB
command, and every apply is logged to
`~/.local/state/deepcool-control/lighting.log` before it runs.

The native MSI backend writes only the documented LED reports (`0x52` and
`0x53`); it does not send firmware, EEPROM, fan, or voltage commands. OpenRGB
MSI firmware effect modes have a history of hanging or bricking RGB
controllers, and one all-zone `Meteor` write at 100% caused a hard shutdown on
the reference machine. Turning safe mode off is possible, but effects,
all-zone writes, and brightness above 50% require a confirmation dialog when
using OpenRGB. Do not use `Meteor` on all zones at full brightness.

If the machine shuts down after a lighting change, do not press **Apply** again
until the ARGB wiring and power supply have been checked. The log shows the
last command that was sent.

## Configuration

Settings are stored in `~/.config/deepcool-control/config.json` and can be
changed from the application.

## Notes

- Close the vendor application before running DeepCool Control. Only one process
  can safely drive the display.
- If the display is not detected, reconnect it after installation and check
  **Settings → Diagnostics**.
- NVIDIA GPU readings require `nvidia-smi`.

## License

MIT — see [LICENSE](LICENSE).
