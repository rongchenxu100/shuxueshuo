# 阶段 F2：产物成本收敛

日期：2026-09-28。按[架构计划](scoped-proof-search-architecture.md)第 14.6、15 节实施。默认证明协议仍为 `bound-conditions/v1`，本阶段不切换默认、不改变 checker、证明证书、Method 或 Planner 提示词。F3 全量验收与清理另行实施。

## 实现边界

`DebugArtifactJournal` 按一次 solve 管理产物；键为语义 attempt、产物角色和内容版本。新版本形成独立 JSON 快照与 SHA-256 文件；再次提交相同内容时，只作内容比较，跳过 JSON 快照转换、序列化和文件写出。比较递归检查可变后代，不依赖对象地址、浅层 frozen 声明或调用方自报 hash。同内容重建对象、原对象嵌套修改、回到本次 solve 已发布过的版本均有测试。

这里保留了内容比较遍历，并不宣称每次发布为 O(1)。`authority_payload()` / `to_payload()` 等领域投影仍负责生成公开证据结构；本阶段消除写入器层的重复完整 JSON 转换，序列化及物理写入。未建立按对象身份缓存领域投影的机制。相同字节的完整产物已跨角色、跨 attempt 共享版本文件；递归嵌入的上游证据、不同内容文件内部的重叠片段仍存在，共享证据 DAG 属于后续协议优化。

Orchestrator 在 requested、received、compiled、completed/失败事件发生时即时发布。返回后的发布仍比较实际内容，不凭 completed 状态或 attempt 编号跳过：若内容未变则复用版本，若内容变化则发布新版本。未接入 observer 的 provider 也走同一发布路径。新增外层 Runtime 错误仍写出，并记录到 canonical index 的 `runtime-error` 角色。比较缓存按 solve 隔离，结束时清空，只留下计数；没有跨请求的全局缓存，也不授予数学证明复用权限。

## 文件与历史

- `.versions/<sha256>.json`（文本为 `.txt`）保存每个内容版本；跨角色和 attempt 的相同字节只写一次，角色语义仍在 alias 和 index 中。
- 原有 `attempt-N.<role>.json` 保留为最新版的硬链接，原子替换，不二次写入完整内容。版本文件设为 `0444`，防止普通截断式误写；这不是防特权进程篡改的安全边界。
- `attempt-N.evidence-index.json` 指向具体版本和 SHA-256，保留不可用角色及原因。索引最后发布。
- `attempt-N.evidence-history.json` 保存各阶段索引的版本引用，包括失败阶段；后续阶段和后续 attempt 不覆盖它们。重新打开 journal 时保留已有历史。
- 文件写入失败不把版本记作已发布，旧索引/旧产物仍可读，重试可继续发布。同目录硬链接不可用（EXDEV / ENOTSUP / EOPNOTSUPP / EPERM）时采用临时文件复制再原子替换，仍保留全部版本。其他 I/O 错误和内容不匹配继续显式报错；本次不将审计失败改为静默忽略，磁盘写满等仍可能中断求解。

每次独立 solve 应使用新的输出目录（authoring harness 已强制如此）。历史目录里的文件是诊断数据，不是 Runtime 权限。恢复仍须外部认证授权、证据签名及独立 checker；文件存在或 SHA 匹配均不能代替数学验证。

## 平台入库（评审修订）

生产和评审入口均通过 `DebugJournal` 的平台模式发布：版本 JSON 可被 `rglob("*.json")` 收集，发布索引前还会递归发布其引用的版本，因此多次阶段更新发生在一次扫描间隔内也不会漏掉失败证据。hash-only 共享文件统一归为辅助 `validation`；逻辑角色由原名（raw / input / output 等）和索引维护，不从哈希推断。

平台模式保留未修改 JSON 的原始字节，紧凑模式不会因平台重新序列化而 SHA 失配。继续使用各平台原有的结构化脱敏函数；若脱敏改变内容，则发布脱敏后的版本，并递归更新引用路径与 SHA。此时平台存储哈希有意不同于本地原始哈希，所有平台内引用必须闭合。源引用的 SHA 不匹配或存在环时拒绝发布，不伪造校验结果。旧的普通 watcher 调用仍返回解析后的对象，只有两个实际平台入口选择字节发布。

新增测试覆盖跨角色共享、只读位、硬链接不支持、`0.0 → -0.0`、平台真实存储中三阶段历史与每条引用的 SHA、脱敏后重哈希，以及产品入口的脱敏规则。已有大归档保留为评审前测量材料，不再增加一套大归档。

## 两种模式

| 模式 | 内容 |
| --- | --- |
| `full_diagnostic`（兼容默认） | 完整 canonical 审计角色、阶段历史、旧 prompt/payload/reconciliation 等调试视图，缩进 JSON |
| `compact_audit` | 同样完整的 canonical 审计角色与阶段历史，去掉重复的旧调试视图，紧凑 JSON |

两种模式都保存请求、原始响应、provider 请求/响应/元数据、失败诊断、候选与编译计划、事务、完整 checkpoint、verified execution、复用记录。模型未提供的内容仍显式标记 unavailable。`raw-response.txt` 在两种模式均保留，已有响应回放工具可继续使用。

配置入口：`RuntimeOrchestrator(debug_artifact_mode=...)`、`SolverRuntimeConfig.llm_debug_artifact_mode`、`SOLVER_LLM_DEBUG_ARTIFACT_MODE`，以及 CLI `--llm-debug-artifact-mode`。q30 authoring 工具提供 `--debug-artifact-mode`。紧凑模式消费者应读取 evidence index，不能假定所有旧调试文件都存在。默认模式不变。角色裁剪适用于 scope-native 审计协议；低层 ProblemIR debug 路径尚无 canonical 审计索引，仍保留原调试角色，仅使用相应 JSON 格式和内容去重。

## 验证与成本

记录见[验证目录](validation/scoped-proof-search-stage-f2/README.md)。同一冻结 q30、显式 v2、真实五段 Method 数学执行，优化前及两种输出模式各三次；无真实模型调用。独立报告 solve、产物阶段、冷回放、热校验与 Runtime Retry，不把模型等待混入本地成本。

比较缓存及历史测试覆盖内容不变、可变后代修改、同内容新对象、版本返回、写入失败与重试、模式等价、标量子类、跨 attempt 历史和真实 Runtime 拒绝后修复。另直接从实际输出 checkpoint 提取完整证明闭包，使用单独冻结的授权，在禁用新旧搜索的独立进程中回放。

本阶段没有把“关闭调试”作为优化，也没有扩大证明预算。既有 q30 快照内容与 hash 保持一致。最终计数、耗时、代码指纹和复现命令以验证目录为准。
