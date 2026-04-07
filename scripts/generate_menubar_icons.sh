#!/usr/bin/env bash

set -euo pipefail

SOURCE="/Users/veerr_89/Work/tools/cred-codex/assets/credcodex_menubar_source.png"
OUTPUT_1X="/Users/veerr_89/Work/tools/cred-codex/assets/credcodex_menubar.png"
OUTPUT_2X="/Users/veerr_89/Work/tools/cred-codex/assets/credcodex_menubar@2x.png"

if [[ ! -f "$SOURCE" ]]; then
  echo "Missing source asset: $SOURCE" >&2
  exit 1
fi

sips -z 22 22 "$SOURCE" --out "$OUTPUT_1X"
sips -z 44 44 "$SOURCE" --out "$OUTPUT_2X"
