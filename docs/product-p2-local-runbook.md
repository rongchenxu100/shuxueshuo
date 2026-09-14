# P2 本地运行手册

本轮只运行本地系统，不部署服务器、不使用 Docker、不迁移旧 Review 数据。

服务职责、入口、启动／停止命令及对应脚本见 [本地产品服务列表](product-local-services.md)。

## 环境与目录

已验证 macOS Apple Silicon：PostgreSQL 17.10、RabbitMQ 4.3.2、Erlang 28.5.0.2、Celery 5.6.3。Python 主环境由 `server/uv.lock` 固定；Paddle 继续使用独立 `server/.venv-ocr/bin/python`。

默认实例 `local`，数据根 `$HOME/Library/Application Support/shuxueshuo/local`：

```text
local/
├── config/
│   ├── local.env                 # PG 实例配置
│   ├── app.env / migration.env / bootstrap.env
│   ├── runtime.env               # broker、OCR、API、前端配置，权限0600
│   ├── rabbitmq.conf / rabbitmq-env.conf / rabbitmq-plugins
│   └── processes.json            # PID、启动时间、源码版本
├── postgres/                     # 专属 PGDATA
├── rabbitmq/mnesia/               # 专属节点数据
├── artifacts/workspaces/...       # 不可变持久产物
├── work/<execution-id>/           # 执行临时目录
├── logs/                         # API/Worker/publisher/前端与 execution 日志
├── locks/                        # 管理锁、停写标记、进程心跳
└── backups/                      # 经完整性校验的数据库+产物备份
```

不把生成 HTML 放入 `site/`；不开放 artifacts 根目录。`work/` 不是历史或恢复权威，只有已登记并接受的 checkpoint 可复用。

## 安装与启动

从仓库根执行：

```bash
# 仅第一次需要；现有正式 PostgreSQL 已完成此步骤
./deploy/product/local/install.sh

# 安装/检查 RabbitMQ、Node/npm、OCR；同步锁文件，迁移，生成私有运行配置
./deploy/product/local/install-services.sh

./deploy/product/manage.sh --mode local services-start
./deploy/product/manage.sh --mode local services-doctor
./deploy/product/manage.sh --mode local services-status
```

默认入口：

- 工作台：<http://127.0.0.1:3000/>；上传单题图片，中栏进度、右栏网页，范围见[首版设计](workspace-product-design.md)。
- Review：<http://127.0.0.1:3000/review/runs>
- 产品 API：<http://127.0.0.1:8000/api/product/v1/health>
- WebSocket：`ws://127.0.0.1:8000/api/product/v1/ws`
- PostgreSQL：`127.0.0.1:5432/product`，业务账号 `product_app`。
- RabbitMQ：`127.0.0.1:5672`，用户/vhost/cookie 来自本实例私有配置。管理插件未启用。

不运行 `brew services`，不安装开机启动。启动器拒绝端口被其他进程占用，不杀占用进程。检测到旧 Review Worker 时先停止切换，待旧任务完成后正常关闭旧 Worker。

Linux 开发机需预装 PostgreSQL17、RabbitMQ、Node/npm 和兼容 OCR 环境；初始化前显式设置 `PRODUCT_RABBITMQ_BIN` 为 RabbitMQ sbin 目录。本轮只实测 macOS。

首次安装可用环境变量指定 broker/API/前端端口及 OCR 解释器；再次运行使用已有私有配置，不重置密码：

```bash
PRODUCT_BROKER_PORT=5673 PRODUCT_API_PORT=8100 PRODUCT_FRONTEND_PORT=3100 \
  ./deploy/product/manage.sh --mode local --instance p2-test \
  --data-dir '/private/tmp/shuxueshuo-p2-acceptance' services-install
```

实例/data-dir 的覆盖必须在所有管理命令中保持一致。数据根使用绝对路径，含空格路径必须引用。模型密钥从现有 `server/.env`/运行环境读取，不能写入构建配置、命令行或文档。修改 `.env` 需先排空并停止服务再重启，运行中的构建会拒绝混用变更后的有效配置。

## 停止、更新与故障

```bash
./deploy/product/manage.sh --mode local services-stop
# PostgreSQL 默认保留运行；需要时再显式停止
./deploy/product/manage.sh --mode local db-stop
```

停止时先创建 `services-draining` 标记，API 拒绝新写入，最多等待30秒排空任务，然后正常关闭前端/API/publisher/Worker及本实例 RabbitMQ。超时返回失败并保留进程与任务；等待任务完成或在 Review 显式取消后重试停止。不要删除数据目录或通过杀 PID 代替正常停机。

`services-start` 只有在四个进程、版本、心跳和 HTTP 就绪后解除停写；重复启动复用现有 PID。源码/资源版本改变而旧服务仍运行时返回 `runtime.version_changed_stop_first`，先停后启。

自检不调用模型：检查角色、迁移版本、所有登记文件、原子存储探针、Paddle 导入与模型文件、队列、PID/版本/心跳、outbox 积压和过期租约。孤立文件是报告项，不自动删除。故障测试产生的孤立文件不代表登记文件损坏。

RabbitMQ4.3 默认拒绝非持久、非独占队列。本实现关闭不用的 Celery remote control 和 gossip/mingle，业务队列保持 durable classic；取消及恢复由 PostgreSQL 控制，无须启用旧队列特性。[RabbitMQ 队列说明](https://www.rabbitmq.com/docs/4.2/queues)、[Celery 配置](https://docs.celeryq.dev/en/stable/userguide/configuration.html#worker-enable-remote-control)。

## 备份与迁移

先停止整套服务，并在 DBeaver 等客户端正常断开 `product_app` 连接；备份会拒绝任何仍存活的业务连接，不强杀会话。

```bash
./deploy/product/manage.sh --mode local backup
./deploy/product/manage.sh --mode local migrate
./deploy/product/manage.sh --mode local doctor
./deploy/product/manage.sh --mode local services-start
```

正式 P1 → P2 升级前备份：
`$HOME/Library/Application Support/shuxueshuo/local/backups/cf2a15501cbe4307838e28441c21e676`。
该快照是 `0001_product`、零登记产物；P2 migration 为 `0002_product_runtime_indexes`，只新增运行查询索引，不修改初始 revision。

恢复必须选择新实例和新数据根，保持原实例不动；使用与备份 revision 相匹配的发布代码验证恢复，再显式 migrate 到新版本。不自动 downgrade。完整 P1 本地恢复记录见 [P1 验收](product-p1-acceptance.md)。服务器恢复未验收。

## Review 使用

### 本地代码更新后任务一直排队

`services-status` 中进程存活不等于可以消费当前版本任务。构建按 `deployment_version` 路由到 RabbitMQ 队列，后台 Python 进程不会随代码编辑自动重载。修改后端或生成依赖后，在无待处理任务时执行 `services-stop`、`services-start`，再运行 `services-doctor`，确认进程版本与心跳一致后上传新题。

2026-09-11 排队故障：题目 `45eca508-1ca7-42cd-a5cb-5edd05373864` 的构建 `ac9e09b3-7bdf-4a9c-af8b-47add1a7f335` 已发布到 `b4b536d…` 队列（1 条待消费、0 个消费者），旧 Worker 仍监听 `fd785e0…` 队列。确认没有执行中任务、原构建版本与磁盘代码一致后，保留数据库和 RabbitMQ 消息，轮换受管理的应用进程。原构建于 17:32:50 开始执行，无重新上传或新建构建；恢复后 doctor 通过，发件箱积压与过期租约均为 0。

若已出现这种排队，不直接清空队列、修改冻结版本或反复上传；先核对构建版本、消费者和执行权。正常停止会等待排队任务排空，异常队列需要先恢复对应版本消费者。本次定向恢复操作不作为跳过排空检查的日常启停方式。

新图片上传后自动提交一次首次构建；刷新会恢复原请求。相同图片引用已有题目，不自动调用模型；失败后的重试需预览并显式提交新的构建。不要把“重新上传相同图片”当作重新生成按钮。

阶段标题来自冻结快照。JSON、原始调用、校验材料位于高级审查；学生结果在隔离 iframe 中展示，或通过版本固定的页面链接打开。题意保存只产生校验后的修订，解析需单独预览和重建。通过/需修改/撤销结论绑定具体页面版本，历史成功页不能冒充当前有效页。

## 验证命令

```bash
cd server
PRODUCT_TEST_DATA_DIR=/private/tmp/shuxueshuo-p2-acceptance \
PRODUCT_TEST_INSTANCE=p2-test PRODUCT_TEST_BROKER=1 \
uv run pytest tests/product -q --tb=short

uv run pytest tests/test_review_service.py tests/test_review_versions.py \
  tests/test_review_dependencies.py tests/test_review_rebuild.py \
  tests/solver/test_review_human_revision.py tests/solver/test_review_evidence_checkpoint.py -q
```

上述产品测试会追加隔离用户/空间和测试记录；broker 故障测试会停止并重启专用节点，绝不能指向正式 `local`。测试前仅启动专用数据库和 broker，不要与该实例的 `services-stop` 并发运行，否则停写标记会正确地让 API 返回503。`worker_fault_entry.py` 只属于测试，使用睡眠子进程验证真实消息/进程边界，不会调用模型或产生伪造成功页面。

```bash
npm run test --prefix frontend
npm run lint --prefix frontend
npm run typecheck --prefix frontend
npm run build --prefix frontend
```

前端 build 与 dev 共用 `.next`，先停止前端再构建。接口合同及 P3 接线见 [P2 接口说明](product-p2-interfaces.md)；实测结果与未完成项见 [P2 验收记录](product-p2-acceptance.md)。
