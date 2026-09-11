# P1 内部接口与 P2 接入约定

本文件描述 Python 内部能力，不表示 HTTP、WebSocket、Celery 或浏览器页面入口已上线。
表结构以 `product-database-design.md` 为准；安装命令见 `../deploy/product/README.md`。

## 配置与上下文

`Settings.load(mode, data_dir, instance)` 读取已有私有配置；`engine(settings.url())` 创建 app 连接池。
`ProductService(engine, LocalArtifactStorage(settings.artifact_root))` 不会自行建表、迁移或初始化用户。
P2 服务端根据固定 seed 生成 `UserContext(workspace_id, user_id)`，不得信任 HTTP 请求传来的身份。
资源 ID 在 Python 内使用 UUID，HTTP 边界负责 UUID 字符串解析和错误映射。

`ProductError` 代表无效输入；`Conflict` 代表版本/执行权冲突；`Forbidden` 与 `NotFound` 用于拒绝访问；
`IntegrityFailure` 代表材料损坏或合同不一致。P2 不应把驱动异常、私有 JSON 或含秘密的原始日志直接返回前端。

## 事务入口

| 方法 | 输入和返回 |
| --- | --- |
| create_batch | 上下文及名称 → 批次记录 |
| get_problem / list_problems / get_revision / build_history | 按 workspace、owner/visibility 过滤；题目列表支持更新时间与 UUID 的游标，默认 50 条、最多 100 条 |
| reference_upload | 批次、原图字节、文件名、MIME → created/reused + item；歧义返回 ambiguous + candidate_ids |
| save_revision | 题目、基础修订和完整 domain；可附 origin_build/execution/epoch → 通过正式校验和 promotion 的修订 |
| submit_build | request_id、实际来源、基础修订、目标依赖、配置、部署及 pipeline 版本 → build_id/job_id |
| bind_requested_revision | 有效 execution/epoch → 将请求中的正式修订一次性绑定为最终修订；用于跳过或复用提取的构建 |
| acquire_execution | job、worker 和确切部署版本 → execution/epoch；预算耗尽返回已提交的失败状态 |
| heartbeat / cancel / finish_failure | 有效执行的续租、用户取消、失败或中断；均不启动下一次调度 |
| begin_stage / fail_stage | 建立运行中的 attempt；保留失败尝试与实际调用证据 |
| register_artifact | 有效执行、必填 attempt_id、字节和元数据 → 同 build/attempt 的不可变 artifact |
| commit_stage | manifest、checkpoint、完整输出列表和 attempt/reuse 来源 → 被接受的成功 attempt；普通执行必须已有 running attempt |
| record_call / record_diagnostic | 真实执行的调用审计与诊断；缺 token 用量保留 NULL |
| link_artifacts | 增加 audit/build_input/reuse 依赖，重复登记幂等 |
| finish_page / review | 按定义完成构建和页面包；追加对应版本的审查记录 |
| page_resource | 上下文、页面 ID、相对资源路径 → 经授权的 artifact、storage key、MIME |
| build_snapshot / read_events | 读取本次流程标题、阶段状态及事件水位；按 stream seq 补读 |

所有业务方法自己拥有短事务；网络和模型调用不能放入其数据库事务中。
`register_artifact` 在写文件前授权，写完后再次检查执行权；提交失败产生的孤立文件由 doctor 报告，不自动删除。

构建提交只保存 `requested_revision_id`，`resolved_revision_id` 初始为空。提取调用 `save_revision(..., origin_build_id, execution_id, epoch)`，
通过正式校验和 CAS 后保存并绑定最终版本；语义无变化时绑定原版本，不新增修订，仍检查执行权和构建归属。
有基础版本的自动提取仍记录为 `extracted`；只有人工修改记录 `manual` 和 `human_diff`。
直接使用已冻结请求修订的构建显式调用 `bind_requested_revision`，重复绑定同一版本幂等，改绑其他版本拒绝。

执行顺序为 `begin_stage → register_artifact(attempt_id=...) → commit_stage`。
普通执行的 manifest、checkpoint、全部输出及调用审计均须来自本 build 的该 attempt；旧 execution/其他 attempt 的产物不能冒用。
`commit_stage` 省略 attempt_id 时只补全本阶段唯一的 running attempt，没有 running attempt 则拒绝，不再隐式创建成功尝试。
跨构建复用必须指定 `reused_from_attempt_id`，来源须为同题已接受的成功阶段，manifest、checkpoint、完整输出映射须与来源一致；
每条产物关联填写 `reused_from_artifact_id`，调用引用标记 `reused`。存在 running attempt 时不能直接改为复用，须先明确结束该尝试。
阶段重放会比较完整输出映射；最终发布再次验证产物的执行/复用来源链。
旧记录若缺 producer_attempt 或复用来源证据，将拒绝继续复用/发布，不自动补造归属或改写已冻结记录。

`finish_failure` 同时关闭未成功的阶段，保留成功阶段；租约换代将旧 running 阶段标记 interrupted，预算耗尽关闭剩余阶段。

## 定义、阶段证据和页面包

代码中的 `PipelineRegistry` 默认提供 problem_lesson/v1；注册是部署代码行为，不开放用户编辑接口。
v1 以保守顺序依赖覆盖现有九阶段；每阶段 manifest 包含：

```json
{
  "stage_key": "source",
  "contract_version": "v1",
  "inputs": {},
  "resources": {},
  "config": {},
  "upstream": {}
}
```

四组依赖必须与该 build 的 `target_dependencies[stage_key]` 完全一致。
P1 验证文件完整性、阶段合同版本、依赖一致性和页面登记合同；P2 的领域适配器仍负责各类数学 checkpoint 的恢复认证与 typed 合同校验，
不能因为数据库接受了字节就绕过现有领域门禁。P1 的持久化 fixture 不代表执行过模型或完成了真实数学求解。
跨定义复用默认仅允许同阶段合同且依赖完全兼容，未接入的合同升级不自动推断兼容。

页面包 manifest 使用 `product-page/v1`：

```json
{
  "schema_version": "product-page/v1",
  "entry_artifact_id": "UUID",
  "assets": {"index.html": "UUID", "assets/diagram.svg": "UUID"}
}
```

页面阶段输出登记包含 `page_manifest`、`page_html`；所有页面资源必须来自本构建已接受的输出（可以是经过校验的复用产物）。
允许的页面产物类型为 page_html/page_css/page_js/page_svg/page_image/page_font，raw 和来源文件不能直接标为页面内容。
P2 根据 `page_resource` 返回信息读取文件并返回正确 Content-Type，不需要重新生成网页。

## outbox

`outbox.reserve(connection)` 使用短事务和 SKIP LOCKED 保留待发送记录；返回 publisher_token。
P2 在事务提交后向 RabbitMQ 发布，收到 confirm 后调用 `acknowledge(connection, id, token, confirmed=True)`。
未确认时传 false，记录退回 pending；过期 token 不能覆盖新的发布者。P1 没有发布循环、消息代理或数据库派工队列。

重放构建提交不会生成第二个 job/outbox；业务 worker 仍必须使用 execution epoch 防止重复消息造成重复提交。
