# 服务器 OCR（CentOS 7 + Docker）

CentOS 7（glibc 2.17）无法直接运行 PaddlePaddle 3.x（需要 glibc ≥ 2.27）。
因此 OCR 跑在 `python:3.11-slim-bookworm` 容器中，宿主机用
`server/.venv-ocr/bin/python` 封装脚本调用，兼容现有 `REVIEW_OCR_PYTHON` 约定。

## 已验证基线（2026-09-12）

| 项 | 值 |
| --- | --- |
| 宿主机 | CentOS 7 x86_64，AVX/AVX2，Docker 26 |
| 镜像 | `shuxueshuo-ocr:3.3.0` |
| PaddlePaddle | 3.3.0 CPU |
| PaddleOCR | 3.7.0 + doc-parser |
| PaddleX | 3.7.2 |
| 模型缓存 | `$HOME/.paddlex/official_models/` |
| 推理后端 | `run_mode=paddle`（禁用默认 mkldnn，避免 PIR/oneDNN 崩溃） |

## 构建

Docker Hub 直连常超时，先用镜像源拉基础镜像并打本地 tag：

```bash
docker pull docker.m.daocloud.io/library/python:3.11-slim-bookworm
docker tag docker.m.daocloud.io/library/python:3.11-slim-bookworm python:3.11-slim-bookworm

cd /home/ronghao/code/shuxueshuo
docker build -t shuxueshuo-ocr:3.3.0 -f deploy/ocr/Dockerfile .
```

部署用户需能访问 Docker（`docker` 组或 sudo）。

## 封装脚本

```bash
mkdir -p server/.venv-ocr/bin
cp deploy/ocr/python-wrapper.sh server/.venv-ocr/bin/python
chmod +x server/.venv-ocr/bin/python
```

## 模型预热

```bash
docker run --rm \
  -v /home/ronghao/code/shuxueshuo:/opt/shuxueshuo \
  -v "$HOME/.paddlex:/root/.paddlex" \
  -w /opt/shuxueshuo/server \
  -e PADDLE_PDX_MODEL_SOURCE=bos \
  -e PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
  -e OMP_NUM_THREADS=1 \
  shuxueshuo-ocr:3.3.0 \
  python /opt/shuxueshuo/deploy/ocr/preheat_models.py
```

验收：

```bash
server/.venv-ocr/bin/python -c "
from shuxueshuo_server.solver.extraction.paddle_worker import PaddleF2ProviderWorker
print([m.component for m in PaddleF2ProviderWorker().manifests()])
"
```

## 注意

- 不要在 CentOS 7 宿主机 `uv pip install paddlepaddle`。
- Linux CPU 上 PaddleX 默认 `mkldnn`；`paddle_worker` 已强制 `run_mode=paddle` / `enable_mkldnn=False`。
- `.venv-ocr/` 与 `~/.paddlex/` 不进 Git。
