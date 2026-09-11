# 本地产品服务列表与启动、停止命令

适用环境：P2 本地产品实例 `local`，macOS 原生运行。以下服务在 2026-09-11 核查时均已启动；实时状态以 `services-status` 为准。服务器 Docker 部署另行安排。

所有命令从仓库根目录执行：

```bash
cd /Users/haorong/projects/code/shuxueshuo
```

## 常驻服务

| 服务 | 本地入口／端口 | 职责 | 启动／停止命令 | 脚本或实现位置 |
| --- | --- | --- | --- | --- |
| PostgreSQL 17.10 | `127.0.0.1:5432`，数据库 `product` | 保存用户、题目、修订、构建、执行权、产物索引、事件及调用审计，是业务状态的权威来源 | 启动：`./deploy/product/manage.sh --mode local db-start`；停止：`./deploy/product/manage.sh --mode local db-stop`。整套启动也会自动启动数据库 | [统一管理入口](../deploy/product/manage.sh)、[原生数据库生命周期](../server/shuxueshuo_server/product/admin/native.py) |
| RabbitMQ 4.3.2 | `127.0.0.1:5672`；节点内部通信端口 `25672` | 持久保存待消费消息，并向 Worker 投递；不保存题意或最终网页。管理网页插件未启用 | 随整套启动：`./deploy/product/manage.sh --mode local services-start`；随整套停止：`./deploy/product/manage.sh --mode local services-stop` | [原生 RabbitMQ 管理](../server/shuxueshuo_server/product/admin/broker.py)、[服务生命周期](../server/shuxueshuo_server/product/admin/runtime.py) |
| Celery Worker 5.6.3 | 无 HTTP 入口；连接 RabbitMQ 和 PostgreSQL | 消费任务、获取执行权、启动构建子进程、续租、处理取消和异常退出。当前最多同时执行 **1 个构建** | 随整套启动／停止：`services-start`／`services-stop`，完整命令同上 | [Worker 实现](../server/shuxueshuo_server/product/transport.py)、[服务生命周期](../server/shuxueshuo_server/product/admin/runtime.py) |
| Publisher／恢复扫描进程 | 无 HTTP 入口；连接 PostgreSQL 和 RabbitMQ | 将数据库 outbox 消息可靠发布到 RabbitMQ；每约 15 秒扫描过期租约，安排恢复消息 | 随整套启动／停止：`services-start`／`services-stop`，完整命令同上 | [发布与恢复实现](../server/shuxueshuo_server/product/transport.py)、[服务生命周期](../server/shuxueshuo_server/product/admin/runtime.py) |
| FastAPI／Uvicorn | `http://127.0.0.1:8000/api/product/v1`；WebSocket：`ws://127.0.0.1:8000/api/product/v1/ws` | 提供上传、题目、构建、修订、重建、取消、审查、受控产物访问及实时事件接口 | 随整套启动／停止：`services-start`／`services-stop`，完整命令同上 | [API 入口](../server/shuxueshuo_server/main.py)、[产品接口](../server/shuxueshuo_server/product/api.py)、[服务生命周期](../server/shuxueshuo_server/product/admin/runtime.py) |
| Next.js 前端 | [Review](http://127.0.0.1:3000/review/runs) | 上传、进度、解析网页及审查材料界面；代理 HTTP 请求。当前以 `next dev` 开发模式运行，支持热更新 | 随整套启动／停止：`services-start`／`services-stop`，完整命令同上 | [前端 npm scripts](../frontend/package.json)、[产品 Review](../frontend/app/review/runs/product-ui.tsx)、[服务生命周期](../server/shuxueshuo_server/product/admin/runtime.py) |

除 PostgreSQL 外，当前 CLI 没有按服务名分别 start/stop 的子命令。RabbitMQ、Worker、publisher、API 和前端由统一生命周期管理，启动时注入实例配置、记录 PID 和源码版本，停止时排空任务。不要另起默认 RabbitMQ 节点或旧 Review Worker。

## 常用命令

```bash
# 启动整套：PostgreSQL、RabbitMQ、Worker、publisher、API、前端
./deploy/product/manage.sh --mode local services-start

# 查看服务运行状态（包括数据库、RabbitMQ及四个应用进程）
./deploy/product/manage.sh --mode local services-status

# 完整自检：数据库、登记产物、OCR依赖、队列、进程版本和心跳
# 此命令不调用付费模型
./deploy/product/manage.sh --mode local services-doctor

# 停止应用服务和 RabbitMQ；PostgreSQL 保持运行
./deploy/product/manage.sh --mode local services-stop

# 如果需要全部停止，在 services-stop 成功之后停止数据库
./deploy/product/manage.sh --mode local db-stop
```

重启整套应用：先成功执行 `services-stop`，再执行 `services-start`。停止时先拒绝新写入，最多等待约 30 秒排空排队／执行中的任务；超时会报错并保留服务和任务，需要等待任务结束或在 Review 中明确取消后重试。停止服务不删除数据。

重复启动复用已有进程；代码或资源版本变化而旧服务仍在运行时，启动器会要求先停后启。本机不安装开机启动项，不使用 `brew services` 接管默认集群。

## 首次安装入口

安装与日常启停分开。已有本地实例正常运行时，无须重复安装。

| 安装项 | 命令 | 脚本 |
| --- | --- | --- |
| PostgreSQL、本地专属实例及 P1 数据底座 | `./deploy/product/local/install.sh` | [local/install.sh](../deploy/product/local/install.sh) |
| RabbitMQ、P2 依赖与私有运行配置；检查 Node/npm 和独立 OCR 环境 | `./deploy/product/local/install-services.sh` | [local/install-services.sh](../deploy/product/local/install-services.sh) |

所有管理命令的共享入口是 [deploy/product/manage.sh](../deploy/product/manage.sh)，本地转发到 [Python 管理 CLI](../server/shuxueshuo_server/product/admin/cli.py)。

## 按任务启动的子进程与外部能力

| 组件 | 用途 | 启动／停止方式 | 实现位置 |
| --- | --- | --- | --- |
| Python 构建执行器 | 执行本次构建的九阶段流程 | Worker 接到任务后自动启动；任务完成后退出。运行中通过 Review 的“取消生成”撤销执行权，由 Worker 终止执行 | [runner.py](../server/shuxueshuo_server/product/runner.py) |
| Paddle OCR 子进程 | 在独立 `server/.venv-ocr` 中识别文字、版面和公式 | source／observation 阶段按需启动，处理结束后退出；无独立常驻启动脚本 | [observation.py](../server/shuxueshuo_server/product/observation.py) |
| Node.js 页面校验／编译进程 | 校验图形配置并生成解析 HTML | page 阶段自动调用，完成后退出；无需单独启动服务 | [runner.py](../server/shuxueshuo_server/product/runner.py)、[build-lesson-page.mjs](../tools/build-lesson-page.mjs) |
| 豆包、DeepSeek | 外部模型 API，负责抽取、求解规划和讲解生成 | 由对应阶段按冻结配置和调用预算访问；本地没有模型服务的 start/stop 命令 | [runner.py](../server/shuxueshuo_server/product/runner.py)、[调用审计与预算](../server/shuxueshuo_server/product/execution.py) |

WebSocket 属于 FastAPI，恢复扫描属于 publisher，产物存储是本地文件系统，均不是额外独立服务。本套产品栈没有使用 Redis、Nginx 或 Docker；DBeaver 只是数据库客户端，不是启动产品系统的前置条件。

## 配置、数据与日志

默认数据根：`~/Library/Application Support/shuxueshuo/local/`。

```text
local/
├── postgres/              PostgreSQL 专属 PGDATA
├── rabbitmq/              RabbitMQ 节点数据
├── artifacts/             原图、检查点、JSON、HTML 等持久产物
├── work/                  按 execution 分隔的执行临时文件
├── config/
│   ├── local.env          数据库实例和端口配置
│   ├── runtime.env        RabbitMQ、API、前端、OCR 配置
│   └── processes.json     应用 PID、启动时间、源码版本
├── logs/
│   ├── api.log
│   ├── frontend.log
│   ├── worker.log
│   ├── publisher.log
│   ├── rabbitmq/
│   └── <execution-id>.log
├── locks/                 管理锁、停写标记与进程心跳
└── backups/               数据库和产物备份
```

密码保存在该实例的私有配置中，不写入本服务清单。更换实例时，所有命令必须使用一致的 `--instance` 和 `--data-dir`；包含空格的数据路径需加引号。例如：

```bash
./deploy/product/manage.sh --mode local --instance local \
  --data-dir "$HOME/Library/Application Support/shuxueshuo/local" services-status
```

更多安装、备份、恢复和故障说明见 [P2 本地运行手册](product-p2-local-runbook.md)。
