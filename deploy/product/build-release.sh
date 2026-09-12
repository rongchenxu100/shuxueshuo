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
# Pin by tag at pull time; release.env records the loadable content digest from images.tar.
rabbitmq='rabbitmq:4.3.2'
docker pull --platform "$platform" "$postgres"
docker pull --platform "$platform" "$rabbitmq"
# Disable attestations: Docker Desktop often breaks tag/save with missing attestation digests.
docker buildx build --load --provenance=false --sbom=false --platform "$platform" \
  -f "$source_tree/repo/deploy/product/Dockerfile.admin" \
  -t "shuxueshuo-product-admin:$release" "$source_tree/repo"
# Cross-arch Desktop pulls only one platform; save must pass --platform or it looks for the
# missing host-arch digest and fails with "unable to create manifests file".
docker save --platform "$platform" -o "$output/images.tar" \
  "shuxueshuo-product-admin:$release" "$postgres" "$rabbitmq"
# Desktop inspect Id may be an index digest that vanishes after load. Record content IDs
# embedded in images.tar — those are what the server can docker inspect after load.
eval "$(python3 - "$output/images.tar" "shuxueshuo-product-admin:$release" <<'PY'
import json, shlex, sys, tarfile

def digest_of(config: str) -> str:
    name = config.split('/')[-1]
    if name.endswith('.json'):
        name = name[:-5]
    return name if name.startswith('sha256:') else f'sha256:{name}'

with tarfile.open(sys.argv[1]) as tar:
    manifest = json.load(tar.extractfile('manifest.json'))
admin = postgres = rabbit = None
untagged = []
for item in manifest:
    tags = [t for t in (item.get('RepoTags') or []) if t]
    digest = digest_of(item['Config'])
    joined = ' '.join(tags)
    if any(t == sys.argv[2] or t.endswith('/' + sys.argv[2]) for t in tags):
        admin = digest
    elif 'rabbitmq' in joined:
        rabbit = digest
    elif 'postgres' in joined:
        postgres = digest
    elif not tags:
        # Digest-pinned postgres saves often omit RepoTags on Desktop.
        untagged.append(digest)
if postgres is None and len(untagged) == 1:
    postgres = untagged[0]
if not admin or not postgres or not rabbit:
    raise SystemExit(
        f'could not resolve image digests from tar: admin={admin!r} postgres={postgres!r} '
        f'rabbitmq={rabbit!r} untagged={untagged!r} manifest={manifest!r}')
print(f'admin_id={shlex.quote(admin)}')
print(f'postgres_id={shlex.quote(postgres)}')
print(f'rabbitmq_id={shlex.quote(rabbit)}')
PY
)"
[[ "$admin_id" == sha256:* && "$postgres_id" == sha256:* && "$rabbitmq_id" == sha256:* ]] || fail '发布包镜像内容 ID 无效'
cp -R "$source_tree/repo/deploy/product" "$output/scripts"
printf '%s\n' "PRODUCT_RELEASE_ID=$release" "PRODUCT_PLATFORM=$platform" "PRODUCT_ADMIN_IMAGE=$admin_id" \
  "PRODUCT_POSTGRES_IMAGE=$postgres_id" "PRODUCT_POSTGRES_MANIFEST=$postgres" \
  "PRODUCT_RABBITMQ_IMAGE=$rabbitmq_id" "PRODUCT_RABBITMQ_MANIFEST=$rabbitmq" \
  "PRODUCT_ALEMBIC_REVISION=0002_product_runtime_indexes" "PRODUCT_SOURCE_REVISION=$source_revision" > "$output/release.env"
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
