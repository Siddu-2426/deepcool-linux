#!/usr/bin/env bash
# Install DeepCool Control for the current user or system-wide.
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
MODE="user"
INSTALL_UDEV=0

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Options:
  --user       Install for the current user (default).
  --system     Install under /usr/local with sudo.
  --udev       Install the hidraw permission rule (asks for administrator access).
  --help       Show this help.

The app can also install the permission rule from Settings → Grant access.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --user) MODE="user" ;;
    --system) MODE="system" ;;
    --udev) INSTALL_UDEV=1 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage; exit 2 ;;
  esac
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required." >&2
  exit 1
fi

if ! python3 - <<'PY' >/dev/null 2>&1
import gi
import psutil
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
PY
then
  echo "Missing runtime dependencies." >&2
  echo "On Fedora run: sudo dnf install python3-gobject gtk4 libadwaita python3-psutil" >&2
  exit 1
fi

SUDO=()
if [ "$MODE" = "system" ]; then
  if [ "$(id -u)" -ne 0 ]; then
    if ! command -v sudo >/dev/null 2>&1; then
      echo "--system requires root or sudo." >&2
      exit 1
    fi
    SUDO=(sudo)
  fi
  PREFIX="/usr/local"
  APP_DIR="$PREFIX/lib/deepcool-control"
  BIN_DIR="$PREFIX/bin"
  DATA_DIR="$PREFIX/share"
  INSTALL_UDEV=1
else
  PREFIX="$HOME/.local"
  APP_DIR="$PREFIX/lib/deepcool-control"
  BIN_DIR="$PREFIX/bin"
  DATA_DIR="$PREFIX/share"
fi

TMPDIR_BUILD=$(mktemp -d)
trap 'rm -rf "$TMPDIR_BUILD"' EXIT

cat > "$TMPDIR_BUILD/deepcool-control" <<EOF
#!/bin/sh
set -eu
export PYTHONPATH='$APP_DIR'\${PYTHONPATH:+:\$PYTHONPATH}
exec python3 -m deepcool_control "\$@"
EOF
chmod 0755 "$TMPDIR_BUILD/deepcool-control"

sed "s|^Exec=.*|Exec=\"$BIN_DIR/deepcool-control\"|" \
  "$ROOT/data/io.github.deepcool.Control.desktop" \
  > "$TMPDIR_BUILD/io.github.deepcool.Control.desktop"

echo "Installing application files in $PREFIX…"
"${SUDO[@]}" install -d "$APP_DIR" "$BIN_DIR" \
  "$DATA_DIR/applications" \
  "$DATA_DIR/icons/hicolor/scalable/apps"

"${SUDO[@]}" rm -rf "$APP_DIR/deepcool_control"
"${SUDO[@]}" cp -a "$ROOT/src/deepcool_control" "$APP_DIR/deepcool_control"
"${SUDO[@]}" find "$APP_DIR/deepcool_control" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
"${SUDO[@]}" install -m 0755 "$TMPDIR_BUILD/deepcool-control" "$BIN_DIR/deepcool-control"
"${SUDO[@]}" install -m 0644 "$TMPDIR_BUILD/io.github.deepcool.Control.desktop" \
  "$DATA_DIR/applications/io.github.deepcool.Control.desktop"
"${SUDO[@]}" install -m 0644 \
  "$ROOT/data/icons/hicolor/scalable/apps/io.github.deepcool.Control.svg" \
  "$DATA_DIR/icons/hicolor/scalable/apps/io.github.deepcool.Control.svg"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$DATA_DIR/applications" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "$DATA_DIR/icons/hicolor" >/dev/null 2>&1 || true
fi

if [ "$INSTALL_UDEV" -eq 1 ]; then
  RULE_SRC="$ROOT/data/99-deepcool-digital.rules"
  RULE_DST="/etc/udev/rules.d/99-deepcool-digital.rules"
  echo "Installing the device permission rule…"
  if [ "$(id -u)" -eq 0 ]; then
    install -m 0644 "$RULE_SRC" "$RULE_DST"
    udevadm control --reload-rules
    udevadm trigger --action=add --subsystem-match=hidraw
  elif command -v sudo >/dev/null 2>&1; then
    sudo sh -c "install -m 0644 '$RULE_SRC' '$RULE_DST' && udevadm control --reload-rules && udevadm trigger --action=add --subsystem-match=hidraw"
  elif command -v pkexec >/dev/null 2>&1; then
    pkexec sh -c "install -m 0644 '$RULE_SRC' '$RULE_DST' && udevadm control --reload-rules && udevadm trigger --action=add --subsystem-match=hidraw"
  else
    echo "Could not obtain administrator access to install the udev rule." >&2
  fi
fi

echo
echo "DeepCool Control is installed."
echo "  Launch: $BIN_DIR/deepcool-control"
echo "  Diagnose: $BIN_DIR/deepcool-control --doctor"
if ! command -v openrgb >/dev/null 2>&1; then
  echo "  Note: OpenRGB was not found. Case lighting stays disabled until it is installed."
fi
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "  Note: add $BIN_DIR to PATH to launch it by name." ;;
esac
if [ "$INSTALL_UDEV" -eq 0 ]; then
  echo
  if [ -e /etc/udev/rules.d/99-deepcool-digital.rules ] || \
     [ -e /usr/lib/udev/rules.d/99-deepcool-digital.rules ]; then
    echo "The display permission rule is already installed."
    echo "Run '$ROOT/install.sh --udev' to refresh it, or use Settings → Grant access."
  else
    echo "Display permission has not been installed yet."
    echo "Either open Settings → Grant access in the app, or run:"
    echo "  $ROOT/install.sh --udev"
  fi
fi
