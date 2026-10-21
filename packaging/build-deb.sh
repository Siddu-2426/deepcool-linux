#!/usr/bin/env bash
# Build an architecture-independent .deb on any Linux host.
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

NAME=deepcool-control
VERSION=$(python3 - <<'PY'
import pathlib, tomllib
data = tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))
print(data["project"]["version"])
PY
)
DIST="$ROOT/dist"
BUILD="$ROOT/build/deb"
STAGE="$BUILD/$NAME"
OUTPUT="$DIST/${NAME}_${VERSION}_all.deb"

rm -rf "$BUILD"
mkdir -p \
  "$STAGE/DEBIAN" \
  "$STAGE/usr/bin" \
  "$STAGE/usr/lib/deepcool-control" \
  "$STAGE/usr/share/applications" \
  "$STAGE/usr/share/icons/hicolor/scalable/apps" \
  "$STAGE/usr/lib/udev/rules.d" \
  "$STAGE/usr/share/doc/$NAME" \
  "$DIST"

cp -a src/deepcool_control "$STAGE/usr/lib/deepcool-control/deepcool_control"
find "$STAGE/usr/lib/deepcool-control/deepcool_control" -type d -name __pycache__ -prune -exec rm -rf {} +

cat > "$STAGE/usr/bin/deepcool-control" <<'EOF'
#!/bin/sh
set -eu
export PYTHONPATH="/usr/lib/deepcool-control${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m deepcool_control "$@"
EOF
chmod 0755 "$STAGE/usr/bin/deepcool-control"

install -m 0644 data/io.github.deepcool.Control.desktop \
  "$STAGE/usr/share/applications/io.github.deepcool.Control.desktop"
install -m 0644 data/icons/hicolor/scalable/apps/io.github.deepcool.Control.svg \
  "$STAGE/usr/share/icons/hicolor/scalable/apps/io.github.deepcool.Control.svg"
install -m 0644 data/99-deepcool-digital.rules \
  "$STAGE/usr/lib/udev/rules.d/99-deepcool-digital.rules"
install -m 0644 LICENSE "$STAGE/usr/share/doc/$NAME/copyright"
install -m 0644 README.md "$STAGE/usr/share/doc/$NAME/README.md"

cat > "$STAGE/DEBIAN/control" <<EOF
Package: $NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Maintainer: DeepCool Linux contributors <noreply@example.com>
Depends: python3, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, python3-psutil
Suggests: nvidia-driver
Installed-Size: $(du -sk "$STAGE" | cut -f1)
Description: native control app for DeepCool CH-series digital displays
 A GTK4/libadwaita application that reads local CPU and GPU sensors and
 drives the two three-digit readouts and ten-cell load bars on DeepCool
 CH-series USB displays.
 .
 This is an independent educational project and is not affiliated with
 DeepCool.
EOF

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e

if command -v udevadm >/dev/null 2>&1; then
  udevadm control --reload-rules || true
  udevadm trigger --action=add --subsystem-match=hidraw || true
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true
fi

exit 0
EOF

cat > "$STAGE/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e

if command -v udevadm >/dev/null 2>&1; then
  udevadm control --reload-rules || true
  udevadm trigger --action=add --subsystem-match=hidraw || true
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications || true
fi

exit 0
EOF
chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

(
  cd "$STAGE"
  find usr -type f -print0 | sort -z | xargs -0 md5sum > DEBIAN/md5sums
)

if command -v dpkg-deb >/dev/null 2>&1; then
  dpkg-deb --root-owner-group --build "$STAGE" "$OUTPUT"
else
  printf '2.0\n' > "$BUILD/debian-binary"
  tar -C "$STAGE/DEBIAN" --owner=0 --group=0 --numeric-owner \
    -czf "$BUILD/control.tar.gz" .
  tar -C "$STAGE" --exclude='./DEBIAN' --owner=0 --group=0 --numeric-owner \
    -czf "$BUILD/data.tar.gz" .
  (
    cd "$BUILD"
    ar rcs "$OUTPUT" debian-binary control.tar.gz data.tar.gz
  )
fi

echo
echo "DEB written to $OUTPUT"
ls -lh "$OUTPUT"
