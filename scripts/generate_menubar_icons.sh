#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SOURCE="$REPO_ROOT/assets/credcodex_menubar_source.png"
OUTPUT_1X="$REPO_ROOT/assets/credcodex_menubar.png"
OUTPUT_2X="$REPO_ROOT/assets/credcodex_menubar@2x.png"

if [[ ! -f "$SOURCE" ]]; then
  echo "Missing source asset: $SOURCE" >&2
  exit 1
fi

sips -z 22 22 "$SOURCE" --out "$OUTPUT_1X"
sips -z 44 44 "$SOURCE" --out "$OUTPUT_2X"
