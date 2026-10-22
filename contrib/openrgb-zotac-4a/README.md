# ZOTAC RTX 4060 Ti GPU lighting

This directory contains the local OpenRGB patch and build script used to control
the RGB lighting on the reference ZOTAC GeForce RTX 4060 Ti 8GB Twin Edge.

## Reference hardware

| Property | Value |
|---|---|
| GPU | ZOTAC GeForce RTX 4060 Ti 8GB Twin Edge |
| PCI device | `10de:2788` |
| PCI subsystem | `19da:1747` |
| RGB controller | `N702E-2001` protocol `4A` |
| I2C address | `0x4A` |
| Interface | NVIDIA Resource Manager I2C, 10 kHz |

The card is **not** connected to the motherboard's JARGB chain. Changing the
MSI cabinet colour does not change the GPU, and changing the GPU does not
change the cabinet.

## Why a patched OpenRGB is needed

The stock OpenRGB package does not detect this card. OpenRGB merge request
[!3380](https://gitlab.com/CalcProgrammer1/OpenRGB/-/merge_requests/3380)
adds the NVIDIA Resource Manager I2C backend that can reach the controller at
the 10 kHz speed the Spectra MCU requires. The patch here adds what was needed
for the reference card:

- PCI IDs `10de:2788` / `19da:1747` and the matching detector registration.
- Custom preset index `0` for controller `N702E-2001` (upstream used `8`, which
  leaves the LED off in Static mode on this card).
- Rejection of empty/non-printable controller IDs, which removes the duplicate
  false detection through the fixed-100 kHz kernel NVIDIA I2C adapter.
- `CONTROLLER_FLAG_NO_PROFILE_LOAD`: detection must not replay a stale saved
  profile over the effect stored in the GPU firmware.
- Initialisation of the RGBController update flags, so the worker thread cannot
  send a default black frame before the first real update.
- A short wait in `DetectionManager::WaitForDetection`, fixing the CLI race that
  made `--list-devices` exit before detection completed.

The firmware stores the chosen effect. No background daemon is needed for the
GPU; the effect continues after DeepCool Control or OpenRGB exits.

## Build and install

```bash
cd contrib/openrgb-zotac-4a
./build.sh
```

The script builds in a rootless Podman Fedora 44 container and installs the
binary at `~/.local/bin/openrgb`. If a binary already exists there, it is kept
as `openrgb.bak.YYYYMMDDHHMMSS`.

`~/.local/bin` must come before `/usr/bin` in `PATH`. This is true for the
reference user session; check with:

```bash
command -v openrgb
# /home/<user>/.local/bin/openrgb
```

To install somewhere else:

```bash
OUT="$HOME/bin/openrgb" ./build.sh
```

The base branch is pinned to commit
`094965520d81daf0303125348039e896b07b52b3`. MR !3380 is unmerged; if it is
rebased, update `COMMIT` in `build.sh` and regenerate the patch against the new
base.

## Use

```bash
openrgb --list-devices
```

The card should appear as:

```text
0: ZOTAC GPU
  Type:           GPU
  Description:    ZOTAC 40/50 series RGB GPU Device (N702E-2001) protocol 4A
  Location:       I2C: NVIDIA RM i2c port 1 (GPU 0000:01:00.0), address 0x4A
  Modes: [Static] Breathing 'Spectrum Cycle' Flashing 'Spectrum Breathing' 'Random Flashing'
```

DeepCool Control lists the same controller as **ZOTAC GPU** on the Lighting
page. Choose a mode, colour, and zone, then **Apply**.

Examples:

```bash
# Solid red
openrgb --noautoconnect --device 0 --mode Static --color FF0000

# Purple breathing, matching the reference cabinet colour
openrgb --noautoconnect --device 0 --mode Breathing --color 613583 --speed 40
```

`--list-devices` is non-destructive with this patch; it reads the current
controller state without sending a black Static frame.

## Scope and safety

The patch only uses the ZOTAC LED I2C control/status registers already present
in the MR. It does not send firmware, EEPROM, fan, voltage, or clock commands.
The controller writes are still firmware writes, so use the same caution as any
other RGB utility: do not run it concurrently with ZOTAC FireStorm, MSI Center,
or another OpenRGB instance.

The patch applies to OpenRGB and is provided under OpenRGB's GPL-2.0-only
license.
