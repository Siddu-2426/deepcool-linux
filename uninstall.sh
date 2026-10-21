#!/usr/bin/env bash
# Remove DeepCool Control. User configuration is kept unless --purge is given.
set -euo pipefail

MODE="user"
PURGE=0
REMOVE_UDEV=0

usage() {
  cat <<'EOF'
Usage: ./uninstall.sh [options]

Options:
  --user       Remove the per-user installation (default).
  --system     Remove the /usr/local installation (requires sudo).
  --udev       Also remove /etc/udev/rules.d/99-deepcool-digital.rules.
  --purge      Also remove ~/.config/deepcool-control.
  --help       Show this help.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --user) MODE="user" ;;
    --system) MODE="system" ;;
    --udev) REMOVE_UDEV=1 ;;
    --purge) PURGE=1 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage; exit 2 ;;
  esac
done

SUDO=()
if [ "$MODE" = "system" ]; then
  if [ "$(id -u)" -ne 0 ]; then
    SUDO=(sudo)
  fi
  PREFIX="/usr/local"
  REMOVE_UDEV=1
else
  PREFIX="$HOME/.local"
fi

APP_DIR="$PREFIX/lib/deepcool-control"
BIN_DIR="$PREFIX/bin"
DATA_DIR="$PREFIX/share"

systemctl --user disable --now deepcool-control.service >/dev/null 2>&1 || true
rm -f "$HOME/.config/systemd/user/deepcool-control.service"
rm -f "$HOME/.config/autostart/deepcool-control.desktop"
systemctl --user daemon-reload >/dev/null 2>&1 || true

echo "Removing application files from $PREFIX…"
"${SUDO[@]}" rm -rf "$APP_DIR"
"${SUDO[@]}" rm -f "$BIN_DIR/deepcool-control"
"${SUDO[@]}" rm -f "$DATA_DIR/applications/io.github.deepcool.Control.desktop"
"${SUDO[@]}" rm -f "$DATA_DIR/icons/hicolor/scalable/apps/io.github.deepcool.Control.svg"

if [ "$REMOVE_UDEV" -eq 1 ]; then
  if [ "$(id -u)" -eq 0 ]; then
    rm -f /etc/udev/rules.d/99-deepcool-digital.rules
    udevadm control --reload-rules || true
  elif command -v sudo >/dev/null 2>&1; then
    sudo rm -f /etc/udev/rules.d/99-deepcool-digital.rules
    sudo udevadm control --reload-rules || true
  else
    echo "Remove /etc/udev/rules.d/99-deepcool-digital.rules as root." >&2
  fi
fi

if [ "$PURGE" -eq 1 ]; then
  rm -rf "$HOME/.config/deepcool-control"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$DATA_DIR/applications" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "$DATA_DIR/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "DeepCool Control has been removed."
