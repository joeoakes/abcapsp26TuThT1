#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS_DIR="$ROOT_DIR/.tools"
mkdir -p "$TOOLS_DIR"

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"

case "$ARCH" in
  x86_64) ARCH="amd64" ;;
  arm64)  ARCH="arm64" ;;
esac

if [[ "$OS" != "darwin" ]]; then
  echo "This installer currently supports macOS only (darwin). Detected: $OS"
  exit 1
fi

if [[ "$ARCH" != "amd64" && "$ARCH" != "arm64" ]]; then
  echo "Unsupported CPU architecture: $ARCH"
  exit 1
fi

echo "Downloading Caddy for $OS/$ARCH into $TOOLS_DIR ..."

TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

# Download from official Caddy download API.
# This returns a tar.gz that contains the `caddy` binary.
URL="https://caddyserver.com/api/download?os=${OS}&arch=${ARCH}"
TARBALL="caddy_${OS}_${ARCH}.tar.gz"

curl -fL "$URL" -o "$TMP_DIR/$TARBALL"

# The API may return either a tar.gz (containing `caddy`) or a raw binary.
MAGIC="$(python - "$TMP_DIR/$TARBALL" <<'PY'
import sys
p = sys.argv[1]
with open(p, "rb") as f:
    b = f.read(2)
print(b.hex())
PY
)"

if [[ "$MAGIC" == "1f8b" ]]; then
  tar -xzf "$TMP_DIR/$TARBALL" -C "$TMP_DIR"
  install -m 0755 "$TMP_DIR/caddy" "$TOOLS_DIR/caddy"
else
  install -m 0755 "$TMP_DIR/$TARBALL" "$TOOLS_DIR/caddy"
fi

echo "Installed: $TOOLS_DIR/caddy"
echo
echo "Next:"
echo "  scripts/run_dashboard_https_local.sh"

