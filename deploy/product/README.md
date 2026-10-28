# 产品 P1 安装与管理

P1 提供 27 张产品表、不可变产物存储和内部事务接口。P2 已增加本地上传 API、页面 HTTP 路由、RabbitMQ/Celery 和 Review；完整启停命令见 [P2 本地运行手册](../../docs/product-p2-local-runbook.md)。本文件继续说明数据库底座和后续服务器部署。
不读取或迁移旧 Review SQLite。主站静态页面不进发布包：Nginx 直接读取服务器仓库 `site/`，用 `git pull` 更新；教学内容版本须与学习库一致，步骤见 [学习内容正式替换](learning-rollout.md)。

拍题学现已接入单机生产 API、共享 OCR sidecar、清理维护及 HTTP/WebSocket 代理；接入约束与不联网的镜像演练方法见[拍题学单机生产说明](../../docs/search-single-host-production.md)。这不表示已部署线上，也不替代真实供应商和备份恢复验收。

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

## 新公共知识图谱与学习数据（阶段 3）

当前学习结构为 `0012_drill_updated_at`。管理镜像从新图谱、专题关联和服务端小题原稿导入，
不读取旧图谱或生成的 HTML；API 账号只能读取公共内容表。日常命令不会清理学习记录：

```bash
./deploy/product/manage.sh --mode local check-learning
./deploy/product/manage.sh --mode local publish-learning
./deploy/product/manage.sh --mode local reassess-learning
```

`check-learning` 只校验并报告版本与数量；`publish-learning` 事务发布，重复执行不会复制数据；
`reassess-learning` 从已完成的五题轮次重建能力状态。发布会关闭关联或题池变化影响的未完成轮次，
保留已答证据与已有状态。网页产物也应由同份原稿构建，内容版本不一致时客户端停止新建记录。

已有 `0010` 学习内容的实例不能直接升级后继续写旧关联。仅本地提供一次性重建命令，执行前需停止网站进程：

```bash
./deploy/product/manage.sh --mode local rebuild-learning
```

命令先校验、报告清理范围、停写和备份，再在同一事务中清理旧学习记录、升级结构并发布新内容。
用户、登录、其他产品数据及无关题目的学习标记保留；失败事务回滚，维护状态保留供诊断。
此命令拒绝服务器和容器环境，也拒绝重复用于已升级的实例。服务器另有仅替换旧公共内容的显式入口；发现任何旧学习记录即停止，见 [正式替换手册](learning-rollout.md)。

固定本地联调使用 `127.0.0.1:8779` 和默认数据目录、数据库端口 `5432`。题页参数
`?knowledge=next` 为无记录预览，`?knowledge=next&learning=1` 为登录联调；节点详情页使用
`?learning=1`。完整字段、验收及维护说明见 [公共图谱维护说明](../../docs/public-knowledge-graph-stage4.md)。

## 服务器 Docker 发布

服务器预装 Docker/Compose，不要求 uv/Python。构建机需要 Docker buildx、Node.js、Python 3；更新依赖锁时使用 uv。
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

发布包包含 `images.tar`、镜像哈希、内容版本、提交版本及对应版本 `scripts/`，不含静态站。构建会运行图谱生成器 `--check` 并核对该提交 `site/` 与原稿的内容版本；镜像与脚本来自同一 `git archive`。
清单中的 Alembic revision 从同份打包源码解析，不使用固定版本号。
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

服务器需已构建 OCR 镜像并预热 `~/.paddlex` 中的六种模型（见 [OCR 文档](../ocr/README.md)）。sidecar 脚本与 observation 代码从宿主机仓库只读挂载，发版前请 `git pull` 仓库并打含新 compose/runner 的产品包。产品和搜索共用一个 OCR 进程；[本地真实镜像验收](../../docs/search-real-ocr-local-acceptance.md)的容器观测峰值为 3.009 GiB，不能再按旧的单套模型内存估算。该数据来自 Rosetta 和有限样本，不是主机规格承诺；上线前须在原生服务器上同时运行 API、数据库、业务 worker 和 OCR，实测峰值、排队及剩余内存。

普通管理命令自动读取实例保存的 release 路径。若镜像尚未加载，验证离线包哈希再 load。
数据库仅映射 `127.0.0.1:5432`，可通过 `--port` 修改；持久卷名绑定实例和数据根，不复用其他实例的卷。
admin 以部署用户 UID/GID 运行，按需挂载配置及数据；不启动业务容器。

版本升级：先按[正式替换手册](learning-rollout.md#维护窗口与首次替换)获取发布提交，运行 `server/check-site-revision.sh --allow-forward` 检查仓库干净且能快进；再停止所有使用该数据库的业务写入进程及清理进程，执行新发布包的 `server/deploy.sh`。
脚本取得实例锁，临时禁用 app 登录，发现仍有 app 连接则拒绝部署；完成备份、迁移与权限自检后才恢复登录。

```bash
/absolute/path/new-release/scripts/server/deploy.sh --release /absolute/path/new-release --data-dir /srv/shuxueshuo
```

失败恢复取决于数据库事务是否已提交：提交前，DDL 和导入数据一起回滚到旧库，app 保持 NOLOGIN，仓库不要 `git pull`，使用**旧发布包的脚本和 `--release`** 执行 `resume`，再启动旧包应用。提交后，数据库保留新版本，若 doctor 失败，排除原因后使用**目标发布包**执行 `resume`（先核对数据库与目标包内容一致），再继续 `git pull` 与 `verify-release`。预检阶段尚未停写的失败不需要 `resume`。详细判定和命令见[正式替换手册](learning-rollout.md#维护窗口与首次替换)。
宿主机异常退出可能留下 `locks/server-operation` 目录；确认没有管理操作运行后，管理员才能移除这个空锁目录。
发布不升级 PostgreSQL 大版本，也不自动修改运行中的 Nginx 配置；先排空任务、停应用再部署。`deploy` 成功后数据库已恢复 LOGIN，应用保持停止；把服务器仓库前进到发布包的提交（`PRODUCT_SOURCE_REVISION`），显式 `verify-release` 检查仓库干净且 HEAD 与该提交完全相同，再核对镜像、学习库与仓库 `site/` 的内容版本，最后 `services-start`。`services-start` 前的校验不要求仓库提交相同，对仓库 `site/` 只报告不阻止，保留纯静态页面独立更新和无人值守重启的行为。

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

拍题准入新增 `0016_search_admission` 迁移：每账号每日新生成 10／重跑 3、全站 100／50，生成账号并发 1、全局 2 运行＋4 等待，上传/OCR 在途每账号 2、全站 10。OCR 保持单进程。费用开关初始关闭且恢复后强制关闭，须显式启用；配置、停开命令及离线验收见[拍题准入说明](../../docs/search-admission.md)。额度账本随备份保存，但题目删除或到期不能退回已消耗额度。

生产 Compose 组合、Nginx、空库迁移、单进程 OCR 和费用开关的复验方式见[单机服务与离线演练](../../docs/search-single-host-production.md)。复现入口 `deploy/product/rehearse-search.py` 需要本机已有 app/admin/PostgreSQL/Nginx/RabbitMQ/OCR 六种镜像；仅使用隔离内部网络和 fixtures，不代表正式发布、真实供应商或目标服务器容量验收。

先停止业务写入和产物清理。`product-backup/v2` 包含逻辑数据库 dump、产品登记产物，以及数据库登记且尚未到期的拍题页面和提交私有文件；拍题文件逐项记录 SHA-256、字节数、归属和原始 `expires_at`，不按目录扫描导入匿名或孤立文件。备份清单还记录行数、迁移版本和删除权威游标；不包含原始凭据。
备份前阻止新的 app 登录，现存 app 连接会令操作失败；不会强制终止其他进程。
以 migration/bootstrap 身份运行的其他管理程序也必须停止，不能绕过维护窗口约定。

```bash
./deploy/product/manage.sh --mode local backup
./deploy/product/manage.sh --mode server --data-dir /srv/shuxueshuo backup
```

备份文件在 `backups/{id}/`；`.incomplete` 表示失败或中断，不能用作恢复源。完整 v2 备份保留最多 30 天，拍题文件副本仍按原页面 24 小时、原提交 30 天的截止时间提前清除，备份和恢复均不续期。数据库 dump 不是逐行即时擦除：它随整份备份最多保留 30 天，恢复前必须通过独立删除日志和原截止时间过滤。自动清理只处理本实例中可识别的备份；离线复制到别处的备份须另行落实相同保留期。

拍题删除的独立权威记录位于源实例 `work/search/private-v1/recovery/deletions.jsonl`，不以旧数据库或备份中的日志副本替代。它在数据库删除前先持久写入并 `fsync`，只记录 `user_id/search_id/created_at`，不保存题面或照片。迁移 `0015_search_recovery` 将数据库与该日志的 authority/cursor 绑定；缺失、完整行或中间记录损坏、权威不匹配或落后于数据库游标时拒绝继续，不能靠回滚数据库或新建空日志消除错误。管理者仍须保证提供的是当前源权威；校验不能证明任意旧副本就是最新日志。

写入或刷盘失败会尝试截回追加前长度并刷盘；若异常中断遗留末尾无换行残片，初始化在排他锁下验证完整前缀的哈希链、authority 及数据库游标后，才自动截掉残片并记录告警。数据库游标不能超过该前缀；完整记录仍保留。磁盘故障先停止业务、修复空间或文件系统问题，再启动应用触发有限修复；仍报完整性错误时须取回可信当前日志，不允许手工编辑日志、修改游标或绕过校验。详细边界见[删除权威修复说明](../../docs/search-backup-restore-local-acceptance.md#尾部未完成写入的修复边界)。

首次建头断电留下空文件或半行时，只有数据库尚未初始化、两个游标为零且摘要为空，才在上述锁内删除没有任何完整行的普通文件，并用原 authority 重建；已绑定日志或任何完整记录不因此清空。

**升级恢复点要求：** 含拍题数据的 `0014` 备份及所有含拍题数据的 v1 备份均不能恢复新版拍题数据。迁移到 `0015`、首次初始化日志成功后，必须立即停止业务写入及清理，建立并核验首份 v2 备份，同时独立保管当前日志，然后再开放接单。不要等下一次定时备份：迁移前备份到首份合格 v2 备份之间没有新版拍题可用恢复点。

恢复前必须停止源实例的全部业务写入、清理及管理操作；恢复期间持有源日志共享锁，误留在线的删除请求争锁最多等待 250 毫秒，超时返回 503 `recovery.busy`，而不是无限等待。503 不表示删除成功，此保护也不能把恢复结束后旧源的新删除同步到目标。恢复必须使用新实例、新数据目录和未占用端口，重建角色及权限，不覆盖原库或自动切换应用。`--search-recovery-root` 指向当前源实例的拍题根目录，必须包含其 `recovery/`，不是某次备份中的目录：

```bash
./deploy/product/manage.sh --mode local --data-dir '/absolute/path/restored' --port 55433 restore --target restored --backup '/absolute/path/backup-id' --search-recovery-root '/absolute/path/source/work/search/private-v1'
/absolute/path/release/scripts/manage.sh --mode server --release /absolute/path/release --data-dir /srv/shuxueshuo-restored --port 55433 restore --target restored --backup /absolute/path/backup-id --search-recovery-root /srv/shuxueshuo/work/search/private-v1
```

服务器包装脚本将指定的源拍题根只读挂载到恢复容器。v2 备份没有任何拍题页面/提交时可省略该参数；有拍题数据时必须提供当前源日志及 `0015` 游标。旧 v1 备份只允许恢复没有拍题页面/提交的实例，仍需满足迁移版本匹配；含拍题数据的 v1 明确拒绝为 `restore.search_backup_unsupported`，不能把缺失的私有文件或日志视为已经删除。

目标应用角色在整个恢复过程中保持 `NOLOGIN`。校验备份及当前源删除权威后，先恢复数据库并重放删除，再为目标建立新 authority，只复制剩余且未到期记录的私有文件，按原期限清理到期内容并将遗留非终态标为中断；完成版本、权限、内容校验及 doctor 后才恢复登录。恢复还撤销备份中的全部学生登录会话及未消费短信挑战，学生必须重新获取验证码并登录，旧 Cookie 和旧验证码不能复活。源实例保持不变；之后的目标删除记入目标日志。

仅做隔离演练、不切换业务流量时，原源实例仍是当前权威。正式切换到恢复目标后，必须同时将权威来源切换为新目标日志，并立即创建新 v2 备份。旧备份与新 authority 不匹配时会拒绝恢复；不能继续把旧备份配旧源日志当作当前恢复入口。旧源仍存在不证明它仍是当前源，工具不能自动识别所有陈旧副本或替代这一步运维交接。

恢复失败保留目标 `locks/restore-incomplete`，`resume` 和 `services-start` 不能绕过。保留失败目标作诊断，重试使用另一个全新目录；不要手动删除标记后开放服务，不提供自动清空或 `down -v` 快捷命令。删除权威须独立于可回滚数据库保管；当前源权威丢失或存在上述有限修复之外的损坏时恢复失败关闭，异地保管与灾备流程仍须部署前另行安排。

运行文件在启动和每分钟维护，v2 备份在启动及每小时维护；显式 `search.maintenance ... cleanup` / `backup-prune` 立即处理，不等待下个定时周期，详见[拍题备份恢复说明与本地验收](../../docs/search-backup-restore-local-acceptance.md)。识别为本轮格式的不完整备份在创建一小时后可清理；清理失败保留记录并在对应周期重试，备份错误不每分钟重复报告。只删除当前实例认可的路径，不操作旧匿名目录或未知备份格式。账号注销按当前决定暂缓，按题删除也不等于删除整个账号。

2026-10-24 审查修复合并回归 **200 passed、0 skipped**，涵盖真实 PostgreSQL 备份恢复、受限修尾及 API 重新启动/MockSMS 登录、首次日志头断电恢复、清理双异常、恢复锁下删除 503、历史快照复用与维护周期；完整命令和日志见[审查修复验收](../../docs/search-backup-restore-local-acceptance.md#7-审查修复验收2026-10-24)。未部署线上，不替代服务器与真实供应商验收。

停服期间自动维护不运行，须由值守人员或既有系统 timer 调用独立 `backup-prune`；该命令不连接数据库或依赖删除日志，日志故障时仍可按期清除备份副本。本轮不新增服务器调度系统，也不能将“已提供命令”等同于“停服期间已持续清理”：

```bash
./deploy/product/manage.sh --mode local --data-dir /absolute/path/source --instance source backup-prune
/absolute/path/release/scripts/manage.sh --mode server --release /absolute/path/release --data-dir /srv/shuxueshuo backup-prune
```

## 验证

纯存储/流程测试不需要数据库。数据库测试必须显式提供已安装的独立实例，不允许指向实际业务实例：

```bash
cd server
uv run pytest tests/product/test_storage_pipeline.py -q
PRODUCT_TEST_DATA_DIR='/absolute/path/p1-test' PRODUCT_TEST_INSTANCE=p1-test uv run pytest tests/product -q
```

测试会在专用库追加隔离的用户、空间及 fixture 数据，不自动删除历史；每次安装验收使用新的空数据根。
默认缺少 `PRODUCT_TEST_DATA_DIR` 时数据库用例跳过；带跳过的测试结果不能作为 PostgreSQL 验收通过。
内部事务与存储合同见 `docs/product-p1-interfaces.md`；各环境的实际测试结果随对应运行产物保存。

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

## 个人知识图谱内容发布

`0008_practice_identity` 迁移题目别名，`0009_learning_graph` 增加公共内容和学生练习表。
`install`、`deploy` 在迁移后自动执行内容校验与导入；手动 `migrate` 后需执行同一版本的
`publish-learning`。导入器核对题页、教师 JSON 与专题映射，失败停止发布；应用账号不能编辑公共内容。
阶段 3 使用 `tools/export-public-knowledge.mjs` 及共享校验模块，读取 `site/data/knowledge-next/`、
服务端 `drills-next/`、教师契约、`site/assets/explain/` 和 `site/1/`、`site/2/` 题页。
管理镜像按需复制这些输入，构建时用镜像内的 Node.js/Python 执行完整内容校验，不依赖旧图谱或生成页面。
新增专题目录时须同步增加管理 Dockerfile 及 dockerignore 的输入范围；漏项会使构建校验失败。
API/Worker 镜像保留页面生成所需的 `site/assets/`，排除仅供主站展示的 `xiaohongshu/` 图片。
主站网页不进镜像或发布包，由服务器仓库 `git pull` 更新。

| 改动 | 需要执行 |
| --- | --- |
| 主站页面、样式、图片（教学内容版本不变） | 服务器仓库 `git pull` |
| 图谱、关联、小题、教师契约或后端逻辑 | 从同一干净提交打包，执行 `deploy`，仓库 `git pull` 到同一提交，`verify-release` |
| 当前包的内容幂等重发 | `publish-learning`；要求镜像原稿和数据库版本一致 |
| Worker 生成资源 | 更新同包 API/Worker 镜像 |
| Nginx 配置、OCR 宿主脚本 | 按各自运维说明更新 |

服务器首次替换与恢复流程见 [学习内容正式替换](learning-rollout.md)。`preflight-learning` 使用只读事务，
不初始化目录、不加载镜像、不启动服务；`prepare-release` 单独完成包校验和镜像载入。

镜像验收（独立临时 PostgreSQL 容器，不使用宿主机数据库）：

```bash
docker buildx build --load --provenance=false --sbom=false --platform linux/amd64 \
  -f deploy/product/Dockerfile.admin -t shuxueshuo-product-admin:learning-check .
docker buildx build --load --provenance=false --sbom=false --platform linux/amd64 \
  -f deploy/product/Dockerfile.app -t shuxueshuo-product-app:learning-check .
cd server
RUN_PRODUCT_IMAGE_INTEGRATION=1 \
PRODUCT_TEST_ADMIN_IMAGE=shuxueshuo-product-admin:learning-check \
PRODUCT_TEST_APP_IMAGE=shuxueshuo-product-app:learning-check \
uv run pytest tests/product/test_learning_image.py -q
```

验收会在只读、非 root 管理容器中执行 `install`、两次 `publish-learning`、`doctor`，比对结构化导出内容，
并用 API/Worker 镜像实际编译独立题页；结束后删除本轮专用容器与数据卷。这里允许未提交工作树用于本地验收，
不生成正式发布包；正式交付仍使用要求干净提交的 `build-release.sh`。
