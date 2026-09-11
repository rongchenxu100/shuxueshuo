#!/usr/bin/env bash
set -euo pipefail
exec "$(dirname "$0")/run.sh" --mode server install "$@"
