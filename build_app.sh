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
ASSETS_DIR="$SCRIPT_DIR/assets"
ICON_ASSETS_DIR="$ASSETS_DIR/icons/macos"
ICON_SOURCE="$ICON_ASSETS_DIR/credcodex_icon_1024.png"
MENU_BAR_ICON="$ASSETS_DIR/credcodex_menubar.png"
MENU_BAR_ICON_2X="$ASSETS_DIR/credcodex_menubar@2x.png"
MENU_BAR_ICON_SOURCE="$ASSETS_DIR/credcodex_menubar_source.png"
TARGET_ALPHA_BOUNDS_RATIO="0.82"
DOCK_ICON_BOUNDS_RATIO="0.72"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required tool: $1" >&2
    exit 1
  fi
}

require_file() {
  if [[ ! -f "$1" ]]; then
    echo "Missing required asset: $1" >&2
    exit 1
  fi
}

for tool in python3 sips iconutil cc plutil; do
  require_cmd "$tool"
done

for asset in "$ICON_SOURCE" "$MENU_BAR_ICON" "$MENU_BAR_ICON_2X" "$MENU_BAR_ICON_SOURCE"; do
  require_file "$asset"
done

VERSION="$(python3 - "$SCRIPT_DIR/credcodex/__init__.py" <<'PY'
from pathlib import Path
import sys

ns = {}
exec(Path(sys.argv[1]).read_text(), ns)
print(ns["__version__"])
PY
)"

mkdir -p "$SCRIPT_DIR/dist"
rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR" "$ICONSET_DIR"

WORK_DIR="$(mktemp -d "$SCRIPT_DIR/dist/.icon-work.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT

scaled_bounds_size() {
  python3 - "$1" "$2" <<'PY'
import sys

size = int(sys.argv[1])
ratio = float(sys.argv[2])
print(max(1, int(round(size * ratio))))
PY
}

normalize_square() {
  python3 - "$1" "$2" "$3" <<'PY'
from pathlib import Path
import subprocess
import sys

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
canvas_size = sys.argv[3]
destination.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(
    ["sips", "--padToHeightWidth", canvas_size, canvas_size, str(source), "--out", str(destination)],
    check=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
PY
}

render_variant() {
  local size="$1"
  local ratio="$2"
  local prefix="$3"
  local scaled_size
  local scaled_path
  local output_path

  scaled_size="$(scaled_bounds_size "$size" "$ratio")"
  scaled_path="$WORK_DIR/${prefix}_${size}_scaled.png"
  output_path="$WORK_DIR/${prefix}_${size}.png"

  sips -Z "$scaled_size" "$ICON_SOURCE" --out "$scaled_path" >/dev/null
  normalize_square "$scaled_path" "$output_path" "$size"
}

for size in 16 32 64 128 256 512 1024; do
  render_variant "$size" "$TARGET_ALPHA_BOUNDS_RATIO" "finder"
  render_variant "$size" "$DOCK_ICON_BOUNDS_RATIO" "dock"
done

cp "$WORK_DIR/finder_16.png" "$ICONSET_DIR/icon_16x16.png"
cp "$WORK_DIR/finder_32.png" "$ICONSET_DIR/icon_16x16@2x.png"
cp "$WORK_DIR/finder_32.png" "$ICONSET_DIR/icon_32x32.png"
cp "$WORK_DIR/finder_64.png" "$ICONSET_DIR/icon_32x32@2x.png"
cp "$WORK_DIR/finder_128.png" "$ICONSET_DIR/icon_128x128.png"
cp "$WORK_DIR/finder_256.png" "$ICONSET_DIR/icon_128x128@2x.png"
cp "$WORK_DIR/finder_256.png" "$ICONSET_DIR/icon_256x256.png"
cp "$WORK_DIR/finder_512.png" "$ICONSET_DIR/icon_256x256@2x.png"
cp "$WORK_DIR/finder_512.png" "$ICONSET_DIR/icon_512x512.png"
cp "$WORK_DIR/finder_1024.png" "$ICONSET_DIR/icon_512x512@2x.png"

iconutil -c icns "$ICONSET_DIR" -o "$RESOURCES_DIR/AppIcon.icns"
cp "$WORK_DIR/dock_512.png" "$RESOURCES_DIR/$RUNTIME_ICON_NAME"
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
