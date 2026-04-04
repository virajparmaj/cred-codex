#!/usr/bin/env bash

set -euo pipefail

APP_NAME="CredCodex"
APP_DEST="$HOME/Applications/$APP_NAME.app"
PLIST_NAME="com.local.credcodex"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required tool: $1" >&2
    exit 1
  fi
}

for tool in launchctl osascript open; do
  require_cmd "$tool"
done

if pgrep -x "$APP_NAME" >/dev/null 2>&1; then
  osascript -e "tell application \"$APP_NAME\" to quit" 2>/dev/null || true
  sleep 1
  pkill -x "$APP_NAME" 2>/dev/null || true
fi

launchctl bootout "gui/$UID" "$PLIST_PATH" 2>/dev/null \
  || launchctl bootout "gui/$UID/$PLIST_NAME" 2>/dev/null \
  || launchctl unload "$PLIST_PATH" 2>/dev/null \
  || true

rm -f "$PLIST_PATH"
rm -rf "$APP_DEST"

echo "CredCodex was uninstalled."
echo "Local data remains at ~/.credcodex"
