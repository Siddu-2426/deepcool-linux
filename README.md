# DeepCool Control

<img src="data/icons/hicolor/scalable/apps/io.github.deepcool.Control.svg" width="96" align="right" alt="DeepCool Control icon">

Native GTK4/libadwaita application for DeepCool CH-series digital case
displays. It reads CPU and GPU sensors locally and drives the two three-digit
readouts and ten-cell load bars over USB HID.

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

Only these product IDs are accessed. RGB lighting is not controlled.

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
permission rule. Reconnect the display after installing.

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
