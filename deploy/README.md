# 部署

服务器上的仓库路径：**`/home/ronghao/code/shuxueshuo`**。站点根目录：**`/home/ronghao/code/shuxueshuo/site`**。API 工程目录：**`/home/ronghao/code/shuxueshuo/server`**（FastAPI + uv，提供微信 JS-SDK 签名等 **`/api/`**）。

当前约定：**域名 A 记录直连 ECS**，HTTPS 在 **本机 Nginx** 终结（不经 CLB）。**静态页面由 Nginx 直出**；**`/api/`** 反代到本机 **`127.0.0.1:8000`**（Uvicorn），**勿对公网放行 8000 端口**。

更细的 CentOS 7、故障排查与接口说明见：[server/README.md](../server/README.md)。

---

## 一次开通：安装 uv 与 Python 3.11（业务用户 `ronghao`，首次部署执行）

若服务器尚未安装 **uv**（CentOS 7 等）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# 重新登录 SSH，或执行：
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

首次进入 **`server`** 目录安装依赖并准备解释器：

```bash
cd /home/ronghao/code/shuxueshuo/server
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.11
uv sync --frozen
```

---

## API 环境变量与 systemd

1. **配置密钥**（勿提交仓库）：

   ```bash
   cd /home/ronghao/code/shuxueshuo/server
   cp .env.example .env
   chmod 600 .env
   vi .env   # WECHAT_MP_APP_ID、WECHAT_MP_APP_SECRET、PUBLIC_SITE_ORIGIN（与浏览器 https 根一致，无尾部 /）
   ```

2. **本机试跑（可选）**：

   ```bash
   cd /home/ronghao/code/shuxueshuo/server
   export PATH="$HOME/.local/bin:$PATH"
   set -a && source .env && set +a
   uv run uvicorn shuxueshuo_server.main:app --host 127.0.0.1 --port 8000
   ```

   另开终端：`curl -sS http://127.0.0.1:8000/api/health`，应返回 `{"status":"ok"}`。按 `Ctrl+C` 结束。

3. **systemd 常驻**（root；将 **`ronghao`** / 路径换成你机上的实际用户与 `uv` 路径，`which uv` 一般在 **`/home/ronghao/.local/bin/uv`**）：

   **这一段怎么执行**：下面 **`sudo tee … <<'EOF'` 到独占一行的 `EOF`** 是一条命令（heredoc）：会把中间多行写入 **`/etc/systemd/system/shuxueshuo-api.service`**（不存在则创建，存在则覆盖）。后面的 **`systemctl daemon-reload` / `enable` / `start`** 是随后依次执行的几条命令；可以整块复制进 root 终端一次性粘贴运行。

   ```bash
   sudo tee /etc/systemd/system/shuxueshuo-api.service >/dev/null <<'EOF'
   [Unit]
   Description=数学说 WeChat JS-SDK API (FastAPI)
   After=network.target

   [Service]
   Type=simple
   User=ronghao
   Group=ronghao
   WorkingDirectory=/home/ronghao/code/shuxueshuo/server
   Environment="PATH=/home/ronghao/.local/bin:/usr/local/bin:/usr/bin"
   EnvironmentFile=/home/ronghao/code/shuxueshuo/server/.env
   ExecStart=/home/ronghao/.local/bin/uv run uvicorn shuxueshuo_server.main:app --host 127.0.0.1 --port 8000
   Restart=on-failure
   RestartSec=3

   [Install]
   WantedBy=multi-user.target
   EOF

   sudo systemctl daemon-reload
   sudo systemctl enable shuxueshuo-api
   sudo systemctl start shuxueshuo-api
   sudo systemctl status shuxueshuo-api
   ```

   排错：`journalctl -u shuxueshuo-api -f`。

4. **SELinux**（若 `getenforce` 为 Enforcing，Nginx 反代连后端被拒时）：

   ```bash
   sudo setsebool -P httpd_can_network_connect 1
   ```

---

## Nginx

1. 复制配置（模板已包含 **`location /api/`** → `127.0.0.1:8000`，与静态站点同文件）：

   ```bash
   sudo cp /home/ronghao/code/shuxueshuo/deploy/nginx/shuxueshuo.conf /etc/nginx/conf.d/shuxueshuo.conf
   ```

2. **证书路径**（已与模板一致）：

   ```text
   /home/ronghao/cert/shuxueshuo/shuxueshuo.com.pem   # 证书链 PEM
   /home/ronghao/cert/shuxueshuo/shuxueshuo.com.key   # 私钥
   ```

   Nginx 一般以非 root 用户（如 `nginx`）读证书，需保证能遍历并读取该路径。若 `nginx -t` 报 **Permission denied**，可为目录赋予执行权限、证书只读，例如：

   ```bash
   chmod 755 /home/ronghao /home/ronghao/cert /home/ronghao/cert/shuxueshuo
   chmod 644 /home/ronghao/cert/shuxueshuo/shuxueshuo.com.pem
   chmod 640 /home/ronghao/cert/shuxueshuo/shuxueshuo.com.key
   sudo chgrp nginx /home/ronghao/cert/shuxueshuo/shuxueshuo.com.key   # 若系统里 nginx 用户组名为 nginx
   ```

   （具体用户/组名以 `ps aux | grep nginx` 或发行版文档为准；也可改用 `root` 可读副本放到 `/etc/nginx/ssl/`。）

3. 若路径不同，编辑 `/etc/nginx/conf.d/shuxueshuo.conf` 中的 `ssl_certificate` / `ssl_certificate_key`、`root`。

4. **先确保 API 已启动**（否则浏览器访问带 `/api/` 的页面会 502），再开放防火墙与安全组 **80、443** 入站；校验并重载：

   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

5. 对外验证：

   ```bash
   curl -sS https://shuxueshuo.com/api/health
   ```

6. DNS：**`shuxueshuo.com` / `www`** 的 **A 记录** 指向该 ECS 公网 IP（不再指向 CLB）。

模板文件：[nginx/shuxueshuo.conf](nginx/shuxueshuo.conf)。**80 端口**：直连 HTTP 会 301 到 HTTPS；若使用 **仅 HTTP 回源** 的 CDN（如 Cloudflare「灵活」模式）且已带 `X-Forwarded-Proto: https`，则 **不再跳转** 并在 80 上直出站点，避免「重定向过多」。若源站可对外提供 443，更建议把 CDN 改为 **完全/完全(严格)**，让回源也走 HTTPS。

---

## 若出现「重定向次数过多」

- 已改模板为上述 `X-Forwarded-Proto` 判断；请更新服务器上的 `shuxueshuo.conf` 后 `nginx -t` 并重载。
- 若使用 Cloudflare：将 SSL 模式从「灵活」改为 **完全** 或 **完全(严格)**，或临时关闭「始终使用 HTTPS」做对比测试。
- 仅直连 ECS、无 CDN 时：仍循环则检查是否另有全局规则把 `https` 再指回 `http`（其它 `conf.d`、WAF 等）。

---

## 更新站点与 API

**静态文件**：在服务器执行 `git pull`，或从本机 rsync `site/`：

```bash
cd /home/ronghao/code/shuxueshuo && git pull
```

```bash
rsync -avz --delete ./site/ ronghao@<ECS IP>:/home/ronghao/code/shuxueshuo/site/
```

**API 依赖变更时**（`server/pyproject.toml` 或 `uv.lock` 有更新）：

```bash
cd /home/ronghao/code/shuxueshuo/server
export PATH="$HOME/.local/bin:$PATH"
uv sync --frozen
sudo systemctl restart shuxueshuo-api
```

**仅静态 HTML/CSS/JS 变更**：一般只需覆盖 `site/`；微信分享脚本若仍指向同源 **`/api/wechat/jssdk-config`**，无需重启 API。

若 **Nginx 配置**有更新：

```bash
sudo cp /home/ronghao/code/shuxueshuo/deploy/nginx/shuxueshuo.conf /etc/nginx/conf.d/shuxueshuo.conf
sudo nginx -t && sudo systemctl reload nginx
```

---

## 去掉 CLB、改为域名直连 ECS（HTTPS 在本机 Nginx）

此前 **证书在 CLB、回源只打 80** 时，ECS 上的 **`listen 443`** 往往接不到公网流量。取消 CLB 后，浏览器会 **直连 ECS 的 443**，必须在 **本机** 配好证书与各域名的 **`server { listen 443 ssl; }`**。

### 1. DNS

- 各域名（如 `shuxueshuo.com`、`www`、`api.xiaozhongshuo.com`、主站 `xiaozhongshuo.com` 等）的 **A 记录** 指向 **ECS 公网 IP**（不再指向 CLB VIP）。
- 生效时间取决于 TTL，变更后可用 `dig +short <域名>` 核对。

### 2. 安全组 / 防火墙

- 入方向放行 **TCP 80、443**（以及 SSH 22）；**勿**对公网放行 **8000**（API 仅本机）。
- 若本机 **`firewalld`/`iptables`** 有策略，同步放行 80/443。

### 3. TLS 证书放在 ECS

为每个需要在 HTTPS 上服务的域名准备 PEM：

- **Let’s Encrypt**（如 `certbot certonly --nginx` / **DNS 验证**），或  
- 继续把控制台下载的证书放到固定路径（与 Nginx 里 `ssl_certificate`、`ssl_certificate_key` 一致）。

仓库示例：

- 数学说：[deploy/nginx/shuxueshuo.conf](nginx/shuxueshuo.conf) 使用 **`/home/ronghao/cert/shuxueshuo/`**。  
- API：[deploy/nginx/api.xiaozhongshuo.com.conf](nginx/api.xiaozhongshuo.com.conf) 使用 **`/etc/nginx/cert/`** 下 PEM（可按你实际路径改）。

取消 CLB 后，**务必确认证书域名与浏览器访问域名一致**，且 **未过期**。

### 4. Nginx：每个站点都要有「对外 HTTPS」

- **数学说**：模板已包含 **`listen 443 ssl`** + `root` + **`location /api/`** 反代，直连场景下会真正用到这一段。  
- **API**：[`api.xiaozhongshuo.com.conf`](nginx/api.xiaozhongshuo.com.conf) 已含 **`listen 443`**；直连后 **`listen 80`** 仍可保留（可选做 **301 跳转 HTTPS**）。  
- **主站 Laravel**（`xiaozhongshuo.com`）：当前 [`deploy/nginx/nginx.conf`](nginx/nginx.conf) 里 **仅有 `listen 80`**。若主站也要 **https://xiaozhongshuo.com**，需要 **新增** 带 `ssl_certificate` 的 **`listen 443`** `server {}`（或拆到 `conf.d`），结构可与 API、数学说类似。

校验并重载：

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### 5. 应用层（Laravel / 其它）

- **去掉 CLB 后**，多数请求 **`X-Forwarded-Proto` 可能不再有**（客户端直连 Nginx）。已在 PHP `fastcgi_param HTTP_X_FORWARDED_PROTO ...` 时，空值表示 HTTP；若全站强制 HTTPS，通常 **`$scheme` 已为 https**，一般无妨。  
- 若曾在 `.env` 里为 CLB 配 **`TRUSTED_PROXIES`**，直连后可收紧或改为信任本机 / 保留将来 CDN 网段。

### 6. 与「经 CLB」的差异小结

| 项目 | 经 CLB（回源 80） | 直连 ECS |
|------|-------------------|----------|
| TLS | CLB 终结 | **ECS Nginx 终结** |
| ECS **`listen 443`** | 可能闲置 | **必须使用且证书有效** |
| **`listen 80` 上的 API** | 强烈建议独立 `server_name`（已写入 api.conf） | 同上；可加 **301 → HTTPS** |

