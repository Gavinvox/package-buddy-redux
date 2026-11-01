#!/bin/sh
# Rebuilds the Flutter web app and copies it to app/web (served by the server at /).
# Needs the Flutter SDK. Not needed for a normal install: the package already contains app/web.
set -e
cd "$(dirname "$0")/client"
flutter pub get
flutter build web --release --no-web-resources-cdn --pwa-strategy=none
cd ..
rm -rf app/web
cp -r client/build/web app/web
find app/web -name '*.symbols' -delete
echo "Web app copied to app/web"
