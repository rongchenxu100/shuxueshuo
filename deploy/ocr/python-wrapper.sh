#!/bin/bash
# 安装到服务器：server/.venv-ocr/bin/python
# 使 REVIEW_OCR_PYTHON / 默认 OCR 路径在 CentOS 7 上通过 Docker 运行 Paddle。
set -euo pipefail
REPO="${SHUXUESHUO_REPO:-/home/ronghao/code/shuxueshuo}"
IMAGE="${SHUXUESHUO_OCR_IMAGE:-shuxueshuo-ocr:3.3.0}"
mkdir -p "${HOME}/.paddlex"
exec docker run --rm \
  -v "${REPO}:/opt/shuxueshuo" \
  -v "${HOME}/.paddlex:/root/.paddlex" \
  -w /opt/shuxueshuo/server \
  -e PADDLE_PDX_MODEL_SOURCE=bos \
  -e PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
  -e OMP_NUM_THREADS=1 \
  -e PYTHONPATH=/opt/shuxueshuo/server \
  "${IMAGE}" \
  python "$@"
