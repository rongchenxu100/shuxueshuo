# Studio 创作工作台部署与维护

本文档维护 `frontend/` 下的 Next.js Studio 工作台，域名 **https://studio.shuxueshuo.com**。
默认页面为新产品工作台（`ProductWorkspace`）；仅当显式设置 `WORKSPACE_MODE=mock` 时才走旧 mock 界面。

产品 API 由服务器 P2 Compose 提供（`127.0.0.1:8000`）。Nginx 将 `/api/product/`（含 WebSocket）直反代到该端口；页面其余路径反代到本机 Next（`127.0.0.1:3000`）。

## 服务器约定

```bash
CONTAINER_NAME=shuxueshuo-studio
IMAGE_NAME=shuxueshuo-studio:latest
APP_PORT=3000   # 仅绑 127.0.0.1，由 Nginx 对外
```

产品 API 与主站微信 `/api/` 共用 P2 `api` 容器的 `127.0.0.1:8000`。勿再启用旧的 `shuxueshuo-api` systemd。

## 推荐部署：本机构建 amd64 → 上传 → docker load

CentOS 服务器访问 Docker Hub 常超时，在 Mac 上构建后上传。

### 1. Mac 本地构建

使用仓库 **main** 上的 `frontend/`（不要再用过期 worktree）：

```bash
cd /Users/haorong/projects/code/shuxueshuo/frontend

# WS 地址在构建期内联；生产必须指向 studio 域名
docker buildx build \
  --platform linux/amd64 \
  --build-arg NEXT_PUBLIC_PRODUCT_WS_ORIGIN=wss://studio.shuxueshuo.com \
  -t shuxueshuo-studio:latest \
  --load \
  .

docker save shuxueshuo-studio:latest | gzip > /tmp/shuxueshuo-studio.tar.gz
scp /tmp/shuxueshuo-studio.tar.gz ronghao@39.107.235.86:/home/ronghao/
```

### 2. 服务器加载并启动

```bash
docker load < /home/ronghao/shuxueshuo-studio.tar.gz
docker rm -f shuxueshuo-studio 2>/dev/null || true

# 不要设置 WORKSPACE_MODE=mock
docker run -d \
  --name shuxueshuo-studio \
  --restart unless-stopped \
  -p 127.0.0.1:3000:3000 \
  shuxueshuo-studio:latest

curl -sSI http://127.0.0.1:3000 | head
```

正式访问：https://studio.shuxueshuo.com

## 切流检查清单（首次接产品 API）

1. 停止并禁用旧 uvicorn：`sudo systemctl stop shuxueshuo-api && sudo systemctl disable shuxueshuo-api`
2. 产品 `API_PORT='8000'`，`services-start` / `services-doctor` 通过
3. 部署本页所述新 studio 镜像
4. 安装更新后的 Nginx 模板并 reload（见下）
5. 浏览器确认新产品工作台；上传/构建可用

## 日常更新

```bash
# Mac
cd /Users/haorong/projects/code/shuxueshuo/frontend
docker buildx build --platform linux/amd64 \
  --build-arg NEXT_PUBLIC_PRODUCT_WS_ORIGIN=wss://studio.shuxueshuo.com \
  -t shuxueshuo-studio:latest --load .
docker save shuxueshuo-studio:latest | gzip > /tmp/shuxueshuo-studio.tar.gz
scp /tmp/shuxueshuo-studio.tar.gz ronghao@39.107.235.86:/home/ronghao/

# 服务器
docker load < /home/ronghao/shuxueshuo-studio.tar.gz
docker rm -f shuxueshuo-studio
docker run -d --name shuxueshuo-studio --restart unless-stopped \
  -p 127.0.0.1:3000:3000 shuxueshuo-studio:latest
docker logs --tail=50 shuxueshuo-studio
```

可选回滚 tag：

```bash
docker tag shuxueshuo-studio:latest shuxueshuo-studio:$(date +%Y%m%d-%H%M)
```

## Nginx

模板：[nginx/studio.shuxueshuo.com.conf](nginx/studio.shuxueshuo.com.conf)

- `location /api/product/` → `http://127.0.0.1:8000`（`Host 127.0.0.1`，支持 WebSocket）
- `location /` → `http://127.0.0.1:3000`

```bash
sudo cp /home/ronghao/code/shuxueshuo/deploy/nginx/studio.shuxueshuo.com.conf \
  /etc/nginx/conf.d/studio.shuxueshuo.com.conf
# 若仓库未更新，也可从发布机 scp 该文件
sudo nginx -t && sudo systemctl reload nginx
```

证书：

```text
/home/ronghao/cert/studio-shuxueshuo/studio.shuxueshuo.com.pem
/home/ronghao/cert/studio-shuxueshuo/studio.shuxueshuo.com.key
```

仅对公网开放 80/443；**不要**长期对公网暴露 3000/8000。

## 环境与安全边界

| 项 | 说明 |
|---|---|
| `NEXT_PUBLIC_PRODUCT_WS_ORIGIN` | 构建参数，生产为 `wss://studio.shuxueshuo.com` |
| `WORKSPACE_MODE` | 勿设为 `mock`，否则仍是旧 Authoring 页 |
| `PRODUCT_PUBLIC_ORIGINS` | 产品 API 容器环境变量，默认允许 `https://studio.shuxueshuo.com` |
| Next `/pages/api/product` 代理 | 仍仅本机开发用；域名流量由 Nginx 直反代 API |

## 常用命令

```bash
docker ps --filter name=shuxueshuo-studio
docker logs -f shuxueshuo-studio
docker restart shuxueshuo-studio
ss -lntp | grep -E ':3000|:8000'
curl -sS http://127.0.0.1:8000/api/product/v1/health
curl -sSI https://studio.shuxueshuo.com/ | head
```

## 排错

- 仍是旧页面：未替换 `shuxueshuo-studio` 镜像，或容器带了 `WORKSPACE_MODE=mock`
- API 403 `access.origin_rejected`：确认 API 镜像/compose 含 `PRODUCT_PUBLIC_ORIGINS`，且 Nginx 转发了 `Origin`
- API 403 `access.loopback_only`：确认 Nginx `proxy_set_header Host 127.0.0.1`
- WS 连到 `127.0.0.1:8000`：镜像构建时未传入 `NEXT_PUBLIC_PRODUCT_WS_ORIGIN`，需重建前端镜像
