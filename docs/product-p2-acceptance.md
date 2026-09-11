# P2 本地实现与验收记录

日期：2026-09-11。本轮实现产品 HTTP/WebSocket、原生 RabbitMQ/Celery、九阶段执行适配器、Review 和本地服务生命周期。服务器 Docker/生产部署继续延后。

**结论：P2 本地基础实现与离线/队列验收通过，唯一真实单题构建因抽取校验与超时失败，未生成网页；P2 暂不标记完整通过，P3 不开始正式接线。**

## 已执行验证

| 项目 | 实际结果 |
| --- | --- |
| PostgreSQL + RabbitMQ 全量产品测试 | **74 passed in 42.45s**；真实 PostgreSQL/RabbitMQ，无跳过、无付费模型 |
| 旧 Review / 修订 / 依赖 / 重建 / 数学证据回归 | **78 passed in 55.60s**，无付费模型 |
| 前端单元测试 | **114 passed，17个测试文件**，含新增产品代理身份/路径/请求键测试 |
| 前端 lint / TypeScript / production build | 全部通过；生产构建未作为服务器部署 |
| 有效离线完整链路 | 来源/观察/题意使用有效领域 fixture；recorded planner 实际求解；真实 evidence/lesson fallback/visual/HTML 编译与数据库提交 |
| 检查点恢复 | 新临时目录恢复所有九阶段，正式 typed 校验；跨构建复用前八阶段，仅页面重编译；人工修订重校验不调用抽取 provider |
| 真实消息故障 | confirm 丢失重复发布、旧 publisher token 拒绝；RabbitMQ 重启后持久消息仍存在；真实 Celery Worker 被终止后新 epoch 接管，旧执行被拒绝 |
| 预算及取消 | execution delivery 上限；语义/网络预算跨 execution 持久化；缺少 usage 保持NULL；取消撤销执行权 |
| 原 P1 含业务库 | `0002_product_runtime_indexes`；保留 **138 builds、468 artifacts**；Alembic check：No new upgrade operations detected |
| 隔离服务完整生命周期 | 首次启动、重复启动（原PID保持）、doctor、停止、重新启动均通过；停机保留PG及所有数据 |
| 含空格正式路径 | `$HOME/Library/Application Support/shuxueshuo/local` 下原生 PG/RabbitMQ/API/Worker/publisher/Next 启动成功 |
| 浏览器离线预览 | 九阶段结果、授权 iframe、审查通过及刷新恢复均验证；旧静态导航残留已在产品编译模式修正 |
| 正式模型前预检 | 指定南开原图完成真实本地 source + Paddle observation；无付费模型调用 |
| 正式运行自检 | PostgreSQL17.10、0002、角色/文件/原子存储、broker、四进程版本及双心跳通过；无过期租约和 outbox 积压 |

隔离实例 `/private/tmp/shuxueshuo-p2-acceptance`：PostgreSQL55440，RabbitMQ5673/vhost `product_p2-test`，API8100，前端3100。故障只发生在测试进程和专用节点，不操作正式数据。原 P1 验收实例端口55438。

RabbitMQ 实测4.3.2、Erlang28.5.0.2、Celery5.6.3。首次 Worker 故障测试发现 RabbitMQ4.3 拒绝 Celery 未使用的临时 remote-control 队列；关闭 remote control 后真实 Worker 测试通过，不启用弃用特性，不改变数据库取消合同。

有一轮 API 测试与实例的正常停写窗口重叠，收到预期503；测试随后隔离自己的 HTTP 生命周期标记并增加维护窗口断言。不能把该轮结果记成通过。另有源码序列化/typed visual恢复/页面元数据路径问题均由离线测试发现、修复后重跑。

## 唯一真实构建

通过正式 Review 选择 `internal/source-images/tj-2026-nankai-yimo-25/source-page-01.jpg`，仅提交一次：

- problem：`3b3afa66-26d3-4848-ad02-2d83f2995c9b`
- build：`46ff6e5f-4d3c-49a2-be1e-02a98ec34160`
- 入口：<http://127.0.0.1:3000/review/runs/46ff6e5f-4d3c-49a2-be1e-02a98ec34160>
- 部署快照：`141c2bfff1143436dea442c5521a13f07acf7cf38a4c3973ce3880426532a4f1`
- 提取：`doubao-seed-2-1-turbo-260628`，语义/网络3/6；Solver：`deepseek-v4-flash`，3/6；讲解：同一DeepSeek，1/2；SDK自动重试为0。

最终状态 **failed / extraction.blocked**。来源与OCR成功；抽取失败，后续阶段关闭，没有创建题意修订或页面。没有追加构建或绕过校验。

| 抽取尝试 | 实际结果 |
| --- | --- |
| 1 | 返回成功（49.187秒），领域校验失败：重复事实 `extraction.problem_fact_redundant`；遗漏“取值范围（直接写出结果即可）”的题干要求 `extraction.problem_text_incomplete` |
| 2 | 修复返回成功（166.500秒），重复事实已消除，题干完整性仍未通过 |
| 3 | 修复请求及其一次网络重试均超时（总363.543秒），`extraction.multimodal_provider_timeout` |

共3次语义尝试、4次实际网络请求、1次 execution。三条调用审计的 usage 均为NULL；不据此声明免费或零费用。提取 provider 在首个完整JSON处结束流，前两次未得到usage尾包；超时请求也没有完整用量。

三份校验产物 ID：`eb32bbe7-f220-46bc-a250-599c39f86863`、`74c44c91-6b71-497a-87d9-14d1a700a093`、`b3782e1e-ba11-4ceb-bcbb-37279e31c278`，可在该构建高级审查区读取。Solver、讲解模型均未调用。真实“图片→网页”闭环和本题页面交互未通过，不用离线 fixture 替代这一结论。

终态后修正了事件 `stage_key` 被P1启发式脱敏误处理，以及失败阶段的材料名称投影；追加回归后74项通过。旧不可变事件保留原样，状态以构建快照为准。后续服务版本与本次真实构建快照不同，不宣称重新跑过真实模型。

## 正式升级与数据边界

先正常断开 DBeaver 的两个空闲连接，备份成功后执行迁移，再恢复其原连接。升级前备份位于 `local/backups/cf2a15501cbe4307838e28441c21e676`，revision0001、零登记产物。未重置密码、seed或原数据，未修改旧SQLite/运行目录。

产品离线执行测试把 `ReviewStore`、`Versions` 初始化替换为立即失败，完整生成和恢复仍通过，确认适配路径不会依赖旧持久化层。

最终正式服务版本为 `fd785e06c888c49254c1ae2f98079c29a370f0538e4a806ed552359e687bfe1c`。重启后 doctor 通过：48 个登记产物完整，无孤儿文件、过期租约或 outbox 积压；API、前端、Worker、publisher 均运行，双心跳正常。

通过正式浏览器再次上传同一原图，界面显示“已引用已有题目，没有重复生成。”数据库保持1个 problem、1个 build、1个 job、3条 model_calls、0个 page_build、0个 revision；仅批次和批次项增至各2条。本次重复上传没有新增模型调用。

验收结束后，已停止两个隔离验收实例的 PostgreSQL 和测试 RabbitMQ，保留测试数据。正式本地实例继续运行，DBeaver 原连接已恢复。

## 尚未验收的环境

- Linux 本地安装与服务器 Docker 未执行，不记为通过。
- 本轮不部署 Nginx、服务器 app/Worker 或公共页面入口。
- 真实抽取失败；下一步需离线分析题干完整性修复与provider超时，再经用户明确授权开展新的付费验收。达到完整本地验收条件后才能把 P2 标记完成并正式进入 P3。

交接文档：[接口合同](product-p2-interfaces.md)、[本地运行手册](product-p2-local-runbook.md)。
