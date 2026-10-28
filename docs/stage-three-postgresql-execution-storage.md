# 阶段三执行器：PostgreSQL 存储实施说明

阶段三执行器、学生拍题与离线 CLI 共用产品 PostgreSQL。运行目录提供冻结输入和调试导出，数据库是事件、状态、预算及恢复权威。

## 1. 单一权威与范围

- 不再创建或读取阶段三 `events.sqlite3`，没有 SQLite fallback，也没有双写后端。
- 迁移 `0014_lesson_execution` 建立共享 `lesson_*` 表，以 `run_id` 隔离运行，不为每次运行新建 schema。`lesson_runs.identity` 固定运行身份，所有子表以运行外键级联。
- 数据包括事件与水位、提交幂等回执、路线检查点、数学步骤和哈希摘要、目标状态、选择片段、交互状态与卡片、阶段四交接与 QA，以及计算预算、占用和尝试回执。
- 运行目录仍保存冻结输入、`run.json`、调试导出和 supervisor 文件回执。`checkpoint.json`、`events.jsonl` 和导出 manifest 是可读视图，不是执行恢复权威。
- 旧 SQLite 运行只作历史归档，本轮不导入 PostgreSQL，不用旧 JSON 重建可写执行记录。只有本轮创建的 PostgreSQL 运行可继续恢复执行；保留旧输出并使用新目录发起新的离线运行。

## 2. 事务、隔离与生命周期

`storage_context(db, submission_id=None, clock=None)` 显式绑定产品连接、可选私有提交及生命周期时钟。学生 API、后台工作线程和 WebSocket 读取各自绑定提交范围；已有 `EventStore` 保存构造时的上下文，避免线程切换落回其他实例。无显式上下文的离线调用从现有 `Settings` 取得 PostgreSQL 配置，连接失败直接报错。

Web 请求通过可恢复的 ContextVar 强制要求执行器绑定具体提交，后台线程复制该约束；正式本地服务入口另设进程标志 `PRODUCT_EXECUTION_STORAGE_CONTEXT_REQUIRED=1`，使 spawn 子进程同样不能回退默认实例。缺少绑定或只有无提交的 CLI scope 时直接报 `events.storage_context_required`（HTTP 503 / WebSocket 1011），不尝试创建默认引擎。独立 CLI 未启用 Web 标志时保留原默认配置行为。

`EventStore.transaction(write=True)` 只包围短数据库变更，不覆盖代数计算、子进程等待或模型调用。搜索运行写事务采用页面、提交、公共题目、运行的锁顺序，页面使用 `FOR SHARE`，提交与运行仍使用排他行锁。这样同页不同题目的课程写入可以并发，删除和清理的页面排他锁仍会等待；检查提交仍存在、产物未到期且公共题目未停用，提交前再次检查 30 天期限。同一运行行锁串行化水位、幂等回执与预算更新。只读快照使用 PostgreSQL `REPEATABLE READ`，保证游标、物化状态与事件来自同一个已提交视图。

运行的提交归属不可变。无提交 scope 的 CLI 只能访问独立 CLI 运行，不能凭 `run_id` 读取学生私有运行；其他提交的 scope 同样不能访问。已打开的 store 还校验运行身份与创建代次，拒绝采用同 ID 后来重建的记录。

- **主动删除私有提交**：`lesson_runs.submission_id` 外键随提交级联删除，事件、预算和交接数据一并消失；删除后的后台写入失败，不能重建运行。
- **私有产物满 30 天**：清理事务删除该提交的执行运行及子表；已关联的规范公共题目和历史关系可以保留，不能继续恢复旧私有课程。
- **公共题目停用**：拒绝该题私有运行的新读写，不因存量 store 已打开而绕过状态检查。
- **来源整页满 24 小时**：保持第一期规则，不提前删除仍在 30 天期限内的独立裁剪提交与执行数据。主动删单题也不提前删除来源整页。

文件物理清理继续通过第一期的 pending cleanup 队列、生命周期锁和读取锁完成；数据库级联删除不是文件删除的替代品。

WebSocket 无新事件时指数退避，最长 3 秒；有新事件恢复 150 毫秒续读，发送前重验会话与归属，客户端 ping 不得加速数据库轮询。真实 PostgreSQL 的可控时钟回归中，空闲及完成态在 30 秒内各执行 13 次事件读取，而非约 200 次；撤权检查仍不超过 3 秒。

## 3. 迁移与本地命令

升级前停止所有连接目标实例的 web、worker 和 cleanup，按既有本地备份、迁移、自检流程操作。下列为隔离实例示例，不是线上部署指令：

```bash
./deploy/product/manage.sh --mode local \
  --data-dir /private/tmp/sss-search-acceptance --instance search-acceptance --port 55444 deploy
./deploy/product/manage.sh --mode local \
  --data-dir /private/tmp/sss-search-acceptance --instance search-acceptance --port 55444 doctor
```

数据库版本须达到 `0014_lesson_execution` 或更新版本。迁移同时将新表加入应用权限、自检和备份清单；运行时不执行 DDL。应用只允许更新必要状态列，运行身份和已提交数学证据不授予更新权限。

阶段三 CLI 的数据库参数属于主命令，必须放在 `run`、`resume`、`events`、`serve`、`batch`、`report` 等子命令之前。在 `server/` 目录执行：

```bash
uv run --offline python -m shuxueshuo_server.graph_lesson.stage_three.cli \
  --data-dir /private/tmp/sss-search-acceptance --instance search-acceptance \
  run --input /absolute/path/to/stage-two-result.json --output /absolute/path/to/new-run

uv run --offline python -m shuxueshuo_server.graph_lesson.stage_three.cli \
  --data-dir /private/tmp/sss-search-acceptance --instance search-acceptance \
  events --run /absolute/path/to/new-run --after-seq 0
```

未传数据库参数时沿用产品默认持久目录及实例，不自动创建数据库。测试和录制验证必须显式指定隔离实例，不能用日常数据库替代。

## 4. 真实 PostgreSQL 离线测试

以下测试需要已迁移的独立 PostgreSQL，缺少配置直接失败，不以跳过视作通过。示例在 `server/` 执行：

```bash
PRODUCT_TEST_DATA_DIR=/private/tmp/sss-search-acceptance \
PRODUCT_TEST_INSTANCE=search-acceptance RUN_LLM_INTEGRATION=0 \
uv run --offline pytest -q tests/search/test_execution_storage.py \
  tests/solver/test_graph_stage_three_events.py \
  tests/solver/test_graph_stage_three_postgres_budget.py
```

搜索数据库测试逐例建立临时 schema，并复现完整迁移、外键和应用权限。阶段三测试在隔离实例中按测试模块建立 `test_*` schema，清理用例新增运行，保留模块级录制 fixture。测试用 `PRODUCT_TEST_SCHEMA` 将同一 schema 传给 spawn 子进程；该配置只允许同时显式指定测试数据目录和实例，且目标执行表必须已经存在，不能回退到 public 的旧运行。

重点覆盖原子回滚、并发幂等、连续水位、读取快照一致性、预算中断恢复、跨 run/提交隔离、删除与后台提交交错、到期边界及停用拒绝。历史阶段三文档中的测试数字仍只代表当时版本。

专项还发现并修复两处运行边界：路线 advisory lease 使用独立 AUTOCOMMIT 连接并脱离应用连接池，避免持有多条路线时耗尽池；本地计算子进程被并发回收时，等待退出码发布后再关闭 `Process`，避免恢复过程中误报仍在运行。均有确定性回归，不靠延长计算预算或忽略异常规避。

## 5. 仍是本地执行，不等于分布式改造

执行状态与预算账本统一到 PostgreSQL，但运行目录、冻结输入、supervisor 回执、导出锁及搜索文件生命周期锁仍依赖当前主机文件系统。路线预算除本机 `flock` 外，也使用 PostgreSQL session advisory lease，阻止同一运行的相同路线从另一个目录并发占用；这不等于完整的跨主机 worker 协调。

本轮不增加远程任务队列、共享对象存储、跨机 supervisor 恢复、自动重试付费调用或线上部署。

私有拍题文件、执行数据、原始到期期限与删除权威必须一致恢复。当前 v2 备份及恢复已包含对应规则，详见[备份恢复契约](search-backup-restore-local-acceptance.md)；独立 CLI 运行目录需自行一致备份。稳定锁文件不能在运行中按 mtime 或记录缺失直接删除。

## 课程可用性

持久状态为 `ready` 仍须检查匹配提交的 PostgreSQL 运行、原始题目、裁剪元数据、题图、冻结输入及阶段结果。材料缺失时返回 `unavailable`，不在读取时重建；到期和停用状态优先。详情保留公共题面并提供重新拍照；start/resume/重跑不得绕过可用性或生命周期检查。同题较旧的可用课程与最新失败状态分别表达。
