# 产品 P1 安装与管理

P1 提供 27 张产品表、不可变产物存储和内部事务接口。真实上传 API、页面 HTTP 路由、队列和 Worker 在 P2 接入。
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
