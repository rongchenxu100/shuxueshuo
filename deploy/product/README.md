# 产品 P1 安装与管理

P1 提供 27 张产品表、不可变产物存储和内部事务接口。P2 已增加本地上传 API、页面 HTTP 路由、RabbitMQ/Celery 和 Review；完整启停命令见 [P2 本地运行手册](../../docs/product-p2-local-runbook.md)。本文件继续说明数据库底座和后续服务器部署。
不读取或迁移旧 Review SQLite，不改变原 `site/` 及 Nginx 配置。

## 本地原生 PostgreSQL

预装 uv；macOS 预装 Homebrew。安装入口按需安装 `postgresql@17`，不要求 Docker。
Linux 开发机预装 PostgreSQL 17 工具集并设置 `PRODUCT_PG_BIN_DIR`。

```bash
./deploy/product/local/install.sh
./deploy/product/manage.sh --mode local status
./deploy/product/manage.sh --mode local doctor
./deploy/product/manage.sh --mode local db-stop
./deploy/product/manage.sh --mode local db-start
```

macOS 默认数据目录为 `$HOME/Library/Application Support/shuxueshuo/local`。
首次安装仅创建 `internal` 用户、`default` 空间和 owner 成员三条种子，所有其他业务表为空。
重复安装保留配置、密码、种子 ID 和业务数据。没有开机启动项，重启电脑后执行 `db-start`。

自定义实例示例：所有后续命令使用同一 instance、data-dir；端口会从配置读取。

```bash
./deploy/product/local/install.sh --instance development --data-dir '/absolute/path/product data' --port 55432
./deploy/product/manage.sh --mode local --instance development --data-dir '/absolute/path/product data' doctor
```

`postgres/` 是这个实例的 PGDATA，由 `pg_ctl` 管理；不会接管 Homebrew 默认集群。
端口被占用、PGDATA 不完整或不是 PostgreSQL 17 时退出，不删除或重新初始化已有数据。

## 服务器 Docker 发布

服务器预装 Docker/Compose，不要求 uv/Python。构建机需要 Docker buildx、Python 3；更新依赖锁时使用 uv。
管理镜像基于固定 digest 的 PostgreSQL 17.10 bookworm，包含 pg_dump/pg_restore；Python 包使用锁定版本和哈希。
P2 发布包额外包含固定平台的 RabbitMQ 4.3.2 与 `Dockerfile.app` 构建的 API/Worker/publisher 镜像。
系统包在镜像构建时安装，交付以生成的镜像内容 ID 固定；不宣称跨时间重建得到逐字节相同的系统层。

发布前必须提交所有修改和未跟踪文件，脚本在调用 Docker 前拒绝脏工作树。镜像构建和交付脚本均来自同一提交的
`git archive` 快照，清单 `PRODUCT_SOURCE_REVISION` 记录该提交；Git 忽略文件和构建期间的工作树修改不会进入发布包。

每个平台独立输出发布包，不将本地原生数据库开发与镜像构建绑定：

```bash
./deploy/product/build-release.sh --release p1-20260911 --platform linux/amd64 --output /absolute/path/release-amd64
./deploy/product/build-release.sh --release p1-20260911-arm64 --platform linux/arm64 --output /absolute/path/release-arm64
```

发布包包含 `images.tar`、镜像哈希、版本清单及对应版本 `scripts/`。
将完整发布包传到服务器，通过包内脚本执行；清单与校验文件应随受信任交付渠道传输，校验和不替代发布来源认证。

```bash
/absolute/path/release-amd64/scripts/server/install.sh --release /absolute/path/release-amd64 --data-dir /srv/shuxueshuo
/absolute/path/release-amd64/scripts/manage.sh --mode server --data-dir /srv/shuxueshuo doctor
```

### 服务器 P2：RabbitMQ + API/Worker/publisher

P1 `install` 只启动 PostgreSQL。包含 `PRODUCT_RABBITMQ_IMAGE` 与 `PRODUCT_APP_IMAGE` 的发布包可继续安装应用侧服务。
前置：宿主机已装 OCR 镜像 `shuxueshuo-ocr:3.3.0`，且 `$HOME/code/shuxueshuo/server/.env` 含模型密钥（可用 `PRODUCT_REPO_HOST` 覆盖仓库路径）。

```bash
# 生成 /srv/shuxueshuo/config/runtime.env（broker 密码、OCR 路径等）
/absolute/path/release-amd64/scripts/manage.sh --mode server --data-dir /srv/shuxueshuo \
  --release /absolute/path/release-amd64 services-install

# 启动 postgres + rabbitmq + api + worker + publisher，并做 DB/broker/API 自检
/absolute/path/release-amd64/scripts/manage.sh --mode server --data-dir /srv/shuxueshuo services-start
/absolute/path/release-amd64/scripts/manage.sh --mode server --data-dir /srv/shuxueshuo services-doctor
/absolute/path/release-amd64/scripts/manage.sh --mode server --data-dir /srv/shuxueshuo services-status
/absolute/path/release-amd64/scripts/manage.sh --mode server --data-dir /srv/shuxueshuo services-stop
```

`services-stop` 停止 api/worker/publisher/ocr/rabbitmq，PostgreSQL 保持运行。服务器暂不在 Compose 内启 Next；Studio 前端仍按 [frontend-studio-workbench.md](../frontend-studio-workbench.md) 单独部署到 `127.0.0.1:3000`，由 `studio.shuxueshuo.com` Nginx 反代。产品 API 默认 `127.0.0.1:8000`（`runtime.env` 的 `API_PORT`）。

### 构建性能：发布指纹与 Worker 并发

服务器容器同时设置 `PRODUCT_MODE=server`、`PRODUCT_IN_CONTAINER=1` 和非空
`PRODUCT_RELEASE_ID` 时，每个进程复用自己的依赖探测快照。每次使用仍检查依赖文件清单及
inode、大小、mtime/ctime，并检查 `server/.env` 内容和进程环境；变化后重新完整探测。
探测期间发生变化或探测失败时阻断，不回退旧快照。实例重启／执行恢复后的新进程重新探测，
不信任磁盘缓存。OCR manifest、数据库执行权、取消、租约及构建配置匹配仍实时检查。
本地开发及没有发布标识的环境继续每次完整探测。

实例的 `config/runtime.env` 支持 `WORKER_CONCURRENCY='2'`（允许 1–16，缺省为 1，兼容旧配置）。
进程环境 `PRODUCT_WORKER_CONCURRENCY` 可覆盖该值；使用 Compose 部署时，直接修改挂载的数据目录中
`config/runtime.env` 即可，无需修改 Compose。宿主 shell 的任意环境变量不会自动传入容器。
该设置只影响任务并发，不改变模型预算、题意复核、求解策略或历史构建的有效配置。

建议先在资源足够的测试实例设置为 2。更新后先停止接收新任务并排空现有任务，再使用管理脚本
`services-stop` / `services-start` 重启受管理服务；仅编辑配置不会改变已运行的 Worker。
仍采用 threads 池、每个构建独立子进程、prefetch=1 与数据库执行权去重。
OCR sidecar 仍串行处理，增加并发主要让其他题在某题等待模型期间继续推进，不能保证单题速度翻倍。

实现验证：独立 PostgreSQL 的产品、依赖及重建回归 **151 passed、3 skipped、1 deselected**；
三个跳过项为专用 RabbitMQ 测试，未选中的是付费模型测试。并发测试实际运行 Celery threads 池
（使用内存 transport），另通过真实 PostgreSQL 验证并发执行、重复投递和取消隔离。
本机 Mac 对真实依赖探测的测量：首次 0.926 秒，10 次缓存命中中位数 0.0108 秒，快照完全一致。
此数据不代表服务器整题耗时；线上仍需部署后实测。日志与计时分别为
`/private/tmp/product-release-cache-regression.log` 和 `/private/tmp/product-release-cache-benchmark.json`。

### OCR：本地 Mac vs 服务器

| 环境 | 方式 |
| --- | --- |
| **Mac 本地**（`--mode local`） | 无 Docker；本机直接安装 Paddle；`REVIEW_OCR_PYTHON` 指向本机 Python。不设 `PRODUCT_OCR_URL`。 |
| **服务器**（`compose.app`） | 常驻 `ocr` sidecar（`shuxueshuo-ocr` 镜像 + [`../ocr/sidecar_server.py`](../ocr/sidecar_server.py)）；worker 经 `PRODUCT_OCR_URL=http://ocr:8080` 调用。**不再**挂 `docker.sock` / 嵌套 `docker run`。 |

服务器需已构建 OCR 镜像并预热 `~/.paddlex`（见 [OCR 文档](../ocr/README.md)）。sidecar 脚本与 observation 代码从宿主机仓库只读挂载，发版前请 `git pull` 仓库并打含新 compose/runner 的产品包。常驻模型会多占内存（约数百 MB～1G+），建议主机 ≥8G；2G 机不建议。

普通管理命令自动读取实例保存的 release 路径。若镜像尚未加载，验证离线包哈希再 load。
数据库仅映射 `127.0.0.1:5432`，可通过 `--port` 修改；持久卷名绑定实例和数据根，不复用其他实例的卷。
admin 以部署用户 UID/GID 运行，按需挂载配置及数据；不启动业务容器。

版本升级：先停止所有使用该数据库的业务写入进程及清理进程，再执行新发布包的 `server/deploy.sh`。
脚本取得实例锁，临时禁用 app 登录，发现仍有 app 连接则拒绝部署；完成备份、迁移与权限自检后才恢复登录。

```bash
/absolute/path/new-release/scripts/server/deploy.sh --release /absolute/path/new-release --data-dir /srv/shuxueshuo
```

失败不会自动回退数据库；app 可能留在 NOLOGIN 的维护状态。排查后用已验证的目标版本执行 `resume`，它先运行完整 doctor 再开放登录。
宿主机异常退出可能留下 `locks/server-operation` 目录；确认没有管理操作运行后，管理员才能移除这个空锁目录。
P1 不升级 PostgreSQL 大版本，也不替换运行中的旧 API、Review、Nginx。P2 要另接任务排空和服务切换。

## 配置和数据库客户端

实际配置位于数据根的 `config/`，不进入仓库或镜像：

| 文件 | 内容 |
| --- | --- |
| local.env | 本地实例、PG 工具目录、端口和数据根 |
| compose.env | 服务器实例、端口和目录标识 |
| app.env | product_app 密码，业务账号无 DDL 权限 |
| migration.env | product_migration 密码，仅结构升级及管理操作使用 |
| bootstrap.env | product_bootstrap 密码，仅初始化、维护窗口管理使用 |

秘密文件权限必须是 0600。连接 URL 在进程内由配置派生，不打印密码 URL、不覆盖原 `server/.env`。
本地应用连接 `127.0.0.1:端口/product`，Docker admin 连接 `postgres:5432/product`。
数据库客户端可使用 DBeaver：本地直连，服务器通过 SSH 隧道连接 loopback 端口；正式改表使用 Alembic。

## 备份和恢复

先停止业务写入和产物清理。备份包含逻辑数据库 dump、全部登记文件、行数及 SHA256 清单、迁移版本；不包含原始凭据。
备份前阻止新的 app 登录，现存 app 连接会令操作失败；不会强制终止其他进程。
以 migration/bootstrap 身份运行的其他管理程序也必须停止，不能绕过维护窗口约定。

```bash
./deploy/product/manage.sh --mode local backup
./deploy/product/manage.sh --mode server --data-dir /srv/shuxueshuo backup
```

备份文件在 `backups/{id}/`；`.incomplete` 表示失败或中断，不能用作恢复源。
恢复必须使用新实例、新数据目录和未占用端口，重建角色及权限，不覆盖原库或自动切换应用：

```bash
./deploy/product/manage.sh --mode local --data-dir '/absolute/path/restored' --port 55433 restore --target restored --backup '/absolute/path/backup-id'
/absolute/path/release/scripts/manage.sh --mode server --release /absolute/path/release --data-dir /srv/shuxueshuo-restored --port 55433 restore --target restored --backup /absolute/path/backup-id
```

先校验所有备份文件，再恢复数据库和产物，最后比对行数、迁移版本、账号权限及所有登记文件哈希。
失败目标留待诊断，重试使用另一个全新目录；不提供自动清空或 `down -v` 快捷命令。

## 验证

纯存储/流程测试不需要数据库。数据库测试必须显式提供已安装的独立实例，不允许指向实际业务实例：

```bash
cd server
uv run pytest tests/product/test_storage_pipeline.py -q
PRODUCT_TEST_DATA_DIR='/absolute/path/p1-test' PRODUCT_TEST_INSTANCE=p1-test uv run pytest tests/product -q
```

测试会在专用库追加隔离的用户、空间及 fixture 数据，不自动删除历史；每次安装验收使用新的空数据根。
默认缺少 `PRODUCT_TEST_DATA_DIR` 时数据库用例跳过；带跳过的测试结果不能作为 PostgreSQL 验收通过。
不同环境的安装、依赖版本、实际测试数和备份恢复证据记录在 `docs/product-p1-acceptance.md`。

退出码：0 成功，2 前置条件/参数错误，3 服务不可用，4 迁移或版本错误，5 完整性失败。
## 敏感配置提交规则

真实凭据仅存于本机 `.env` 配置：模型配置使用 `server/.env`，产品实例使用 Git 外数据根的 `config/*.env`。安装器生成的配置、日志和数据均保留在实例数据根，不加入仓库。

Git 只允许提交无真实凭据的 `.env.example` 或 `*.env.example` 模板；密码、API key、cookie 等字段留空。不要使用 `git add -f` 绕过环境文件忽略规则。普通不含秘密的代码配置和发布清单可以提交。

Review 文档可以记录环境变量名、公开模型 endpoint、本地端口和不可用于认证的运行 ID；不得记录真实凭据、认证请求头、带凭据的连接串或未脱敏的私有配置输出。

### 题意抽取：服务器 `server/.env` 检查清单

路径（勿提交）：`$HOME/code/shuxueshuo/server/.env`（可用 `PRODUCT_REPO_HOST` 覆盖）。  
Compose 中 api / worker / publisher **只读挂载**该文件。改完后必须 `services-stop` / `services-start`，仅保存文件不会让已运行进程重载。

**必填（视觉抽取：首轮 / 修复 / 复核）**

| 变量 | 期望值 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 非空 | 缺失会 `configuration.extraction_key_missing`；与文本 Solver 共用密钥 |
| `PROBLEM_VISION_PROVIDER` | `deepseek` | 其它值直接拒绝，无 Doubao 自动回退 |
| `DEEPSEEK_VISION_MODEL` | `deepseek-flash` | 实现写死校验；勿写成 `deepseek-v4-flash` |
| `DEEPSEEK_VISION_BASE_URL` | `https://api.deepseek.com` | 进入依赖指纹；改 endpoint 会使旧构建需重建 |
| `DEEPSEEK_VISION_TIMEOUT` | `300` | 秒；原图 + high detail，过短易超时 |
| `DEEPSEEK_VISION_MAX_TOKENS` | `16384` | 输出上限 |

**推荐模板（可直接粘贴后填密钥）**

```dotenv
PROBLEM_VISION_PROVIDER=deepseek
DEEPSEEK_VISION_MODEL=deepseek-flash
DEEPSEEK_VISION_BASE_URL=https://api.deepseek.com
DEEPSEEK_VISION_TIMEOUT=300
DEEPSEEK_VISION_MAX_TOKENS=16384
DEEPSEEK_API_KEY=

# 下游文本 Solver / lesson（非视觉）
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

**可空 / 不再用于产品抽取**

- `DOUBAO_API_KEY` / `DOUBAO_*`：仅 legacy/debug；产品 extraction **不读**豆包。
- 策略固定为 thinking `enabled` + `reasoning_effort=low`、非流式 `json_object`、`image_detail=high`、SDK retries=0；**不要**在 `.env` 里试图改 thinking。
- 预算仍由构建有效配置固化：草稿 3 / 复核 3 / 语义 6 / 网络 12。

**上线前在服务器自检（不打印密钥值）**

```bash
ENV="$HOME/code/shuxueshuo/server/.env"
test -f "$ENV" && stat -c '%a %n' "$ENV" 2>/dev/null || stat -f '%Lp %N' "$ENV"
# 权限建议 600

# 键是否存在且非空（只输出 ok/missing）
for key in DEEPSEEK_API_KEY PROBLEM_VISION_PROVIDER DEEPSEEK_VISION_MODEL \
           DEEPSEEK_VISION_BASE_URL DEEPSEEK_VISION_TIMEOUT DEEPSEEK_VISION_MAX_TOKENS; do
  if grep -Eq "^${key}=.+" "$ENV"; then echo "ok  $key"; else echo "MISSING $key"; fi
done

grep -E '^(PROBLEM_VISION_PROVIDER|DEEPSEEK_VISION_MODEL|DEEPSEEK_VISION_BASE_URL|DEEPSEEK_VISION_TIMEOUT|DEEPSEEK_VISION_MAX_TOKENS)=' "$ENV"
# 期望：deepseek / deepseek-flash / https://api.deepseek.com / 300 / 16384
```

改 `.env` 后：

```bash
RELEASE=$(cat /srv/shuxueshuo/config/release-path)
"$RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo \
  --release "$RELEASE" services-stop
"$RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo \
  --release "$RELEASE" services-start
"$RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo \
  --release "$RELEASE" services-doctor
```

若同时升级了抽取代码，仍须打**新产品包**再 `services-start`；只改密钥可只重启。视觉字段进入依赖指纹，旧 Doubao / 旧模型冻结构建会要求重建。

首轮、修复与独立视觉复核固定为 thinking enabled / reasoning_effort low、非流式 JSON object。`DEEPSEEK_MODEL` / `DEEPSEEK_BASE_URL` 继续只控制下游 Solver 等文本路径。
