#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
release='' operation='' root=${PRODUCT_DATA_DIR:-/srv/shuxueshuo} instance=server port='' backup='' target=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) [[ "$2" == server ]] || fail 'server mode required'; shift 2;;
    --release) release=${2:?}; shift 2;;
    --data-dir) root=${2:?}; shift 2;;
    --instance) instance=${2:?}; shift 2;;
    --port) port=${2:?}; shift 2;;
    --backup) backup=${2:?}; shift 2;;
    --target) target=${2:?}; shift 2;;
    install|deploy|resume|status|migrate|seed|doctor|backup|restore|bootstrap) operation=$1; shift;;
    *) fail "未知参数：$1";;
  esac
done
if [[ -z "$port" && -f "$root/config/compose.env" ]]; then
  port=$(sed -n "s/^PRODUCT_DB_PORT='\([0-9]*\)'$/\1/p" "$root/config/compose.env")
fi
port=${port:-5432}
[[ "$root" == /* && "$root" != / ]] || fail '需要 Git 外绝对数据目录'
if [[ -f "$PRODUCT_REPO/server/pyproject.toml" && "$root" == "$PRODUCT_REPO"* ]]; then fail '数据目录不能在 Git 内'; fi
[[ "$instance" =~ ^[a-z][a-z0-9_-]{0,39}$ && "$port" =~ ^[0-9]+$ ]] || fail '实例或端口无效'
[[ -n "$operation" ]] || fail '缺少管理操作'
if [[ "$operation" != install && "$operation" != restore && ! -f "$root/config/compose.env" ]]; then
  fail '实例尚未安装'
fi
if [[ -z "$release" && -f "$root/config/release-path" ]]; then release=$(cat "$root/config/release-path"); fi
[[ "$release" == /* && -f "$release/release.env" ]] || fail '--release 需要完整发布包的绝对路径'
command -v docker >/dev/null || fail '请预装 Docker/Compose'
docker compose version >/dev/null
# Parse a restricted data format, never source/eval the release manifest.
while IFS='=' read -r key value; do
  [[ "$key" =~ ^PRODUCT_[A-Z_]+$ && "$value" =~ ^[a-zA-Z0-9/.:@_-]+$ ]] || fail '发布清单格式错误'
  case "$key" in PRODUCT_RELEASE_ID|PRODUCT_PLATFORM|PRODUCT_ADMIN_IMAGE|PRODUCT_POSTGRES_IMAGE|PRODUCT_POSTGRES_MANIFEST|PRODUCT_ALEMBIC_REVISION|PRODUCT_SOURCE_REVISION) export "$key=$value";; *) fail '未知发布字段';; esac
done < "$release/release.env"
[[ "$PRODUCT_ADMIN_IMAGE" == sha256:* && "$PRODUCT_POSTGRES_IMAGE" == sha256:* ]] || fail '镜像必须固定内容 ID'
if ! docker image inspect "$PRODUCT_ADMIN_IMAGE" >/dev/null 2>&1 || ! docker image inspect "$PRODUCT_POSTGRES_IMAGE" >/dev/null 2>&1; then
  [[ "$(checksum "$release/images.tar")" == "$(cat "$release/images.sha256")" ]] || fail '离线镜像包校验失败'
  docker load -i "$release/images.tar"
fi
docker run --rm --entrypoint /opt/product/bin/python -v "$release:/release:ro" "$PRODUCT_ADMIN_IMAGE" -c \
 'import hashlib,json,pathlib; p=pathlib.Path("/release"); m=json.loads((p/"manifest.json").read_text()); assert all(hashlib.sha256((p/n).read_bytes()).hexdigest()==h for n,h in m["files"].items()), "release checksum mismatch"'
actual_platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$PRODUCT_ADMIN_IMAGE")
[[ "$actual_platform" == "$PRODUCT_PLATFORM" ]] || fail '镜像架构与清单不一致'
if ! cmp -s "$0" "$release/scripts/server/run.sh"; then fail '请使用目标发布包 scripts/server/run.sh 或对应版本脚本'; fi
export PRODUCT_DATA_DIR="$root" PRODUCT_INSTANCE="$instance" PRODUCT_DB_PORT="$port" PRODUCT_UID="$(id -u)" PRODUCT_GID="$(id -g)"
mkdir -p "$root"
mkdir -p "$root/locks"
mkdir "$root/locks/server-operation" 2>/dev/null || fail '已有服务器管理操作运行；检查遗留锁后再重试'
trap 'rmdir "$root/locks/server-operation"' EXIT
configure=(docker run --rm --user "$PRODUCT_UID:$PRODUCT_GID" -e PRODUCT_IN_CONTAINER=1 -e "PRODUCT_HOST_DATA_DIR=$root" -v "$root:/var/lib/shuxueshuo" "$PRODUCT_ADMIN_IMAGE")
if [[ "$operation" == restore ]]; then
  [[ -n "$target" && -n "$backup" && ! -e "$root/config" ]] || fail '恢复需要新实例、新目录和 --backup'
  instance="$target"; export PRODUCT_INSTANCE="$instance"
fi
volume="shuxueshuo-product-${instance}_postgres_data"
if docker volume inspect "$volume" >/dev/null 2>&1; then
  volume_root=$(docker volume inspect --format '{{ index .Labels "product.data-root" }}' "$volume")
  [[ "$volume_root" == "$root" ]] || fail '已有数据库卷绑定另一数据目录，拒绝复用'
fi
"${configure[@]}" --mode server --data-dir /var/lib/shuxueshuo --instance "$instance" --port "$port" configure
PRODUCT_BOOTSTRAP_PASSWORD=$(sed -n "s/^PRODUCT_BOOTSTRAP_PASSWORD='\([^']*\)'$/\1/p" "$root/config/bootstrap.env")
export PRODUCT_BOOTSTRAP_PASSWORD
compose=(docker compose --project-name "shuxueshuo-product-$instance" -f "$release/scripts/compose.yml" -f "$release/scripts/compose.server.yml")
admin=("${compose[@]}" run --rm --no-deps admin --mode server --data-dir /var/lib/shuxueshuo --instance "$instance" --port "$port")
case "$operation" in
  install)
    if [[ -f "$root/config/release-path" && "$(cat "$root/config/release-path")" != "$release" ]]; then
      fail '已安装实例的版本变更必须使用 deploy.sh'
    fi
    "${compose[@]}" up -d --wait --wait-timeout 90 postgres; "${admin[@]}" install;;
  deploy)
    [[ -f "$root/config/release-path" ]] || fail '实例尚未安装'
    postgres_container=$("${compose[@]}" ps -q postgres)
    [[ -n "$postgres_container" ]] || fail '数据库容器未运行'
    [[ "$(docker inspect --format '{{.Image}}' "$postgres_container")" == "$PRODUCT_POSTGRES_IMAGE" ]] || fail '数据库镜像变更需要独立备份和升级流程'
    "${admin[@]}" deploy;;
  restore)
    "${compose[@]}" up -d --wait --wait-timeout 90 postgres
    "${admin[@]}" bootstrap
    "${compose[@]}" run --rm --no-deps -v "$backup:/restore:ro" --entrypoint /opt/product/bin/python admin -c \
      'import sys; from shuxueshuo_server.product.config import Settings; from shuxueshuo_server.product.admin.backup import restore_data; s=Settings.load("server","/var/lib/shuxueshuo",sys.argv[1],int(sys.argv[2])); print(restore_data(s,"/restore"))' "$instance" "$port";;
  *) "${admin[@]}" "$operation";;
esac
if [[ "$operation" == install || "$operation" == deploy || "$operation" == restore ]]; then
  printf '%s\n' "$release" > "$root/config/release-path"
  mkdir -p "$root/deployments"
  printf '{"release":"%s","operation":"%s","status":"succeeded"}\n' "$PRODUCT_RELEASE_ID" "$operation" > "$root/deployments/$(date -u +%Y%m%dT%H%M%SZ).json"
fi
