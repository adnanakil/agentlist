#!/bin/bash
set -euo pipefail

SOURCE=${1:-scripts/hal_findmy_helper.swift}
DESTINATION=${2:-"$HOME/.hal/HalFindMyHelper.app"}
INFO_PLIST=${3:-scripts/HalFindMyHelper-Info.plist}
CONTENTS="$DESTINATION/Contents"
MACOS="$CONTENTS/MacOS"
EXECUTABLE="$MACOS/HalFindMyHelper"
PLIST="$CONTENTS/Info.plist"
MODULE_CACHE=${TMPDIR:-/tmp}/hal-findmy-module-cache

mkdir -p "$MACOS" "$MODULE_CACHE"
xcrun swiftc \
  "$SOURCE" \
  -o "$EXECUTABLE" \
  -module-cache-path "$MODULE_CACHE" \
  -framework AppKit \
  -framework ApplicationServices

cp "$INFO_PLIST" "$PLIST"

codesign --force --sign - "$DESTINATION"
echo "Built $DESTINATION"
