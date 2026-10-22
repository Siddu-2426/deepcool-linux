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

### Keep the display and lighting running at boot

Enable **Settings → Background service**. This creates a systemd user unit that
owns both the CH-series display and the native MSI per-LED lighting animation.
The unit deliberately does **not** wait for `graphical-session.target`.

Enable lingering once so the user manager, and therefore this service, starts
during boot instead of waiting for a login:

```bash
loginctl enable-linger "$USER"
```

The udev rules assign both hidraw devices to the `wheel` group in addition to
the login-time `uaccess` ACL. That is the part that lets the boot-time service
open the display and the MSI controller before the login prompt appears. On a
system where the desktop user is not in `wheel`, either add them to that group
or use the app's **Grant access** action and log in before relying on the
pre-login service.

If the rules were installed before this change, refresh the copies in
`/etc/udev/rules.d` (they take precedence over the package copies), then
reload udev:

```bash
sudo install -m 0644 data/99-deepcool-digital.rules \
  data/99-deepcool-msi-mystic-light.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --action=add --subsystem-match=hidraw
```

The next boot starts the service from the lingering user manager, before the
login prompt. Verify with:

```bash
systemctl --user status deepcool-control
journalctl --user -u deepcool-control -f
```

When the service is enabled, closing the window hands both devices to systemd
and exits the GUI. Breathing, meteor, and the other animated MSI effects keep
running, and the panel keeps updating. While the GUI is open it acts as a
control panel: lighting changes are saved and the service applies them, so the
GUI never opens a second MSI writer.

If the service is disabled, closing the window hides the app instead of
quitting it. The display timer and the native RGB animation stay alive in the
GUI process; open the app again to show the window. Use **Quit** from the menu
to stop both when the service is disabled.

The panel and the native MSI `JARGB_V2_2` stream are driven from Linux
userspace. They cannot be active before the kernel has enumerated USB and this
service has started; on the reference machine that happens a few seconds into
boot, before the login prompt. The GPU effect is stored in the GPU firmware and
is visible as soon as the card powers on; the service also reapplies the saved
effect at startup as a safety net. The panel has no independent power state and
stays lit while the PC is powered and the USB cable is connected.

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
With **Background service** enabled, the daemon owns this stream, so the
animation continues after the window is closed. No firmware, EEPROM, fan, or
voltage commands are sent.

Native effects: `Static`, `Breathing`, `Flashing`, `Double flashing`, `Meteor`,
`Blink`, `Color pulse`, `Color wave`, `Marquee`, `Visor`, `Rainbow flashing`,
`Stack`, `Fire`, `Rainbow`, `Rainbow wave`, `Color cycle`, `Lightning`,
`Color ring`, `Planetary`, `Double meteor`, `Energy`, `Clock`, and `Off`.

The package installs the MSI hidraw permission rule
(`99-deepcool-msi-mystic-light.rules`) so the app and the boot-time service can
open `1462:7d77` without root. The rule grants persistent `wheel`-group access
for the pre-login service and adds the login-time `uaccess` ACL.

### ZOTAC RTX 4060 Ti GPU (patched OpenRGB)

The reference GPU is a ZOTAC GeForce RTX 4060 Ti 8GB Twin Edge:

| Property | Value |
|---|---|
| PCI device | `10de:2788` |
| PCI subsystem | `19da:1747` |
| RGB controller | `N702E-2001`, protocol `4A`, address `0x4A` |
| Interface | NVIDIA Resource Manager I2C, 10 kHz |

The GPU is independent from the MSI `JARGB_V2_2` cabinet chain. The stock
OpenRGB package does not detect this card. `contrib/openrgb-zotac-4a/`
contains a patch for the unmerged NVIDIA RM I2C backend ([OpenRGB MR
!3380](https://gitlab.com/CalcProgrammer1/OpenRGB/-/merge_requests/3380)) and a
Podman build script:

```bash
cd contrib/openrgb-zotac-4a
./build.sh
```

The script installs the patched binary at `~/.local/bin/openrgb` and keeps any
previous binary as a timestamped backup. `~/.local/bin` must come before
`/usr/bin` in `PATH`; verify with `command -v openrgb`. The Lighting page then
shows a separate **ZOTAC GPU** controller. The patch uses preset index `0` for
`N702E-2001`, validates the controller ID to suppress the kernel-I2C duplicate,
and does not replay a saved profile over the firmware state during detection.

The GPU stores the selected effect in its own firmware, so it keeps running
after OpenRGB or DeepCool Control exits. The background service does not own the
GPU and never leaves an OpenRGB process running. It only issues a one-shot
reapply at startup, after the NVIDIA driver is available, using a generated
OpenRGB config that disables every detector except the ZOTAC 4A detector. That
keeps the MSI detector from opening or disturbing `/dev/hidraw3`. The saved GPU
effect and color are kept in separate `gpu_lighting_*` configuration keys, so
selecting the GPU in the Lighting page never replaces the cabinet's native MSI
settings.

Other controllers are controlled through OpenRGB. The packages recommend it;
install it if you have a non-MSI controller. For the reference ZOTAC GPU, use
the patched build above instead of the distribution package:

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
