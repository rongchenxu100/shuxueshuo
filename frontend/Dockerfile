# 这个 Dockerfile 用来部署 frontend Studio 创作工作台。
#
# 设计目标：
# - 使用 Node 20，满足 Next.js 16 的运行要求。
# - 使用多阶段构建，最终镜像只保留生产运行所需文件。
# - 使用 Next.js standalone 输出，避免在运行镜像里携带完整源码与 node_modules。
# - 显式复制 fixtures，因为当前临时 mock API 会在运行时读取 frontend/fixtures。
#
# 构建命令：
#   docker build -t shuxueshuo-studio:latest .
#
# Mac 本地构建并上传 CentOS 服务器时，建议显式构建 amd64：
#   docker buildx build --platform linux/amd64 -t shuxueshuo-studio:latest --load .
#
# 运行命令：
#   docker run -d --name shuxueshuo-studio --restart unless-stopped -p 3000:3000 shuxueshuo-studio:latest

# deps 阶段只安装依赖。
# 单独拆出这一层后，只要 package.json / package-lock.json 不变，
# 后续代码改动重新 build 时可以复用 npm ci 的缓存层。
FROM node:20-bookworm-slim AS deps

WORKDIR /app

# 只复制依赖清单，避免源码变化导致依赖层缓存失效。
COPY package.json package-lock.json ./

# npm ci 会严格按 package-lock.json 安装，适合 CI / Docker 构建。
RUN npm ci

# builder 阶段负责编译 Next.js 应用。
FROM node:20-bookworm-slim AS builder

WORKDIR /app

# 关闭 Next.js 遥测，减少构建和运行环境中的额外网络行为。
ENV NEXT_TELEMETRY_DISABLED=1

# 复用 deps 阶段安装好的依赖，再复制完整 frontend 源码。
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# next.config.ts 中设置了 output: "standalone"。
# 构建完成后会生成 .next/standalone，其中包含生产 server.js 和必要依赖。
RUN npm run build

# runner 阶段是最终生产镜像。
# 这里不再运行 npm install，也不保留完整源码，只复制 standalone 产物。
FROM node:20-bookworm-slim AS runner

WORKDIR /app

# HOSTNAME=0.0.0.0 让 Next server 在容器内监听所有网卡，
# 否则外部端口映射可能无法访问。
ENV HOSTNAME=0.0.0.0
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
ENV PORT=3000

# 创建非 root 用户运行 Node 进程，降低容器内进程权限。
RUN addgroup --system --gid 1001 nodejs \
  && adduser --system --uid 1001 nextjs

# standalone：Next 生产 server 及其最小依赖集合。
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./

# static：Next 生成的静态资源，server.js 会按 .next/static 路径读取。
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

# public：预览 fixture HTML、图片等公开静态资源。
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

# fixtures：当前临时 mock Route Handlers 运行时读取的 JSON 数据。
# 注意：mock mutation 不会写回 fixtures，容器重启或刷新仍回到初始数据。
COPY --from=builder --chown=nextjs:nodejs /app/fixtures ./fixtures

USER nextjs

# 容器内监听端口。实际公网端口由 docker run -p 或 Nginx 反代决定。
EXPOSE 3000

# standalone 输出的入口文件。
CMD ["node", "server.js"]
