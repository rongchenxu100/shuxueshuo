#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
release='' platform='' output=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --release) release=${2:?}; shift 2;;
    --platform) platform=${2:?}; shift 2;;
    --output) output=${2:?}; shift 2;;
    *) fail "未知参数：$1";;
  esac
done
[[ "$release" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]+$ ]] || fail '需要 --release 标识'
[[ "$platform" == linux/arm64 || "$platform" == linux/amd64 ]] || fail '需要 --platform linux/arm64 或 linux/amd64（分别生成发布包）'
[[ "$output" == /* && ! -e "$output" ]] || fail '--output 必须是不存在的绝对目录'
[[ -z "$(git -C "$PRODUCT_REPO" status --porcelain --untracked-files=all)" ]] || fail '发布要求干净工作树：请先提交修改和未跟踪文件'
source_revision=$(git -C "$PRODUCT_REPO" rev-parse HEAD)
# Build and package the very same committed tree; ignored files and concurrent edits cannot enter.
source_tree=$(mktemp -d "${TMPDIR:-/tmp}/shuxueshuo-release.XXXXXXXX")
trap 'rm -rf -- "$source_tree"' EXIT
git -C "$PRODUCT_REPO" archive --format=tar "$source_revision" > "$source_tree/source.tar"
mkdir "$source_tree/repo"
tar -xf "$source_tree/source.tar" -C "$source_tree/repo"
mkdir -p "$output"
postgres='postgres:17.10-bookworm@sha256:9b18b78397054fce88a9552e9d5a3ad5bb7fd258c5b3cc1c5028e46373d6ea8f'
docker pull --platform "$platform" "$postgres"
docker buildx build --load --platform "$platform" -f "$source_tree/repo/deploy/product/Dockerfile.admin" \
  -t "shuxueshuo-product-admin:$release" "$source_tree/repo"
admin_id=$(docker image inspect --format '{{.Id}}' "shuxueshuo-product-admin:$release")
postgres_id=$(docker image inspect --format '{{.Id}}' "$postgres")
docker tag "$postgres_id" "shuxueshuo-product-postgres:$release"
docker save -o "$output/images.tar" "shuxueshuo-product-admin:$release" "shuxueshuo-product-postgres:$release"
cp -R "$source_tree/repo/deploy/product" "$output/scripts"
printf '%s\n' "PRODUCT_RELEASE_ID=$release" "PRODUCT_PLATFORM=$platform" "PRODUCT_ADMIN_IMAGE=$admin_id" \
  "PRODUCT_POSTGRES_IMAGE=$postgres_id" "PRODUCT_POSTGRES_MANIFEST=$postgres" \
  "PRODUCT_ALEMBIC_REVISION=0001_product" "PRODUCT_SOURCE_REVISION=$source_revision" > "$output/release.env"
checksum "$output/images.tar" > "$output/images.sha256"
# Hash all delivered scripts/configuration; server checks these before running a release.
python3 - "$output" <<'PY'
import hashlib,json,sys
from pathlib import Path
p=Path(sys.argv[1]); files={}
for f in sorted((p/'scripts').rglob('*')):
    if f.is_file(): files[str(f.relative_to(p))]=hashlib.sha256(f.read_bytes()).hexdigest()
files['release.env']=hashlib.sha256((p/'release.env').read_bytes()).hexdigest()
(p/'manifest.json').write_text(json.dumps({'files':files},indent=2))
PY
printf '发布包：%s\n' "$output"
