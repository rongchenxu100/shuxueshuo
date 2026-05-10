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
