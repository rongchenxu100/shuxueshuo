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
source_tree=$(cd "$source_tree" && pwd -P)
trap 'rm -rf -- "$source_tree"' EXIT
git -C "$PRODUCT_REPO" archive --format=tar "$source_revision" > "$source_tree/source.tar"
mkdir "$source_tree/repo"
tar -xf "$source_tree/source.tar" -C "$source_tree/repo"
alembic_revision=$(python3 "$source_tree/repo/deploy/product/alembic-head.py" "$source_tree/repo/server/alembic/versions")
# The site is served from the server repository (git pull), not from this package;
# its committed pages must still match the content shipped in the images.
node "$source_tree/repo/tools/build-public-knowledge-graph.mjs" --check
node "$source_tree/repo/tools/build-topic-overviews.mjs" --check
node "$source_tree/repo/tools/build-graph-walk-topic.mjs" --check
node "$source_tree/repo/tools/export-public-knowledge.mjs" --check > "$source_tree/content-version.json"
python3 - "$source_tree/content-version.json" "$source_tree/repo/site/knowledge/teaching/version.json" <<'PYVERSION'
import json, sys
expected, actual = (json.load(open(p)) for p in sys.argv[1:])
assert all(expected[k] == actual[k] for k in ('content_version', 'schema_version')), 'static/source content version mismatch'
PYVERSION
mkdir -p "$output"
postgres='postgres:17.10-bookworm@sha256:9b18b78397054fce88a9552e9d5a3ad5bb7fd258c5b3cc1c5028e46373d6ea8f'
# Pin by tag at pull time; release.env records the loadable content digest from images.tar.
rabbitmq='rabbitmq:4.3.2'
docker pull --platform "$platform" "$postgres"
docker pull --platform "$platform" "$rabbitmq"
# Disable attestations: Docker Desktop often breaks tag/save with missing attestation digests.
docker buildx build --load --provenance=false --sbom=false --platform "$platform" \
  -f "$source_tree/repo/deploy/product/Dockerfile.admin" \
  -t "shuxueshuo-product-admin:$release" "$source_tree/repo"
docker buildx build --load --provenance=false --sbom=false --platform "$platform" \
  -f "$source_tree/repo/deploy/product/Dockerfile.app" \
  -t "shuxueshuo-product-app:$release" "$source_tree/repo"
# Cross-arch Desktop pulls only one platform; save must pass --platform or it looks for the
# missing host-arch digest and fails with "unable to create manifests file".
docker save --platform "$platform" -o "$output/images.tar" \
  "shuxueshuo-product-admin:$release" "shuxueshuo-product-app:$release" "$postgres" "$rabbitmq"
# Both identities are verified against images.tar. Classic dockerd runs config IDs;
# containerd-backed engines run OCI manifest IDs for the same image bytes.
eval "$(python3 "$source_tree/repo/deploy/product/image-identities.py" "$output/images.tar" \
  "shuxueshuo-product-admin:$release" "shuxueshuo-product-app:$release" "$platform")"
[[ "$admin_id" == sha256:* && "$app_id" == sha256:* && "$postgres_id" == sha256:* && "$rabbitmq_id" == sha256:* ]] || fail '发布包镜像内容 ID 无效'
cp -R "$source_tree/repo/deploy/product" "$output/scripts"
content_version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["content_version"])' "$source_tree/content-version.json")
content_schema=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["schema_version"])' "$source_tree/content-version.json")
printf '%s\n' "PRODUCT_RELEASE_ID=$release" "PRODUCT_PLATFORM=$platform" "PRODUCT_ADMIN_IMAGE=$admin_id" \
  "PRODUCT_APP_IMAGE=$app_id" "PRODUCT_APP_IMAGE_OCI=$app_oci_id" "PRODUCT_ADMIN_IMAGE_OCI=$admin_oci_id" \
  "PRODUCT_POSTGRES_IMAGE=$postgres_id" "PRODUCT_POSTGRES_IMAGE_OCI=$postgres_oci_id" "PRODUCT_POSTGRES_MANIFEST=$postgres" \
  "PRODUCT_RABBITMQ_IMAGE=$rabbitmq_id" "PRODUCT_RABBITMQ_IMAGE_OCI=$rabbitmq_oci_id" "PRODUCT_RABBITMQ_MANIFEST=$rabbitmq" \
  "PRODUCT_ALEMBIC_REVISION=$alembic_revision" "PRODUCT_SOURCE_REVISION=$source_revision" \
  "PRODUCT_CONTENT_VERSION=$content_version" "PRODUCT_CONTENT_SCHEMA=$content_schema" > "$output/release.env"
checksum "$output/images.tar" > "$output/images.sha256"
# Hash all delivered scripts/configuration; server checks these before running a release.
python3 - "$output" <<'PY'
import hashlib,json,sys
from pathlib import Path
p=Path(sys.argv[1]); files={}
for f in sorted((p/'scripts').rglob('*')):
    if f.is_file(): files[str(f.relative_to(p))]=hashlib.sha256(f.read_bytes()).hexdigest()
for name in ('release.env', 'images.sha256'):
    files[name]=hashlib.sha256((p/name).read_bytes()).hexdigest()
(p/'manifest.json').write_text(json.dumps({'files':files},indent=2))
PY
printf '发布包：%s\n' "$output"
