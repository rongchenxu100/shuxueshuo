#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
command -v uv >/dev/null || fail '请先安装 uv'
if [[ -z ${PRODUCT_PG_BIN_DIR:-} ]]; then
  if [[ $(uname -s) == Darwin ]]; then
    command -v brew >/dev/null || fail '请先安装 Homebrew 或配置 PRODUCT_PG_BIN_DIR'
    export HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1
    PRODUCT_PG_BIN_DIR="$(brew --prefix)/opt/postgresql@17/bin"
    [[ -x "$PRODUCT_PG_BIN_DIR/pg_ctl" ]] || brew install postgresql@17
    export PRODUCT_PG_BIN_DIR
  else
    command -v pg_ctl >/dev/null || fail '请预装 PostgreSQL 17，配置 PRODUCT_PG_BIN_DIR'
  fi
fi
uv sync --project "$PRODUCT_REPO/server" --frozen
exec uv run --project "$PRODUCT_REPO/server" --frozen python -m shuxueshuo_server.product.admin.cli --mode local install "$@"
