#!/usr/bin/env bash
set -euo pipefail
PRODUCT_REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
PRODUCT_SCRIPTS=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
fail() { echo "$*" >&2; exit 2; }
checksum() {
  if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d ' ' -f 1
  else shasum -a 256 "$1" | cut -d ' ' -f 1; fi
}
