# 部署

服务器上的仓库路径：**`/home/ronghao/code/shuxueshuo`**。站点根目录：**`/home/ronghao/code/shuxueshuo/site`**。

当前约定：**域名 A 记录直连 ECS**，HTTPS 在 **本机 Nginx** 终结（不经 CLB）。

## Nginx

1. 复制配置：

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

3. 若路径不同，编辑 `/etc/nginx/conf.d/shuxueshuo.conf` 中的 `ssl_certificate` / `ssl_certificate_key`。

4. 开放防火墙与安全组 **80、443** 入站；校验并重载：

   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

5. DNS：**`shuxueshuo.com` / `www`** 的 **A 记录** 指向该 ECS 公网 IP（不再指向 CLB）。

模板文件：[nginx/shuxueshuo.conf](nginx/shuxueshuo.conf)。**80 端口**：直连 HTTP 会 301 到 HTTPS；若使用 **仅 HTTP 回源** 的 CDN（如 Cloudflare「灵活」模式）且已带 `X-Forwarded-Proto: https`，则 **不再跳转** 并在 80 上直出站点，避免「重定向过多」。若源站可对外提供 443，更建议把 CDN 改为 **完全/完全(严格)**，让回源也走 HTTPS。

## 若出现「重定向次数过多」

- 已改模板为上述 `X-Forwarded-Proto` 判断；请更新服务器上的 `shuxueshuo.conf` 后 `nginx -t` 并重载。
- 若使用 Cloudflare：将 SSL 模式从「灵活」改为 **完全** 或 **完全(严格)**，或临时关闭「始终使用 HTTPS」做对比测试。
- 仅直连 ECS、无 CDN 时：仍循环则检查是否另有全局规则把 `https` 再指回 `http`（其它 `conf.d`、WAF 等）。

## 更新站点文件

在服务器执行 `git pull`，或从本机 rsync `site/`：

```bash
rsync -avz --delete ./site/ ronghao@<ECS IP>:/home/ronghao/code/shuxueshuo/site/
```
