# 数学说 API（FastAPI + uv）

提供微信网页 **JS-SDK** 所需的 `wx.config` 签名（`GET /api/wechat/jssdk-config`）。

## 环境变量

复制 `.env.example` 为 `.env` 并填写：

| 变量 | 说明 |
|------|------|
| `WECHAT_MP_APP_ID` | 公众号 AppID |
| `WECHAT_MP_APP_SECRET` | 公众号 AppSecret（勿提交仓库） |
| `PUBLIC_SITE_ORIGIN` | 站点 HTTPS 根，如 `https://www.example.com`，**无**尾部 `/`。前端传的 `url` 必须以此开头 |

公众平台：**设置与开发 → 公众号设置 → 功能设置 → JS 接口安全域名** 填写备案域名（仅域名）。

## 本地开发

```bash
cd server
uv sync
cp .env.example .env   # 编辑填入真实值
uv run uvicorn shuxueshuo_server.main:app --reload --host 127.0.0.1 --port 8000
```

测试：

```bash
curl -sS 'http://127.0.0.1:8000/api/health'
curl -sS --get --data-urlencode 'url=https://shuxueshuo.com/problems/tj/24/foo.html' \
  'http://127.0.0.1:8000/api/wechat/jssdk-config'
```

（将 `url` 换成与你的 `PUBLIC_SITE_ORIGIN` 一致的页面地址。）

## 生产部署（Nginx + systemd）

1. 服务器安装 **uv**，在项目目录执行 `uv sync --frozen`。
2. **Nginx** 在现有静态站点之外增加 API 反代，示例：

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

注意：`proxy_pass` 末尾不要多加 `/`，除非你有意改写路径。

3. **systemd** 示例 `/etc/systemd/system/shuxueshuo-api.service`：

```ini
[Unit]
Description=数学说 WeChat JS-SDK API
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/shuxueshuo/server
EnvironmentFile=/path/to/shuxueshuo/server/.env
ExecStart=/home/deploy/.local/bin/uv run uvicorn shuxueshuo_server.main:app --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

将 `ExecStart` 中的 `uv` 路径改为服务器实际路径（`which uv`）。仅本机监听 `8000`，防火墙不对外开放该端口。

4. **多 worker**：`jsapi_ticket` 缓存在进程内存；多 worker 建议 `workers=1` 或引入 Redis 共享 ticket。

---

## CentOS 7.2 生产部署（服务器未安装 uv）

以下假设：你用 **普通用户**（如 `deploy`）管理代码，用 **root** 安装 systemd / 改 Nginx；站点代码放在 **`/opt/shuxueshuo`**（可按实际修改）。Python 要求 **≥ 3.11**，由 **uv** 自带下载解释器，无需系统自带 3.11。

### 1）系统依赖（root）

```bash
sudo yum install -y curl ca-certificates tar gzip gcc openssl-devel libffi-devel make
```

（若后续 `uv python install` 编译失败，再补 `bzip2-devel xz-devel readline-devel sqlite-devel` 等。）

### 2）安装 uv（deploy 用户，无需 root）

官方安装脚本会把 `uv` 装到 **`$HOME/.local/bin`**：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

重新登录 SSH，或立刻加载 PATH：

```bash
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

若 `command not found`，检查 `~/.bashrc` / `~/.profile` 是否已追加 `export PATH="$HOME/.local/bin:$PATH"`。

### 3）同步代码与依赖

将仓库拷到服务器（**示例**：`git clone`；也可用 `rsync` / SFTP 上传 **`server` 目录及根目录的 `uv.lock`**）。

```bash
cd /opt   # 或你的目录
sudo mkdir -p /opt/shuxueshuo
sudo chown deploy:deploy /opt/shuxueshuo   # 换成你的用户
cd /opt/shuxueshuo
git clone <你的仓库地址> .
cd server
```

安装 **Python 3.11**（由 uv 管理，写到用户缓存目录）并安装依赖：

```bash
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.11
uv sync --frozen
```

### 4）环境变量

```bash
cd /opt/shuxueshuo/server
cp .env.example .env
chmod 600 .env
vi .env   # 填写 WECHAT_MP_APP_ID、WECHAT_MP_APP_SECRET、PUBLIC_SITE_ORIGIN
```

**`PUBLIC_SITE_ORIGIN`** 必须与浏览器访问的 **https 根** 完全一致（含是否 `www`）。

### 5）本机试跑（可选）

```bash
export PATH="$HOME/.local/bin:$PATH"
cd /opt/shuxueshuo/server
set -a && source .env && set +a
uv run uvicorn shuxueshuo_server.main:app --host 127.0.0.1 --port 8000
```

另开终端：

```bash
curl -sS http://127.0.0.1:8000/api/health
```

按 `Ctrl+C` 停掉试跑进程。

### 6）systemd 常驻（root）

CentOS 通常没有 `www-data` 用户，下面用运行服务的用户 **`deploy`**（请改成你实际用户）。  
`ExecStart` 使用 **`uv run`**，路径以 **`which uv`** 为准（一般在 **`/home/deploy/.local/bin/uv`**）。

```bash
sudo tee /etc/systemd/system/shuxueshuo-api.service >/dev/null <<'EOF'
[Unit]
Description=数学说 WeChat JS-SDK API (FastAPI)
After=network.target

[Service]
Type=simple
User=deploy
Group=deploy
WorkingDirectory=/opt/shuxueshuo/server
Environment="PATH=/home/deploy/.local/bin:/usr/local/bin:/usr/bin"
EnvironmentFile=/opt/shuxueshuo/server/.env
ExecStart=/home/deploy/.local/bin/uv run uvicorn shuxueshuo_server.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
```

**务必**把上面三处 **`deploy`**、`/home/deploy/.local/bin/uv`、`WorkingDirectory` / `EnvironmentFile` 改成你的真实路径。

```bash
sudo systemctl daemon-reload
sudo systemctl enable shuxueshuo-api
sudo systemctl start shuxueshuo-api
sudo systemctl status shuxueshuo-api
journalctl -u shuxueshuo-api -f   # 排错
```

### 7）Nginx 反代 `/api/`（root）

在现有 **`server { ... }`**（HTTPS）里加入（或 include `server/nginx-api-snippet.conf` 内容）：

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### 8）防火墙与安全组

- **本机**：`8000` 仅监听 `127.0.0.1`，**不要**对公网放行 `8000`。
- **阿里云安全组**：保持只开放 **80/443**（及 SSH），与计划一致。

### 9）SELinux（若 `getenforce` 为 Enforcing）

Nginx 反代到本机后端若被拒绝，可尝试（按需，以你们安全策略为准）：

```bash
sudo setsebool -P httpd_can_network_connect 1
```

### 10）后续更新代码

```bash
cd /opt/shuxueshuo
git pull
cd server
export PATH="$HOME/.local/bin:$PATH"
uv sync --frozen
sudo systemctl restart shuxueshuo-api
```

---

## 接口契约

- **GET** `/api/wechat/jssdk-config?url=<encodeURIComponent(页面完整URL，不含#)>`
- **200** JSON：`appId`、`timestamp`、`nonceStr`、`signature`
- **400**：`url` 非法或未在白名单前缀下
- **502**：微信接口错误或配置错误
