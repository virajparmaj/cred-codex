#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
APP_NAME="CredCodex"
APP_SUPPORT_DIR="$HOME/.credcodex"
APP_DEST="$HOME/Applications/$APP_NAME.app"
PLIST_NAME="com.local.credcodex"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required tool: $1" >&2
    exit 1
  fi
}

launch_agent_loaded() {
  launchctl print "gui/$UID/$PLIST_NAME" >/dev/null 2>&1 || launchctl list "$PLIST_NAME" >/dev/null 2>&1
}

stop_launch_agent() {
  if launch_agent_loaded; then
    launchctl bootout "gui/$UID" "$PLIST_PATH" 2>/dev/null \
      || launchctl bootout "gui/$UID/$PLIST_NAME" 2>/dev/null \
      || launchctl unload "$PLIST_PATH" 2>/dev/null \
      || true
  fi
}

for tool in python3 launchctl osascript open ditto xattr sips iconutil cc plutil; do
  require_cmd "$tool"
done

if pgrep -x "$APP_NAME" >/dev/null 2>&1; then
  osascript -e "tell application \"$APP_NAME\" to quit" 2>/dev/null || true
  sleep 1
  pkill -x "$APP_NAME" 2>/dev/null || true
fi

stop_launch_agent
rm -rf "$APP_DEST"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip setuptools wheel
"$VENV_DIR/bin/pip" install --quiet -e "$SCRIPT_DIR"

bash "$SCRIPT_DIR/build_app.sh"

mkdir -p "$HOME/Applications"
ditto "$SCRIPT_DIR/dist/$APP_NAME.app" "$APP_DEST"
mkdir -p "$APP_SUPPORT_DIR" "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$PLIST_NAME</string>
  <key>ProgramArguments</key>
  <array>
    <string>open</string>
    <string>-a</string>
    <string>$APP_DEST</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <false/>
</dict>
</plist>
PLIST

launchctl bootstrap "gui/$UID" "$PLIST_PATH" 2>/dev/null || launchctl load "$PLIST_PATH"
open "$APP_DEST"

echo "Installed CredCodex."
echo "App:    $APP_DEST"
echo "Config: $APP_SUPPORT_DIR/config.json"
echo "Logs:   $APP_SUPPORT_DIR/credcodex.log"
