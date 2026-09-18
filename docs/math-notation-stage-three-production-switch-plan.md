# 阶段三生产切换计划：沿用九阶段流水线

日期：2026-09-18

本计划把数学参数表达直接接入现有生产流水线。当前没有线上用户和需要兼容的历史生产 run，因此生产默认直接使用数学参数表达；旧 `source-ref` 只保留给历史录制回放和回归测试。除 solver 阶段的 Method 参数编码外，不重写九阶段流水线，不引入新的计划协议，不改变 Scope、Goal、依赖、状态、前置条件、分支、retry、事务或页面生成规则。

## 一、九阶段保持不变

旧路径的阶段顺序和名称继续作为唯一生产编排：

| 顺序 | 阶段 | 生产职责 | 本次变化 |
|---:|---|---|---|
| 1 | `source` | 原始上传图、规范化图、来源身份和版本 | 不变 |
| 2 | `observation` | OCR/版面观察，生成 Observation Context | 保留阶段；默认使用 `fast-pass`，见下文 |
| 3 | `extraction` | 多模态题意抽取、校验、repair，生成 VerifiedProblem/Extraction Context | 不变 |
| 4 | `projection` | 生成 Solver ProblemIR、Planning Context 和授权目录 | 不变 |
| 5 | `solver` | Planner 选择 Method、绑定参数、执行并生成 VerifiedFunctionalPlanExecution | **仅在这里切换 Method 参数编码** |
| 6 | `evidence` | 从已验证执行生成 ExplanationSnapshot/AnnotatedTeachingPlan | 不变 |
| 7 | `lesson` | 生成或确定性 fallback 讲解，生成 LessonIR | 不变 |
| 8 | `visual` | 生成 VisualStepIR、图形和交互 JSON | 不变 |
| 9 | `page` | 校验并编译最终 HTML 课程页 | 不变 |

阶段 ID、阶段 manifest、输入引用、输出 artifact 名称、版本指纹和从指定阶段重跑的规则继续复用现有实现。数学参数的原文、规范引用和来源映射作为 solver 证据保存，不改变后续阶段的输入类型。

## 二、OCR 快速通过策略

本次切换不把 OCR 重新设计成新阶段，也不删除 `observation` 阶段。默认配置增加一个明确的观察模式：

```text
observation_mode=fast-pass
```

`fast-pass` 的行为：

1. 仍完成图片规范化、来源哈希和 observation manifest。
2. 生成一个合法的最小 Observation Context，明确记录 `ocr_status=skipped_fast_pass`、输入图片引用、版本和诊断。
3. 不伪造 OCR 文本，不把空结果标记为 OCR 成功；下游只使用实际存在的图片/观察字段。
4. `extraction` 继续沿用现有 image/context 输入和校验边界；如果某题确实需要 OCR 字段，按现有阻断规则失败并留下原因。
5. 真实 OCR 未来接入时只替换 observation adapter 和配置，仍输出同一 Observation Context 契约，不修改后六个阶段。

正式 OCR 模式使用独立 `.venv-ocr` 和现有 OCR manifest；`fast-pass` 与真实 OCR 的产物必须有不同的模式和版本标识，不能互相冒充或静默复用。

## 三、solver 阶段的最小切换

生产配置固定指定：

```text
argument_encoding=math-expression/v1
```

数学表达入口进入同一个 `functional-plan-content/v2`、同一个 `FunctionalPlanContentCompiler`、同一个 `functional-scope-repair/v1` 和同一个执行器。数学表达只在参数绑定层转换为现有 SourceRef；保存、恢复、检查点和提交状态均使用规范引用。

生产路径必须保留：

- 数学原文、规范引用、绑定来源和诊断的关联；
- 原有 retry 次数、开放 Scope、锁定结果、重算范围和事务边界；
- 原有 `answer_from`、`{step_id, return}`、output identity 和 state version 规则；
- 失败时按原错误分类阻断，不能用 fallback 猜对象、补题设或改写父 Scope 状态。

历史 `source-ref` 计划只能在明确的录制回放/回归配置中启用，不能由生产输入自动猜测编码。

## 四、正式产品接入步骤

### 1. 配置

- 将生产默认设为 `argument_encoding=math-expression/v1`；不增加 workspace 灰度开关和用户级双轨逻辑。
- 在运行配置 artifact 中记录 `argument_encoding`、`observation_mode`、代码指纹、Prompt/Schema/Capability 版本。
- 历史计划明确按 `source-ref` 读取，生产新 run 统一按数学表达读取。

### 2. 运行记录与候选准入

- 在现有 run/stage/artifact 记录数学原文、规范 content、binding audit、solver 诊断和最终执行证据。
- `solver` 成功只表示执行完成；只有 `evidence`、`lesson`、`visual`、`page` 全部成功才开放课程页。
- `current_product_admission` 只有在正式数据库、API 和权限流程完成后才改为 true。

### 3. 九阶段 worker 接线

- 保持现有 `source → observation → extraction → projection → solver → evidence → lesson → visual → page` 调度。
- solver worker 从 run 配置读取 `argument_encoding`，其他 worker 不感知数学参数编码。
- 从任意阶段重跑继续使用现有依赖 manifest；重跑 solver 及后续阶段时不重新解释已保存的数学原文。

### 4. API 与页面

- 详情 API 展示参数编码、OCR 模式、阶段状态、诊断和 artifact 版本。
- 课程页只读取 page 阶段产物，不直接读取数学原文或内部 SourceRef。
- 页面失败时不展示旧页面，保留失败 run 和可重跑起点。

## 五、切换门禁与直接上线

### 离线门禁

- 五题人工候选和五题真实候选双编码规范计划与执行审计等价。
- Scope retry、状态读取、返回身份、闭包、事务和页面回归全部通过。
- JSON/DSML 尾、数学绑定失败、歧义、不可见条件、父状态重写和 OCR fast-pass 反例均有测试。

### 直接上线步骤

1. 冻结当前代码、Prompt、Schema、Capability、九阶段配置和验收输入。
2. 通过离线等价性、既有机制回归、页面回归和四题/和平一模真实重跑门禁。
3. 将生产 solver 配置直接设为 `argument_encoding=math-expression/v1`。
4. 运行首个完整九阶段样例，确认 `source` 到 `page` 的 artifact 和 manifest 连续完整。
5. 后续新 run 统一走数学表达路径；旧路径只用于录制回放和问题定位。

没有线上用户时不做 Shadow、Canary 或用户级回退。若上线后发现阻断问题，回退部署版本并修复后重新通过门禁，不把旧路径作为生产双轨长期维护。

每个阶段分别统计成功率、阻断原因、retry 次数、prompt/completion/total token、耗时和页面生成率。未知 provider 响应不计为成功，也不自动补发付费调用。

## 六、验收结论的边界

当前录制/冻结验收已经证明：数学表达入口可以经过原有执行器生成 ExplanationSnapshot、LessonIR、VisualStepIR 和 HTML。最新真实 Planner 重跑证明求解和执行链路可用。

这仍不等于正式产品切换完成。只有九阶段 run 由产品 worker 真实驱动、候选写入正式数据库、API/权限可查询、后续四个教学/页面阶段成功后，才将 `current_product_admission` 改为 true。

## 七、未来 OCR 接入

未来只新增或替换 `observation` adapter：

- 保持 Observation Context、manifest 和依赖输入契约；
- 以真实 OCR 版本、模型指纹和来源 hash 生成新 observation artifact；
- 从 observation 开始按现有依赖重跑后续阶段；
- 不修改数学参数绑定、solver 执行器和页面协议；
- OCR 失败时保留 fast-pass/真实 OCR 的模式和诊断，不把一个模式的产物伪装成另一个模式。
