#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
command -v uv >/dev/null || fail '请先安装 uv'
command -v node >/dev/null || fail '请先安装 Node.js'
command -v npm >/dev/null || fail '请先安装 npm'
if [[ $(uname -s) == Darwin ]]; then
  command -v brew >/dev/null || fail '请先安装 Homebrew'
  export HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1
  [[ -x "$(brew --prefix)/opt/rabbitmq/sbin/rabbitmq-server" ]] || brew install rabbitmq
  export PRODUCT_RABBITMQ_BIN="$(brew --prefix)/opt/rabbitmq/sbin"
fi
uv sync --project "$PRODUCT_REPO/server" --frozen
npm --prefix "$PRODUCT_REPO/frontend" ci
exec "$PRODUCT_SCRIPTS/manage.sh" --mode local services-install "$@"
