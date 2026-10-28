# 产品服务架构：任务、实时交互、存储与版本

内部产品服务已接入 PostgreSQL、SQLAlchemy/Alembic、RabbitMQ/Celery、HTTP/WebSocket 和版本化产物。本文描述工作台与产品构建服务；legacy Review 可独立保留。学生拍题使用同一产品实例，但执行调度、登录和私有资源由[拍题服务](search-single-host-production.md)管理，不套用产品构建队列。运行命令见[本地手册](product-p2-local-runbook.md)。

## 1. 选型与部署边界

| 职责 | 选型与边界 |
| --- | --- |
| 应用服务 | Python FastAPI；Review、工作台使用产品领域服务；学生服务复用基础设施 |
| 业务存储 | PostgreSQL；SQLAlchemy 数据访问，Alembic 管理结构迁移 |
| 消息持久化与投递 | RabbitMQ；不另实现数据库任务队列 |
| 后台执行 | Celery Worker；首版一任务运行一个构建，按冻结的流水线版本执行；当前定义为九阶段 |
| 客户端通信 | HTTP 资源操作 + WebSocket 实时事件/学生交互；现有 SSE 可在迁移期保留 |
| 产物存储 | 初期单机共享持久化目录；统一 storage key/interface，后续接对象存储 |
| 页面访问 | 产品域名下的内部版本化预览；公开发布与 CDN 后续实施 |
| 内部工作台身份 | 固定默认用户、工作空间及 owner，仅用于受限内部入口；学生接口使用独立手机号会话与归属校验 |

API、Worker、PostgreSQL、RabbitMQ 是独立进程/服务，由部署配置启动并监督重启。
初期单机部署不宣称高可用；数据库、消息代理和产物目录都使用持久化卷。
RabbitMQ 多节点容错需要 quorum queues 等配置及多数副本可用，不能由“开启持久化”推导高可用。
新增 Redis、Kubernetes 或 Temporal 不是首版前置条件。

```mermaid
flowchart TB
    U[内部工作台 / Review] <-->|HTTP / WebSocket| A[产品 API]
    A --> D[(PostgreSQL)]
    A --> F[(产物存储)]
    D --> P[事务发件箱发布器]
    P --> Q[[RabbitMQ]]
    Q --> W[Celery Workers]
    W --> G[现有九阶段生成链]
    G --> L[模型 / OCR / 页面编译]
    G --> F
    W --> D
    D --> E[持久事件转发]
    E --> A
```

发布器与事件转发是职责，不强制各部署一个服务。Review 是审查视图，不拥有另一套生成链或队列。

## 2. 一次构建请求

```mermaid
sequenceDiagram
    participant U as 工作台
    participant A as API
    participant D as PostgreSQL
    participant P as 发件箱发布器
    participant Q as RabbitMQ
    participant W as Celery Worker
    participant F as 模型与产物存储
    U->>A: 上传并提交构建请求 / request_id
    A->>F: 保存原图并校验哈希
    A->>D: 同一事务保存修订关联、job、outbox
    D-->>A: 提交成功
    A-->>U: 202 + job_id
    U->>A: 订阅任务事件，携带游标
    P->>D: 读取待发送记录
    P->>Q: 发布持久化消息
    Q-->>P: publisher confirm
    P->>D: 标记已发送
    Q->>W: 投递 job_id
    W->>D: 检查终态与执行权，记录开始
    loop 所需阶段
        W->>F: 执行并保存不可变产物
        W->>D: 提交检查点、状态与事件
        A-->>U: 推送持久化事件
    end
    W->>D: 最终状态与页面指针事务检查
    W-->>Q: 消费确认
    A-->>U: 完成事件及版本页面地址
```

- HTTP 202 表示任务和 outbox 已持久化，不表示模型已开始或队列已完成处理。
- 队列消息只携带任务标识及必要的协议版本，实际输入取自冻结的数据库/产物记录。
- 发件箱由不依赖该任务成功入队的发布路径驱动；数据库提交后未发出可补发。
  RabbitMQ 已确认但 outbox 未标记时可能重复发送，业务必须幂等。
- 配置持久队列、持久消息、publisher confirms、正确路由及未路由消息处理；
  consumer ack 与 publisher confirm 分别证明处理完成和消息接收，不能互相替代。
- Celery 显式配置延迟确认、Worker 丢失策略、长任务消费超时与有界重试。
  崩溃重投递不等于数学失败重试；永久失败须记录终态并完成消息处理，防止无限重排。

## 3. 恢复、执行权与资源控制

队列提供投递可靠性，领域服务继续负责已完成任务跳过、合法检查点恢复、目标版本与发布规则。
领取时用事务/条件更新取得执行权；以执行代次或 token 隔离旧执行，必要时用心跳判断旧执行是否失联。
重新分配执行权后，旧 Worker 的阶段提交和最终提交必须被拒绝，不能仅检查一次 running 状态。
这不是另写队列调度器，也不承诺外部模型恰好调用一次：响应返回但未保存就崩溃时，可能再次调用。

- 当前九阶段依赖和 manifest 复用现有实现；每次构建冻结 pipeline key/version、阶段定义、合同和完成规则，后续增删阶段发布新定义，不改写旧构建。
- 成功判定与阶段展示读取本次快照，不依赖全局九阶段列表；ordinal 用于顺序，依赖关系决定失效范围。详细字段及演进规则见[数据库设计](product-database-design.md#93-流水线版本与冻结定义)。
- 模型重试、Scope repair、任务重投递分别记录预算。
- 取消先记录请求，再在可安全中止的位置处理；外部调用取消尽力而为，已取消执行不能发布页面。
- 批量生成与未来实时问答使用不同队列/资源配额；provider 限流应跨 Worker 生效，不能把单进程限额当总限额。
- 学生等待回答时只保留会话状态，不长期占用 Worker；新输入触发处理，旧响应受会话版本约束。
- 生产任务绑定部署版本和有效配置，升级时旧任务排空或路由至兼容 Worker；不混用新旧代码产物。
- 旧任务按原流水线定义恢复；缺少兼容 Worker 时明确中止恢复，新定义只能创建独立子构建。跨版本复用须通过实际输入、阶段合同、资源指纹和恢复材料验证。
- Review 本地开发的源码指纹探测继续保留；生产镜像版本不能替代 prompt/配置/实际输入的依赖记录。

## 4. HTTP 与 WebSocket

HTTP 负责上传、资源读取、修订保存、重建计划和任务查询；WebSocket 负责订阅进度、
学生回答、追问与打断。业务协议独立于传输，现有 SSE 与新 WebSocket 共用事件权威。

事件至少携带协议版本、event_id、所属任务/会话、对应流的单调序号、事件类型和数据。
客户端命令携带 request_id；只在可靠接收后确认，重发命令不得产生重复业务操作。
先持久化业务变化和事件，再发送通知；重连按游标补读，快照附带事件水位，避免查询与订阅之间漏事件。
游标超过保留范围时明确返回重取快照要求。UI 按事件标识去重，不把所有系统事件假定为全局有序。

首版可由 API 读取数据库事件推进订阅；多实例时每实例都要收到其客户端订阅事件，不能把广播事件
放入只有一个实例能消费的工作队列。消息提醒只是唤醒，持久事件仍是恢复来源。
大量流式 token 可做短期缓冲并在最终保存响应；不承诺每个 token 都是永久业务事件。
重要状态、学生输入、答案和打断必须可追溯。连接中断不取消构建，缓慢客户端需限缓冲与恢复策略。

## 5. 数据与文件的权威分工

| 内容 | 权威存储 |
| --- | --- |
| workspace、题目/批次、题意修订、domain JSON、人工差异 | PostgreSQL；关系字段 + JSONB |
| job、阶段状态、执行权、请求幂等、outbox | PostgreSQL |
| manifest/依赖摘要、检查点有效性、产物登记、诊断索引与调用用量 | PostgreSQL |
| 当前页面引用、版本化人工审查、未来发布引用与授权 | PostgreSQL |
| 未来学生会话、输入、学习进度、作答和持久事件 | PostgreSQL |
| 原图/PDF/裁剪图、完整模型请求与响应/reasoning | 产物存储；密钥不进入产物 |
| 完整 Plan、typed checkpoint、LessonIR、VisualStepIR、manifest 审计快照 | 不可变产物存储 |
| HTML、固定版本 CSS/JS、SVG、未来音频 | 不可变产物存储 |
| 代码、prompt、Schema、Spec、模板、数据库迁移 | Git；构建记录内容指纹 |

数据库登记 artifact_id、run/stage/type、storage_key、sha256、size、content_type、schema_version、
归属/可见性与创建时间。结构化索引用于查询，完整快照用于恢复；二者有哈希/版本关联，不能各自可编辑。
例如题意修订以数据库为准，导出 JSON 是构建审计副本；运行时 checkpoint 以登记的不可变产物为准。

```text
sources/{source_id}/original.png
runs/{run_id}/solver/response.json
runs/{run_id}/solver/checkpoint.json
runs/{run_id}/lesson/lesson-ir.json
pages/{build_id}/index.html
pages/{build_id}/assets/...
```

这些是 storage key 示例，不是数据库中的机器绝对路径。初期数据目录独立于 Git 和容器临时层，
API/Worker 共享挂载；多主机前切换共享对象存储。先写产物、校验完整性，再提交数据库引用。
失败遗留文件按保留期和引用检查清理；删除不能破坏历史运行/发布/复用依赖。备份恢复联合验证数据库与产物哈希。

## 6. 课程与学生服务

内部构建发布不可变的版本化页面，访问仍受工作空间约束。公共图谱和专题课程见[图谱维护](public-knowledge-graph-stage4.md)，学生登录、练习和节点证据见[个人图谱数据设计](student-knowledge-graph-data-design.md)。

拍题的公共题面身份与私有照片、课程、历史分离；当前课程按私有提交生成。公共课程包及跨设备拍题作答同步属于后续范围，见[共享题库设计](shared-problem-library-and-student-learning-design.md)。

## 7. 数据库与产物格式版本

采用 SQLAlchemy + Alembic；迁移文件进入 Git，数据库通过 alembic_version 记录结构版本。
每次结构变化新增迁移，不改已部署历史；自动生成候选需检查改名、约束、索引和旧数据处理。
部署由单独迁移步骤执行，不让所有 API/Worker 启动时竞争改表。使用扩展、回填、切换、收缩的兼容顺序；
长任务升级期间保持旧字段兼容，大批量回填可单独执行。降级脚本不能替代数据备份。

首次从空库升至 head，仅创建默认用户 `internal`、默认工作空间 `default` 及 owner 成员关系，其他业务表为空。
不迁移旧 SQLite 记录或旧产物，不实现历史导入程序；旧库和文件留在原处。
种子初始化独立于 Alembic，重复执行保留原 ID 和新业务数据；首次空表、种子幂等及 PostgreSQL 并发必须验收。
后续有结构版本变化时，验证上一 revision 含新系统数据的升级；Alembic 继续负责结构演进和 head 检查。
数据库结构 revision 与 domain/Plan/checkpoint 的 schema_version 分开管理，旧数学产物不因改表自动升级。

## 8. 模型与 Plan 多候选

提取 provider 配置化，保留 Schema、数学合同、promotion、OCR 与 Bundle；DeepSeek 与豆包用相同原图对照。
截至 2026-09-10 的选型记录，官方推荐 `deepseek-flash`（V4.1-Flash），旧 `deepseek-v4-flash` 别名已转向新模型；
实施时核对真实 endpoint，尤其是代理映射。请求名称、实际返回名称、供应商版本信息与配置版本分别记录，
供应商未提供固定模型标识时明确限制。切换默认模型后重新验证真实生成链。

Plan Pass 1/repair 维持 low thinking，讲解 disabled；提取配置独立验证。图片不进入后续每轮 Plan prompt。
默认 N=1，候选机制支持有界 N=2/3。每份候选独立编译与数学验证，先过门禁再按可解释质量指标选一个进入下游；
不合并状态、不按答案投票、不向其他候选追加完整历史。正确性冲突须诊断；记录候选输入、结果、排名及成本。
首个通过即停与完成全部后选优是不同策略，必须明确返回采用哪种策略，不将前者称为真正 Best-of-N。
传输、Scope repair 与候选数量共用明确总预算。缓存和全题默认 N=3 不是前置条件。

## 9. 选型依据

- [RabbitMQ 确认机制](https://www.rabbitmq.com/docs/confirms)与[quorum queues](https://www.rabbitmq.com/docs/quorum-queues)：消息持久化、发布与消费确认。
- [Celery Tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html)：延迟确认、幂等与 Worker 丢失行为。
- [事务发件箱](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)：数据库变更与消息发送的一致性。
- [WebSocket](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API)：双向实时传输；业务恢复仍由应用协议实现。
- [PostgreSQL JSONB](https://www.postgresql.org/docs/current/datatype-json.html)：结构化文档查询与索引。
- [Alembic](https://alembic.sqlalchemy.org/en/latest/)与[自动生成边界](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)：数据库结构版本管理。
- [DeepSeek 官方型号](https://api-docs.deepseek.com/quick_start/pricing/)：实际接入时重新核对版本与能力。

Temporal 是未来长期工作流的备选，不与 Celery 同时引入；当前复用现有阶段链与恢复机制优先。
