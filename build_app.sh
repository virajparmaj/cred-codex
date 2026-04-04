#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="CredCodex"
APP_DIR="$SCRIPT_DIR/dist/$APP_NAME.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
ICONSET_DIR="$RESOURCES_DIR/AppIcon.iconset"
RUNTIME_ICON_NAME="AppIconRuntime.png"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required tool: $1" >&2
    exit 1
  fi
}

for tool in python3 sips iconutil cc plutil; do
  require_cmd "$tool"
done

VERSION="$(python3 - <<'PY'
from pathlib import Path
ns = {}
exec(Path("credcodex/__init__.py").read_text(), ns)
print(ns["__version__"])
PY
)"

mkdir -p "$SCRIPT_DIR/dist"
rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

WORK_DIR="$(mktemp -d "$SCRIPT_DIR/dist/.icon-work.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT
BASE_PPM="$WORK_DIR/base.ppm"
BASE_PNG="$WORK_DIR/base.png"

python3 - "$BASE_PPM" <<'PY'
from math import sqrt
from pathlib import Path
import sys

size = 1024
path = Path(sys.argv[1])
center = size / 2

with path.open("w") as handle:
    handle.write(f"P3\n{size} {size}\n255\n")
    for y in range(size):
        row = []
        for x in range(size):
            dx = x - center
            dy = y - center
            dist = sqrt(dx * dx + dy * dy) / center
            base_r = max(24, int(255 - (dist * 140)))
            base_g = max(38, int(214 - (dist * 110)))
            base_b = max(56, int(162 - (dist * 70)))
            if dist < 0.55:
                base_r = min(255, base_r + 18)
                base_g = min(255, base_g + 24)
                base_b = min(255, base_b + 50)
            if abs(dx) < 130 and abs(dy) < 250:
                base_r = 250
                base_g = 250
                base_b = 252
            if abs(dx) < 240 and abs(dy) < 70:
                base_r = 250
                base_g = 250
                base_b = 252
            row.append(f"{base_r} {base_g} {base_b}")
        handle.write(" ".join(row))
        handle.write("\n")
PY

sips -s format png "$BASE_PPM" --out "$BASE_PNG" >/dev/null
mkdir -p "$ICONSET_DIR"

copy_icon() {
  local size="$1"
  local name="$2"
  sips -z "$size" "$size" "$BASE_PNG" --out "$WORK_DIR/$name" >/dev/null
  cp "$WORK_DIR/$name" "$ICONSET_DIR/$name"
}

copy_icon 16 "icon_16x16.png"
copy_icon 32 "icon_16x16@2x.png"
copy_icon 32 "icon_32x32.png"
copy_icon 64 "icon_32x32@2x.png"
copy_icon 128 "icon_128x128.png"
copy_icon 256 "icon_128x128@2x.png"
copy_icon 256 "icon_256x256.png"
copy_icon 512 "icon_256x256@2x.png"
copy_icon 512 "icon_512x512.png"
copy_icon 1024 "icon_512x512@2x.png"

iconutil -c icns "$ICONSET_DIR" -o "$RESOURCES_DIR/AppIcon.icns"
cp "$WORK_DIR/icon_512x512.png" "$RESOURCES_DIR/$RUNTIME_ICON_NAME"
rm -rf "$ICONSET_DIR"

cat > "$CONTENTS_DIR/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>$APP_NAME</string>
  <key>CFBundleDisplayName</key>
  <string>$APP_NAME</string>
  <key>CFBundleIdentifier</key>
  <string>com.local.credcodex</string>
  <key>CFBundleVersion</key>
  <string>$VERSION</string>
  <key>CFBundleShortVersionString</key>
  <string>$VERSION</string>
  <key>CFBundleExecutable</key>
  <string>$APP_NAME</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>LSUIElement</key>
  <true/>
</dict>
</plist>
PLIST

plutil -lint "$CONTENTS_DIR/Info.plist" >/dev/null

cat > "$MACOS_DIR/launcher.c" <<'CSRC'
#include <libgen.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(void) {
    char exe[4096];
    uint32_t size = sizeof(exe);
    if (_NSGetExecutablePath(exe, &size) != 0) {
        fprintf(stderr, "CredCodex: cannot resolve executable path\n");
        return 1;
    }

    char *resolved = realpath(exe, NULL);
    if (!resolved) {
        perror("realpath");
        return 1;
    }

    const char *repo = getenv("CREDCODEX_REPO");
    if (!repo) {
        repo = "@@REPO_DIR@@";
    }

    char python_path[4096];
    snprintf(python_path, sizeof(python_path), "%s/venv/bin/python", repo);
    if (access(python_path, X_OK) != 0) {
        system("osascript -e 'display dialog \"CredCodex could not find its virtual environment. Please rerun install.sh.\" buttons {\"OK\"} default button \"OK\" with icon stop' 2>/dev/null");
        free(resolved);
        return 1;
    }

    chdir(repo);
    char *argv[] = {"CredCodex", "-m", "credcodex", NULL};
    execv(python_path, argv);
    perror("execv");
    free(resolved);
    return 1;
}
CSRC

sed -i '' "s|@@REPO_DIR@@|$SCRIPT_DIR|g" "$MACOS_DIR/launcher.c"
cc -O2 -o "$MACOS_DIR/$APP_NAME" "$MACOS_DIR/launcher.c"
rm "$MACOS_DIR/launcher.c"

echo "Built $APP_DIR"
