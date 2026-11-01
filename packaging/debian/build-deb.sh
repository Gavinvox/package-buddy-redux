#!/usr/bin/env bash
# Builds packagebuddy-redux_<version>_amd64.deb from a Flutter Linux release bundle.
# Usage (from the repo root, after `cd client && flutter build linux --release`):
#   packaging/debian/build-deb.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BUNDLE="${BUNDLE:-$ROOT/client/build/linux/x64/release/bundle}"
VERSION="${VERSION:-$(sed -n 's/^version: *\([0-9.]*\).*/\1/p' "$ROOT/client/pubspec.yaml")}"
ID=net.packagebuddy.selfhosted.packagebuddy
OUT="${OUT:-$ROOT/dist}"
[ -x "$BUNDLE/packagebuddy" ] || { echo "No Linux bundle at $BUNDLE. Run: cd client && flutter build linux --release"; exit 1; }
command -v python3 >/dev/null && python3 -c 'import PIL' 2>/dev/null || { echo "Needs python3-pil (sudo apt install python3-pil)"; exit 1; }

R="$(mktemp -d)"; trap 'rm -rf "$R"' EXIT
mkdir -p "$R/DEBIAN" "$R/opt/packagebuddy-redux" "$R/usr/bin" "$R/usr/share/applications" "$OUT"
cp -a "$BUNDLE/." "$R/opt/packagebuddy-redux/"
ln -s /opt/packagebuddy-redux/packagebuddy "$R/usr/bin/packagebuddy-redux"
for s in 32 48 64 128 256 512; do
  d="$R/usr/share/icons/hicolor/${s}x${s}/apps"; mkdir -p "$d"
  python3 - "$ROOT/client/assets/icon/logo.png" "$d/$ID.png" "$s" <<'PY'
import sys
from PIL import Image
src, dst, s = sys.argv[1], sys.argv[2], int(sys.argv[3])
im = Image.open(src).convert("RGBA"); im.thumbnail((s, s), Image.LANCZOS)
c = Image.new("RGBA", (s, s), (0, 0, 0, 0)); c.paste(im, ((s - im.width) // 2, (s - im.height) // 2)); c.save(dst)
PY
done
cat > "$R/usr/share/applications/$ID.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Package Buddy Redux
GenericName=Package Tracker
Comment=Track your packages with your own Package Buddy Redux server
Exec=/opt/packagebuddy-redux/packagebuddy
Icon=$ID
Terminal=false
Categories=Utility;Office;
StartupWMClass=$ID
StartupNotify=true
DESK
SIZE=$(du -sk "$R/opt" "$R/usr" | awk '{s+=$1} END{print s}')
cat > "$R/DEBIAN/control" <<CTL
Package: packagebuddy-redux
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Installed-Size: $SIZE
Maintainer: Gavinvox <noreply@users.noreply.github.com>
Homepage: https://github.com/Gavinvox/package-buddy-redux
Depends: libgtk-3-0, libglib2.0-0, libc6 (>= 2.34), libstdc++6, libblkid1, liblzma5
Recommends: zenity
Description: Package Buddy Redux desktop client
 Desktop app for a self-hosted Package Buddy Redux server. Syncs with your
 server account and shows desktop notifications for package updates while open.
CTL
printf '#!/bin/sh\nset -e\ncommand -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true\ncommand -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true\n' > "$R/DEBIAN/postinst"
cp "$R/DEBIAN/postinst" "$R/DEBIAN/postrm"; chmod 755 "$R/DEBIAN/postinst" "$R/DEBIAN/postrm"
dpkg-deb --build --root-owner-group -Zxz "$R" "$OUT/packagebuddy-redux_${VERSION}_amd64.deb"
echo "Built $OUT/packagebuddy-redux_${VERSION}_amd64.deb"
