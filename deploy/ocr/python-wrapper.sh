#!/bin/bash
# 安装到服务器：server/.venv-ocr/bin/python
# 使 REVIEW_OCR_PYTHON / 默认 OCR 路径在 CentOS 7 上通过 Docker 运行 Paddle。
# 产品 worker 经嵌套 Docker 跑 observation 时需挂载数据根（work/*/normalized.png）。
set -euo pipefail
REPO="${SHUXUESHUO_REPO:-$HOME/code/shuxueshuo}"
IMAGE="${SHUXUESHUO_OCR_IMAGE:-shuxueshuo-ocr:3.3.0}"
DATA_DIR="${SHUXUESHUO_HOST_DATA_DIR:-${PRODUCT_DATA_DIR:-/srv/shuxueshuo}}"
mkdir -p "${HOME}/.paddlex"
exec docker run --rm \
  -v "${REPO}:/opt/shuxueshuo" \
  -v "${HOME}/.paddlex:/root/.paddlex" \
  -v "${DATA_DIR}:/var/lib/shuxueshuo" \
  -w /opt/shuxueshuo/server \
  -e PADDLE_PDX_MODEL_SOURCE=bos \
  -e PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
  -e OMP_NUM_THREADS=1 \
  -e PYTHONPATH=/opt/shuxueshuo/server \
  "${IMAGE}" \
  python "$@"
