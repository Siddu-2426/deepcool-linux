#!/usr/bin/env bash
# Build a noarch RPM without requiring setuptools or network access.
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
TOPDIR="$ROOT/build/rpm"
DIST="$ROOT/dist"
TARBALL="$TOPDIR/SOURCES/$NAME-$VERSION.tar.gz"

if ! command -v rpmbuild >/dev/null 2>&1; then
  echo "rpmbuild is required. On Fedora: sudo dnf install rpm-build" >&2
  exit 1
fi

rm -rf "$TOPDIR"
mkdir -p "$TOPDIR/SOURCES" "$TOPDIR/SPECS" "$TOPDIR/BUILD" "$TOPDIR/BUILDROOT" "$TOPDIR/RPMS" "$TOPDIR/SRPMS" "$DIST"

tar \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='build' \
  --exclude='dist' \
  --transform "s,^,$NAME-$VERSION/," \
  -czf "$TARBALL" \
  LICENSE README.md pyproject.toml deepcool-control install.sh uninstall.sh \
  src data tests docs packaging debian

cp "$ROOT/$NAME.spec" "$TOPDIR/SPECS/$NAME.spec"
rpmbuild -bb --define "_topdir $TOPDIR" "$TOPDIR/SPECS/$NAME.spec"

find "$TOPDIR/RPMS" -type f -name '*.rpm' -exec cp -v {} "$DIST/" \;
echo
echo "RPM written to $DIST"
ls -lh "$DIST"/*.rpm
