# 服务器发布手册

面向当前生产形态：**产品 API/Worker/publisher 用发布包镜像**；**Studio 前端单独打 Docker 镜像**；**Nginx / 静态站 / 部分脚本仍可用服务器 `git pull`**。

> **公开仓库注意**：勿把真实 ECS IP、SSH 账号口令、数据库/broker/模型密钥写入本文或提交到 Git。下文用占位符；本机可先 `export DEPLOY_SSH='user@your-ecs-host'`。

相关文档：

- 产品库与 `services-*`：[product/README.md](product/README.md)
- Studio 前端镜像：[frontend-studio-workbench.md](frontend-studio-workbench.md)
- OCR：[ocr/README.md](ocr/README.md)
- 主站 Nginx / 静态页：[README.md](README.md)

## 什么时候要打包，什么时候 pull 就行

| 改动 | 发布方式 |
| --- | --- |
| `server/shuxueshuo_server/product/**`、`deploy/product/**`（Compose/管理脚本） | **本机构建发布包 → 上传 → `services-start` 或 `deploy`** |
| `frontend/**`（Studio 工作台） | **本机构建 `shuxueshuo-studio` → 上传 → `docker load` 换容器** |
| `deploy/nginx/**`、主站静态 `site/**`、仓库说明 | 服务器 **`git pull`**，必要时 `nginx -t && reload` |
| OCR wrapper / `deploy/ocr/**`（镜像未变） | 服务器 **`git pull`** 后按 OCR 文档处理 |
| 仅改 `server/.env` 模型密钥 | 改宿主机文件（**勿提交**）；**重启** api/worker/publisher 容器即可，无需新发布包 |

以前「服务器 `git pull` 就发布」适合宿主机直接跑 `uvicorn`。现在产品与 Studio 跑在 **固定 digest 的镜像**里，业务代码变更必须打进镜像再换容器。

## 环境约定（占位符）

本机发布前设置一次（勿写入仓库）：

```bash
export DEPLOY_SSH='<user>@<ecs-host>'   # 例：deploy@ecs.example.internal
# 可选：服务器上的仓库与发布目录若与默认不同再覆盖
# export REMOTE_REPO='$HOME/code/shuxueshuo'
# export REMOTE_RELEASES='$HOME/releases'
```

| 项 | 值 |
| --- | --- |
| SSH | `$DEPLOY_SSH`（本机环境变量，不入库） |
| 仓库（服务器） | `$HOME/code/shuxueshuo` |
| 产品数据根 | `/srv/shuxueshuo` |
| 发布包目录 | `$HOME/releases/` |
| 产品 API | `127.0.0.1:8000`（容器，仅本机） |
| Studio | `127.0.0.1:3000` → `https://studio.shuxueshuo.com` |
| 主站 | `https://shuxueshuo.com`（静态 + `/api/` → `:8000`） |
| OCR 镜像 | `shuxueshuo-ocr:3.3.0` |
| 模型密钥 | 服务器 `$HOME/code/shuxueshuo/server/.env`（Git 忽略，勿提交） |

发布包要求：**干净 Git 工作树**（先 commit/push）。构建机需 Docker Desktop / buildx。

---

## A. 发布产品 API / Worker / publisher

### A1. 本机构建

在仓库根目录执行：

```bash
cd /path/to/shuxueshuo   # 本地克隆根目录
git status               # 必须干净
git pull

RELEASE_ID=p2-app-$(date +%Y%m%d%H%M)
OUT=/tmp/shuxueshuo-release-${RELEASE_ID}-amd64
rm -rf "$OUT"

./deploy/product/build-release.sh \
  --release "$RELEASE_ID" \
  --platform linux/amd64 \
  --output "$OUT"

echo "发布包：$OUT"
echo "RELEASE_ID=$RELEASE_ID"
```

### A2. 上传服务器

```bash
: "${DEPLOY_SSH:?请先 export DEPLOY_SSH=user@ecs-host}"

ssh "$DEPLOY_SSH" 'mkdir -p "$HOME/releases"'
rsync -avz --progress \
  "$OUT/" \
  "${DEPLOY_SSH}:releases/shuxueshuo-release-${RELEASE_ID}-amd64/"
```

### A3. 服务器切换并启动

首次装库用 `install`；**已有 `/srv/shuxueshuo` 只换应用镜像**用下面 `services-*`。  
库结构/迁移变更再用发布包内的 `server/deploy.sh`（见 [product/README.md](product/README.md)）。

```bash
RELEASE=$HOME/releases/shuxueshuo-release-<RELEASE_ID>-amd64

grep '^API_PORT=' /srv/shuxueshuo/config/runtime.env
# 生产应为 API_PORT='8000'

"$RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo \
  --release "$RELEASE" services-stop

"$RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo \
  --release "$RELEASE" services-start

"$RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo \
  --release "$RELEASE" services-doctor

curl -sS http://127.0.0.1:8000/api/product/v1/health
curl -sS http://127.0.0.1:8000/api/health
docker ps --filter name=shuxueshuo-product-server
```

期望 doctor 含 `"broker": true`、`"api": true`。

日常启停（记得带当前 `--release`，或保证 `release-path` 已指向该包）：

```bash
RELEASE=$(cat /srv/shuxueshuo/config/release-path)
"$RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo --release "$RELEASE" services-status
"$RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo --release "$RELEASE" services-stop
"$RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo --release "$RELEASE" services-start
```

---

## B. 发布 Studio 前端（studio.shuxueshuo.com）

与产品发布包 **独立**。只改 `frontend/` 时不必打产品包。

### B1. 本机构建

```bash
: "${DEPLOY_SSH:?请先 export DEPLOY_SSH=user@ecs-host}"
cd /path/to/shuxueshuo/frontend
git -C .. pull

docker buildx build \
  --platform linux/amd64 \
  --build-arg NEXT_PUBLIC_PRODUCT_WS_ORIGIN=wss://studio.shuxueshuo.com \
  -t shuxueshuo-studio:latest \
  --load \
  .

docker save shuxueshuo-studio:latest | gzip > /tmp/shuxueshuo-studio.tar.gz
scp /tmp/shuxueshuo-studio.tar.gz "${DEPLOY_SSH}:shuxueshuo-studio.tar.gz"
```

**必须**带 `NEXT_PUBLIC_PRODUCT_WS_ORIGIN`（构建期内联）。**不要**设 `WORKSPACE_MODE=mock`。

### B2. 服务器换容器

```bash
docker load < "$HOME/shuxueshuo-studio.tar.gz"
docker rm -f shuxueshuo-studio 2>/dev/null || true
docker run -d \
  --name shuxueshuo-studio \
  --restart unless-stopped \
  -p 127.0.0.1:3000:3000 \
  shuxueshuo-studio:latest

curl -sSI http://127.0.0.1:3000 | head
curl -sSI https://studio.shuxueshuo.com/ | head
```

---

## C. 只更新 Nginx / 仓库配置（git pull）

```bash
cd "$HOME/code/shuxueshuo"
git pull

sudo cp deploy/nginx/studio.shuxueshuo.com.conf \
  /etc/nginx/conf.d/studio.shuxueshuo.com.conf
# 主站模板如有变更：
# sudo cp deploy/nginx/shuxueshuo.conf /etc/nginx/conf.d/shuxueshuo.conf

sudo nginx -t && sudo systemctl reload nginx
```

Studio Nginx：`/` → `:3000`；`/api/product/` → `:8000`（`Host 127.0.0.1`）。

---

## D. 一键对照：一次完整发布（产品 + Studio）

本机：

```bash
: "${DEPLOY_SSH:?请先 export DEPLOY_SSH=user@ecs-host}"
cd /path/to/shuxueshuo
git pull
# 工作树干净后：
RELEASE_ID=p2-app-$(date +%Y%m%d%H%M)
OUT=/tmp/shuxueshuo-release-${RELEASE_ID}-amd64
./deploy/product/build-release.sh --release "$RELEASE_ID" --platform linux/amd64 --output "$OUT"
ssh "$DEPLOY_SSH" 'mkdir -p "$HOME/releases"'
rsync -avz --progress "$OUT/" \
  "${DEPLOY_SSH}:releases/shuxueshuo-release-${RELEASE_ID}-amd64/"

cd frontend
docker buildx build --platform linux/amd64 \
  --build-arg NEXT_PUBLIC_PRODUCT_WS_ORIGIN=wss://studio.shuxueshuo.com \
  -t shuxueshuo-studio:latest --load .
docker save shuxueshuo-studio:latest | gzip > /tmp/shuxueshuo-studio.tar.gz
scp /tmp/shuxueshuo-studio.tar.gz "${DEPLOY_SSH}:shuxueshuo-studio.tar.gz"
echo "服务器 RELEASE=\$HOME/releases/shuxueshuo-release-${RELEASE_ID}-amd64"
```

服务器：

```bash
RELEASE=$HOME/releases/shuxueshuo-release-<RELEASE_ID>-amd64

"$RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo \
  --release "$RELEASE" services-stop
"$RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo \
  --release "$RELEASE" services-start
"$RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo \
  --release "$RELEASE" services-doctor

docker load < "$HOME/shuxueshuo-studio.tar.gz"
docker rm -f shuxueshuo-studio
docker run -d --name shuxueshuo-studio --restart unless-stopped \
  -p 127.0.0.1:3000:3000 shuxueshuo-studio:latest

cd "$HOME/code/shuxueshuo" && git pull
sudo cp deploy/nginx/studio.shuxueshuo.com.conf /etc/nginx/conf.d/studio.shuxueshuo.com.conf
sudo nginx -t && sudo systemctl reload nginx

curl -sS http://127.0.0.1:8000/api/product/v1/health
curl -sSI https://studio.shuxueshuo.com/ | head
```

---

## 日志在哪

| 组件 | 怎么看 |
| --- | --- |
| 浏览器 | DevTools → Console / Network（本报错先出现在 Console，未到服务器） |
| Studio 前端容器 | `docker logs --tail 100 -f shuxueshuo-studio` |
| 产品 API | `docker logs --tail 100 -f shuxueshuo-product-server-api-1` |
| Worker | `docker logs --tail 100 -f shuxueshuo-product-server-worker-1` |
| Publisher | `docker logs --tail 100 -f shuxueshuo-product-server-publisher-1` |
| RabbitMQ / Postgres | `docker logs --tail 50 shuxueshuo-product-server-rabbitmq-1` 等 |
| 产品实例日志目录 | `/srv/shuxueshuo/logs/`（管理操作等） |
| Nginx | 常见 `/var/log/nginx/error.log`、`access.log` |

上传类问题建议顺序：浏览器 Console → Network 里 `/api/product/` 与 WS → `api` / `worker` 的 `docker logs`。

## 验收清单

- [ ] `curl http://127.0.0.1:8000/api/product/v1/health` → `status/ok`
- [ ] `curl http://127.0.0.1:8000/api/health` → 主站微信 API 进程存活
- [ ] `services-doctor`：`broker: true`，`api: true`
- [ ] `https://studio.shuxueshuo.com/` 为新产品工作台（非旧 mock Authoring）
- [ ] 浏览器可上传并看到构建进度（API + WS）
- [ ] `docker ps`：postgres / rabbitmq / api / worker / publisher / `shuxueshuo-studio` 均 Up
- [ ] 无旧 `shuxueshuo-api` systemd 占用 8000

## 回滚

- **产品**：`services-stop` 后改用上一版 `RELEASE` 目录再 `services-start`（镜像仍在本机则无需重传）。
- **Studio**：保留旧 tag（如 `shuxueshuo-studio:YYYYMMDD-HHMM`），`docker run` 换回旧镜像。
- **Nginx**：从 git 历史恢复 conf 后 reload。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `发布要求干净工作树` | 先 commit/stash 未提交改动 |
| `address already in use :8000` | 停旧 `shuxueshuo-api`；`API_PORT` 与占用进程对齐 |
| doctor `api: false` / Origin 403 | 确认发布包含 `PRODUCT_PUBLIC_ORIGINS`；Nginx `Host 127.0.0.1` |
| Studio 仍是旧页 | 未换 `shuxueshuo-studio` 镜像，或设了 `WORKSPACE_MODE=mock` |
| `WebSocket 地址必须是本机服务` | 旧前端把 WS 主机限制为 localhost；换含「同站 wss」修复的 studio 镜像 |
| WS 连不上 / 握手失败 | 查 Nginx `/api/product/` 与 `docker logs` api 容器；确认 `Host 127.0.0.1` |
| `请使用目标发布包 scripts/...` | 命令加 `--release` 指向正在用的包路径 |
| 服务器无 `python3` | 改 `runtime.env` 用 `sed`，不要用 python 脚本 |
