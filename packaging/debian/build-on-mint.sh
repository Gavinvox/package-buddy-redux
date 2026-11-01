#!/usr/bin/env bash
# One-shot build of the desktop .deb on Linux Mint / Ubuntu / Debian.
# Needs Flutter on PATH (https://docs.flutter.dev/get-started/install/linux/desktop).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
sudo apt-get install -y clang cmake ninja-build pkg-config libgtk-3-dev liblzma-dev libstdc++-12-dev python3-pil dpkg-dev
cd "$ROOT/client" && flutter pub get && flutter build linux --release
"$ROOT/packaging/debian/build-deb.sh"
