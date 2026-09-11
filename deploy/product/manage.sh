#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
mode=''
args=("$@")
while [[ $# -gt 0 ]]; do
  case "$1" in --mode) mode=${2:?}; shift 2;; *) shift;; esac
done
case "$mode" in
  local) exec uv run --project "$PRODUCT_REPO/server" --frozen python -m shuxueshuo_server.product.admin.cli "${args[@]}";;
  server) exec "$PRODUCT_SCRIPTS/server/run.sh" "${args[@]}";;
  *) fail '需要 --mode local 或 --mode server';;
esac
