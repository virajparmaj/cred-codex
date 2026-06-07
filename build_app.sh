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

restore_fallback_icns() {
  local fallback_ref="HEAD:dist/$APP_NAME.app/Contents/Resources/AppIcon.icns"

  if command -v git >/dev/null 2>&1 && git cat-file -e "$fallback_ref" 2>/dev/null; then
    git show "$fallback_ref" > "$RESOURCES_DIR/AppIcon.icns"
    return 0
  fi

  echo "iconutil failed and no fallback AppIcon.icns is available in git." >&2
  return 1
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

if ! iconutil -c icns "$ICONSET_DIR" -o "$RESOURCES_DIR/AppIcon.icns"; then
  restore_fallback_icns
fi
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

# Resolve Python framework build settings from the venv interpreter. We embed
# Python (link against the framework + Py_InitializeFromConfig) rather than
# execv-ing to it, so the launched process identity stays "CredCodex" instead of
# "Python". macOS Tahoe's menu bar permission system keys off that identity, so
# embedding is what lets the NSStatusItem register and appear in Control Center's
# "Allow in the Menu Bar" list.
VENV_PY="$SCRIPT_DIR/venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "Missing venv interpreter: $VENV_PY (run install.sh first)" >&2
  exit 1
fi

read_py_config() {
  "$VENV_PY" - <<'PY'
import sys
import sysconfig

# base_prefix from sys (NOT sysconfig.get_config_var('base_prefix'), which
# returns the venv path and breaks stdlib/encodings import when used as home).
print(sysconfig.get_path("include"))
print(sysconfig.get_config_var("LIBDIR"))
print(sysconfig.get_config_var("VERSION"))
print(sys.base_prefix)
PY
}

{
  read -r PYTHON_INCLUDE
  read -r PYTHON_LIBDIR
  read -r VENV_PY_VERSION
  read -r PYTHON_FW_PREFIX
} < <(read_py_config)

PYTHON_LDLIB="-lpython${VENV_PY_VERSION}"

for var in PYTHON_INCLUDE PYTHON_LIBDIR VENV_PY_VERSION PYTHON_FW_PREFIX; do
  if [[ -z "${!var}" ]]; then
    echo "Failed to resolve $var from venv interpreter" >&2
    exit 1
  fi
done

LAUNCHER_SRC="$MACOS_DIR/launcher.c"

cat > "$LAUNCHER_SRC" <<'CSRC'
#include <Python.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

/* Embedded-Python launcher. The process identity must remain the app binary
 * (not "Python") for macOS Tahoe's menu bar permission system to register the
 * app's NSStatusItem, so we link the Python framework and initialize in-process
 * instead of execv-ing to the venv interpreter. */

#define APP_NAME "CredCodex"
#define PY_FW_PREFIX "@@PY_FW_PREFIX@@"
#define VENV_PY_VERSION "@@VENV_PY_VERSION@@"

static int fail_status(PyConfig *config, PyStatus status) {
    PyConfig_Clear(config);
    if (PyStatus_IsExit(status)) {
        return status.exitcode;
    }
    Py_ExitStatusException(status);
    return 1;
}

int main(void) {
    const char *repo = getenv("CREDCODEX_REPO");
    if (!repo) {
        repo = "@@REPO_DIR@@";
    }

    char python_path[4096];
    snprintf(python_path, sizeof(python_path), "%s/venv/bin/python", repo);
    if (access(python_path, X_OK) != 0) {
        system("osascript -e 'display dialog \"CredCodex could not find its virtual environment. Please rerun install.sh.\" buttons {\"OK\"} default button \"OK\" with icon stop' 2>/dev/null");
        return 1;
    }

    if (chdir(repo) != 0) {
        perror("chdir");
        return 1;
    }

    PyStatus status;
    PyConfig config;
    PyConfig_InitPythonConfig(&config);

    /* Point home at the BASE Python prefix so the stdlib (encodings, etc.) is
     * found. Pointing this at the venv breaks stdlib import. */
    status = PyConfig_SetBytesString(&config, &config.home, PY_FW_PREFIX);
    if (PyStatus_Exception(status)) {
        return fail_status(&config, status);
    }

    /* Keep the process identity as the app, not "python". */
    status = PyConfig_SetBytesString(&config, &config.program_name, APP_NAME);
    if (PyStatus_Exception(status)) {
        return fail_status(&config, status);
    }

    status = Py_InitializeFromConfig(&config);
    if (PyStatus_Exception(status)) {
        return fail_status(&config, status);
    }
    PyConfig_Clear(&config);

    /* Prepend the venv site-packages and repo root to sys.path, repoint
     * sys.prefix/exec_prefix at the venv, and set argv[0] to the app name. */
    char bootstrap[8192];
    snprintf(bootstrap, sizeof(bootstrap),
        "import sys\n"
        "venv = r'%s/venv'\n"
        "repo = r'%s'\n"
        "site_packages = venv + '/lib/python%s/site-packages'\n"
        "sys.path.insert(0, site_packages)\n"
        "sys.path.insert(0, repo)\n"
        "sys.prefix = venv\n"
        "sys.exec_prefix = venv\n"
        "sys.argv = ['" APP_NAME "']\n",
        repo, repo, VENV_PY_VERSION);

    if (PyRun_SimpleString(bootstrap) != 0) {
        fprintf(stderr, "CredCodex: failed to bootstrap sys.path\n");
        Py_Finalize();
        return 1;
    }

    int rc = PyRun_SimpleString(
        "from credcodex.__main__ import main\n"
        "main()\n");

    Py_Finalize();
    return rc == 0 ? 0 : 1;
}
CSRC

sed -i '' \
  -e "s|@@REPO_DIR@@|$SCRIPT_DIR|g" \
  -e "s|@@PY_FW_PREFIX@@|$PYTHON_FW_PREFIX|g" \
  -e "s|@@VENV_PY_VERSION@@|$VENV_PY_VERSION|g" \
  "$LAUNCHER_SRC"

cc -O2 -I"$PYTHON_INCLUDE" -L"$PYTHON_LIBDIR" $PYTHON_LDLIB \
  -framework CoreFoundation -Wl,-rpath,"$PYTHON_FW_PREFIX/lib" \
  -o "$MACOS_DIR/$APP_NAME" "$LAUNCHER_SRC"
rm "$LAUNCHER_SRC"

echo "Built $APP_DIR"
