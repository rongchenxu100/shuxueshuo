# OCR

## 本地 Mac（直装，无 Docker）

产品本地模式（`--mode local`）与开发机：在本机 Python 环境安装 Paddle / PaddleOCR，用 `REVIEW_OCR_PYTHON` 指向该解释器。不启动 sidecar，不设 `PRODUCT_OCR_URL`。

## 服务器（CentOS 7 + Docker 常驻 sidecar）

CentOS 7（glibc 2.17）无法直接运行 PaddlePaddle 3.x（需要 glibc ≥ 2.27）。
因此 OCR 使用 `shuxueshuo-ocr:3.3.0` 镜像。产品栈通过 Compose 服务 **`ocr`** 常驻该镜像，预热模型后提供 HTTP：

- `GET /health`
- `GET /v1/manifests` — provider 清单（构建依赖指纹）
- `POST /v1/observe` — body：`{work_dir, source_id, phase}`

Worker / API 设置 `PRODUCT_OCR_URL=http://ocr:8080`，**不再**经 `docker.sock` 每次 `docker run`。

脚本入口：[`sidecar_server.py`](sidecar_server.py)（容器内挂载仓库 `deploy/ocr/`）。

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

## 手工封装（可选，非产品 server 路径）

宿主机冒烟仍可用包装脚本（每次临时容器，**产品 server 已改用 sidecar**）：

```bash
mkdir -p server/.venv-ocr/bin
cp deploy/ocr/python-wrapper.sh server/.venv-ocr/bin/python
chmod +x server/.venv-ocr/bin/python
```

## 模型预热

```bash
docker run --rm \
  -v "$HOME/code/shuxueshuo:/opt/shuxueshuo" \
  -v "$HOME/.paddlex:/root/.paddlex" \
  -w /opt/shuxueshuo/server \
  -e PADDLE_PDX_MODEL_SOURCE=bos \
  -e PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
  -e OMP_NUM_THREADS=1 \
  shuxueshuo-ocr:3.3.0 \
  python /opt/shuxueshuo/deploy/ocr/preheat_models.py
```

产品 `services-start` 会启动 sidecar；首次就绪可能需 1–2 分钟（health `start_period`）。验收：

```bash
docker exec shuxueshuo-product-server-ocr-1 \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/health').read())"
```

## 注意

- 不要在 CentOS 7 宿主机 `uv pip install paddlepaddle`。
- Linux CPU 上 PaddleX 默认 `mkldnn`；`paddle_worker` 已强制 `run_mode=paddle` / `enable_mkldnn=False`。
- `.venv-ocr/` 与 `~/.paddlex/` 不进 Git。
- sidecar 与 worker 共享 `/var/lib/shuxueshuo`；以部署用户 UID 运行，避免 work 目录权限问题。
