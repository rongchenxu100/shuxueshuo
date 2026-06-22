# Studio 创作工作台部署与维护

本文档用于维护 `frontend/` 下的 Next.js Studio 创作工作台。当前实现仍使用 mock API 与内存状态，适合产品评审和并行开发验证；后续接入真实后台 API 后，域名和容器维护方式可以继续沿用。

## 服务器约定

示例路径：

```bash
/home/ronghao/code/shuxueshuo/frontend
```

示例容器名与镜像名：

```bash
CONTAINER_NAME=shuxueshuo-studio
IMAGE_NAME=shuxueshuo-studio:latest
APP_PORT=3000
```

如果服务器上已有其他服务占用 3000，可把宿主机端口换成其他端口，例如 `-p 3001:3000`。

## 首次构建与启动

进入前端目录：

```bash
cd /home/ronghao/code/shuxueshuo/frontend
```

构建镜像：

```bash
docker build -t shuxueshuo-studio:latest .
```

启动容器：

```bash
docker run -d \
  --name shuxueshuo-studio \
  --restart unless-stopped \
  -p 3000:3000 \
  shuxueshuo-studio:latest
```

本机验证：

```bash
curl -I http://127.0.0.1:3000
```

浏览器访问：

```text
http://服务器IP:3000
```

正式访问建议使用：

```text
https://studio.shuxueshuo.com
```

## 日常更新

拉取代码后重新构建并替换容器：

```bash
cd /home/ronghao/code/shuxueshuo/frontend

docker build -t shuxueshuo-studio:latest .
docker rm -f shuxueshuo-studio

docker run -d \
  --name shuxueshuo-studio \
  --restart unless-stopped \
  -p 3000:3000 \
  shuxueshuo-studio:latest
```

如果希望保留旧镜像作为回滚点，可以先打版本 tag：

```bash
docker tag shuxueshuo-studio:latest shuxueshuo-studio:$(date +%Y%m%d-%H%M)
```

## 常用维护命令

查看容器状态：

```bash
docker ps --filter name=shuxueshuo-studio
```

查看日志：

```bash
docker logs -f shuxueshuo-studio
```

重启：

```bash
docker restart shuxueshuo-studio
```

停止：

```bash
docker stop shuxueshuo-studio
```

删除容器：

```bash
docker rm -f shuxueshuo-studio
```

清理悬空镜像：

```bash
docker image prune
```

## Nginx 反代

如果需要通过域名访问，例如 `studio.shuxueshuo.com`，建议只让 Nginx 暴露 80/443，容器端口只监听本机或内网。

仓库内已提供模板：[nginx/studio.shuxueshuo.com.conf](nginx/studio.shuxueshuo.com.conf)。

应用模板：

```bash
sudo cp /home/ronghao/code/shuxueshuo/deploy/nginx/studio.shuxueshuo.com.conf /etc/nginx/conf.d/studio.shuxueshuo.com.conf
sudo nginx -t
sudo systemctl reload nginx
```

证书路径按模板约定为：

```text
/home/ronghao/cert/studio-shuxueshuo/studio.shuxueshuo.com.pem
/home/ronghao/cert/studio-shuxueshuo/studio.shuxueshuo.com.key
```

## 防火墙

如果临时直连 `服务器IP:3000`，需要开放端口：

```bash
sudo firewall-cmd --permanent --add-port=3000/tcp
sudo firewall-cmd --reload
```

如果已经用 Nginx 反代，通常只需要对公网开放 80/443，不建议长期暴露 3000。

## 当前实现限制

- `frontend/fixtures` 会被打进镜像，当前 mock API 运行时读取这些 fixture。
- 新建题目、注释、tutor session 等状态主要是 mock 内存状态；容器重启后会清空。
- 当前 mock mutation 不写回 `fixtures`，刷新页面会回到初始 fixture 数据。
- 接入真实后台 API 后，应保留 `studio.shuxueshuo.com` 作为创作后台入口，替换 API 实现而不是更换域名。

## 排错

构建失败时先确认 Docker 版本与网络：

```bash
docker version
docker build --no-cache -t shuxueshuo-studio:latest .
```

容器启动后访问失败：

```bash
docker logs --tail=200 shuxueshuo-studio
docker exec -it shuxueshuo-studio sh
```

容器内检查 Node：

```bash
node -v
```

宿主机检查端口：

```bash
ss -lntp | grep 3000
```
