#!/usr/bin/env bash
#
# Build the patched OpenRGB binary used for the ZOTAC RTX 4060 Ti 8GB
# Twin Edge (PCI 10de:2788, subsystem 19da:1747, controller N702E-2001).
#
# The base is the unmerged OpenRGB merge request !3380 branch, which adds
# the NVIDIA Resource Manager I2C backend needed for the card's 10 kHz
# Spectra controller.  The patch in this directory adds the card IDs and the
# fixes verified on the reference machine.
#
# Requirements: git, podman.  The build runs in a Fedora 44 container, so no
# OpenRGB build dependencies are installed on the host.
#
# Usage:
#   ./build.sh
#   OUT="$HOME/bin/openrgb" ./build.sh
#
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATCH="$HERE/openrgb-zotac-4a.patch"
CACHE="${OPENRGB_ZOTAC_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/openrgb-zotac-4a}"
OUT="${OUT:-$HOME/.local/bin/openrgb}"
IMAGE="${OPENRGB_ZOTAC_IMAGE:-localhost/openrgb-zotac-builder}"

BRANCH="linux-nvrm-i2c-backend"
COMMIT="094965520d81daf0303125348039e896b07b52b3"
REPO="https://gitlab.com/Doodcom/OpenRGB.git"

for tool in git podman; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "error: $tool is required" >&2
        exit 1
    fi
done

if [[ ! -f "$PATCH" ]]; then
    echo "error: patch not found: $PATCH" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Source tree
# ---------------------------------------------------------------------------
if [[ ! -d "$CACHE/.git" ]]; then
    echo "Cloning OpenRGB ($BRANCH)..."
    git clone --branch "$BRANCH" --single-branch "$REPO" "$CACHE"
fi

echo "Checking out $COMMIT..."
git -C "$CACHE" fetch --all --tags
git -C "$CACHE" checkout --force "$COMMIT"
git -C "$CACHE" reset --hard "$COMMIT"
git -C "$CACHE" clean -fdx

echo "Applying ZOTAC 4A patch..."
git -C "$CACHE" apply --check "$PATCH"
git -C "$CACHE" apply "$PATCH"

# ---------------------------------------------------------------------------
# Builder image (cached)
# ---------------------------------------------------------------------------
if ! podman image exists "$IMAGE"; then
    echo "Creating builder image $IMAGE..."
    podman build -t "$IMAGE" -f - "$HERE" <<'EOF'
FROM fedora:44
RUN dnf -y --setopt=install_weak_deps=False install \
        gcc-c++ \
        make \
        git \
        qt6-qtbase-devel \
        qt6-qttools-devel \
        libusb1-devel \
        hidapi-devel \
        mbedtls-devel \
        pkgconf-pkg-config \
    && dnf clean all
EOF
else
    echo "Using cached builder image $IMAGE"
fi

# ---------------------------------------------------------------------------
# Build and install
# ---------------------------------------------------------------------------
echo "Building OpenRGB..."
podman run --rm --userns=keep-id \
    -v "$CACHE:/build:Z" -w /build "$IMAGE" \
    bash -lc 'qmake6 OpenRGB.pro && make -j"$(nproc)"'

if [[ ! -x "$CACHE/openrgb" ]]; then
    echo "error: build did not produce $CACHE/openrgb" >&2
    exit 1
fi

mkdir -p "$(dirname "$OUT")"
if [[ -e "$OUT" ]]; then
    backup="$OUT.bak.$(date +%Y%m%d%H%M%S)"
    echo "Backing up existing binary to $backup"
    cp -a "$OUT" "$backup"
fi
install -m 755 "$CACHE/openrgb" "$OUT"

echo
echo "Installed $OUT"
"$OUT" --version
echo
echo "Verify with:"
echo "  $OUT --list-devices"
echo
echo "The ZOTAC GPU should appear as 'ZOTAC GPU' with controller N702E-2001."
