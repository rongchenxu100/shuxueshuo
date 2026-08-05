# Functional Planner 路线图

## 总目标

建立一条从题目来源到学生课程页的可追溯主链：

```text
图片 / PDF / 人工题目
  -> source fingerprint
  -> ProblemExtractionContext
  -> ProblemIR
  -> PlannerStateContext / FunctionalPlan v1
  -> typed reconciliation + transactional execution
  -> ExplanationSnapshot
  -> LessonExplanationContext
  -> DiagramContext / AnimationContext
  -> validated lesson page
```

当前优先级是先打通完整链路。Best-of-N 属于可靠性优化，在端到端质量和成本可度量后实施。

## 当前生产架构

Solver 只有一个 LLM 规划协议和一条权威执行路径：

```text
ProblemIR
  -> FunctionalPlan v1
  -> typed identity / allocation / placement / finalization
  -> direct Function/Macro compiler
  -> transactional execution
  -> runtime-grounded symbolic closure
  -> Context / retry / Explanation provenance
  -> PlannerOutput
```

StepIntent LLM 协议和 Functional 投影桥已经退役。`StepPlan`、`MethodInvocation`、
`RuntimeContext`、`InvocationExecutor` 仍是内部执行结构。

## 阶段状态

| Track | 状态 | 结果 |
| --- | --- | --- |
| A：Functional parity | `COMPLETE` | authored fixture、真实样本、分层指标与 parity 门禁 |
| B：Typed state authority | `COMPLETE` | MathObject、StateVersion、placement、finalizer、retry 与 typed consumer 权威 |
| C：Transactional execution | `COMPLETE` | 逐 call 事务、binding、symbolic closure 与 provenance 消费 |
| D：Functional default | `COMPLETE` | FunctionalPlan 成为唯一规划协议，legacy StepIntent 已删除 |
| F：Problem extraction | `NEXT / IN PROGRESS` | 图片/PDF/网页来源转换为 validated ProblemIR |
| G：Post-solver contexts | `NEXT / IN PROGRESS` | Explanation、Diagram、Animation 与课程页 Context 链 |
| E：End-to-end optimization | `PENDING AFTER F/G` | 最终 artifact cache、增量重建与条件式 Best-of-N |

已完成阶段的逐轮 findings、迁移模式、source fingerprint 和 batch 流水不再保留在主文档；需要时通过 Git 历史查询。

## 实施顺序

```text
F extraction foundation -----------+
                                    +-> 图片到课程页端到端门禁
G post-solver Context foundation ---+
                                    |
                                    +-> E 端到端成本、缓存与候选优化
```

F 与 G 可以并行：

- F 使用现有题图和 authored ProblemIR 建 gold corpus。
- F 处于 shadow 时，G 继续消费 authored ProblemIR。
- extracted ProblemIR 无需 source-specific fallback 即可进入 solver 和 G 后，两条线汇合。
- E 根据完整链路的真实失败和成本分布设计，不提前假设问题只来自 planner。

## F/G 阶段边界

F/G 先完整打通冷路径，不实现产品缓存或 Best-of-N。每次门禁都从 source 开始运行到 compiled lesson page，以暴露 extraction、solver、explanation、visual 和 animation 的真实契约问题。

本阶段只建立后续优化需要的基础：稳定 source fingerprint、immutable Context、dependency ID/hash、contract version，以及每阶段 latency、token、模型调用次数与失败分类。这些字段用于追溯和失效计算，但不在 F/G 中提供缓存命中短路。

## 全局不变量

1. Context state 是事实源；prompt 和 debug 文件只是 projection/artifact。
2. Context version 不可变，并显式记录 parent 与 dependency Context。
3. ProblemIR 是 extraction 与 planner 的稳定边界。
4. Planner 不读取 OCR 过程数据，也不从描述文本补猜缺失事实。
5. 下游 Context 不得修改上游 Context。
6. 身份由 typed ID 决定，不由名称、handle、runtime path 或实际值决定。
7. runtime value 与 provenance 决定 committed state 和 symbolic closure。
8. 低置信上游事实必须保持显式或阻断流程，不能在下游静默升级为确定事实。
9. expected answer 只用于测试，不参与生产选择。
10. 每个 LLM 边界都必须有 parser、validator、retry state 与 fail-closed 配置边界。
11. F/G 门禁默认运行完整冷路径，不能用旧 artifact 掩盖上游或下游缺陷。
12. Context 和 artifact 必须携带稳定 dependency hash，为 E 的缓存与最小失效提供基础。

## Track F：题目提取

### 目标

把图片、PDF、OCR 文本或网页转换为可追溯、可校验的 `ProblemIR`，同时避免 extractor 学习 capability-specific 解题链。

```text
source asset
  -> evidence + candidates
  -> ProblemExtractionContext
  -> deterministic normalization + validation
  -> ProblemIR projection
```

Planner 对 authored/extracted ProblemIR 使用相同接口；区别只记录在 Context manifest 中。

### 退出条件

- 五道现有题图具有 gold extraction fixture。
- solver 必需的 entity、fact、scope、symbol 和 QuestionGoal 完整投影。
- 多义标签和关系保持为显式 extraction issue。
- extracted/authored ProblemIR 产生等价 answer signature 与 provenance gate。
- Planner prompt 不包含 OCR region、置信度内部数据或被拒候选。
- shadow report 提供字段级 precision/recall 和 issue 分类。
- source fingerprint 稳定，并可作为后续 artifact identity 输入。

详细计划：`docs/problem-extraction-context-implementation-plan.md`。

## Track G：解题后 Context 链

### 目标

把 verified solver artifact 转换为版本化课程页，避免使用一个跨领域的可变万能 Context。

```text
PlannerStateContext
  -> LessonExplanationContext
       -> DiagramContext
       -> VoiceoverContext

LessonExplanationContext + DiagramContext + VoiceoverContext
  -> AnimationContext
  -> compiled lesson page
```

`DiagramContext` 可以额外依赖 `ProblemExtractionContext` 的 source visual projection，但数学事实仍来自 ProblemIR 与 verified solver provenance。G 负责使最终 lesson artifact及其 dependency manifest稳定、可验证；缓存、命中短路和增量重建留到 E。

### 工作包

1. 统一 Context manifest、immutable version、dependency ID、stale 与 rebase 规则。
2. `LessonExplanationContext` 接管教学步骤与教学顺序。
3. `DiagramContext` 接管对象、角色、标签、可见性、约束和每步视觉状态。
4. `AnimationContext` 显式依赖 explanation、diagram 与 voiceover version。
5. 只有相互兼容的 Context 组合才能编译最终页面。

### 退出条件

- 五道 authored 问题均通过 Context graph 编译。
- 上游变化会使下游显式 stale，不会静默复用旧内容。
- rebase 可确定执行，或产生 typed repair issue。
- failed/provisional/alias call 不进入学生讲解。
- Lesson、Diagram、Animation artifact 均记录 dependency Context ID。
- F 汇合后至少一题从真实图片完整生成课程页。
-完整冷路径的各阶段 latency、token、调用次数和 artifact dependency可审计。

主要设计：

- `docs/llm-context-model-design.md`
- `docs/explanation-builder-design.md`
- `docs/visual-step-ir-design.md`
- `internal/skills/solver-to-lesson-page-onboarding/SKILL.md`

## F/G 端到端门禁

```text
题目图片
  -> source fingerprint
  -> ProblemExtractionContext
  -> extracted ProblemIR
  -> verified FunctionalPlan + runtime provenance
  -> LessonExplanationContext
  -> DiagramContext
  -> AnimationContext
  -> validated compiled HTML
```

门禁同时检查：

- extraction quality 与 unresolved ambiguity；
- answer、runtime、identity、version 与 provenance；
- explanation coverage 与 canonical call reachability；
- diagram object/label consistency；
- animation dependency 与 narration alignment；
- 页面 schema 与 visual regression；
- 各阶段 latency、token、retry 和 failure layer。
-完整冷路径各阶段 latency、token、retry、外部模型调用次数与 artifact 大小；
- dependency manifest 完整性，为 E 的最小失效提供输入。

任何阶段都不得通过解析展示文本或 expected answer 修复另一阶段。

## Track E：端到端优化

E 在 F/G 冷路径门禁产生有代表性的质量、延迟和成本数据后启动，按收益顺序实施：

1. 最终 Lesson artifact cache：用 source、build options 和 pipeline fingerprint命中已验证课程页，命中后跳过全部 LLM。
2. 并发构建去重：相同 key 只运行一个 cold build，其他请求订阅同一任务。
3. 分层缓存与最小失效：按数据决定是否缓存 extraction、solver、lesson semantic 和 render artifact。
4. 条件式 Best-of-N：只在 cold miss且低成本单候选未通过门禁或证据不足时创建多个候选。
5. 使用 extraction/planner/runtime/domain/lesson validator做 hard filter，并按 canonical outcome signature分组。
6. 依据 provenance 完整度、题面条件覆盖、verified goal closure 与候选共识排序。
7. 只有通过完整门禁的 winner可以进入最终缓存；其他候选只保存为诊断 artifact。
8. 无唯一可信 winner时 retry或安全失败。

缓存与 Candidate selection都不得读取 expected answer。最终 Lesson cache命中不触发 Best-of-N；Best-of-N只提高新题首次构建的成功率。

## 当前 LLM 成本策略

```text
Pass 1/2/3：JSON Output，开启 thinking，reasoning_effort=low
```

Prompt 中的 JSON 使用 compact rendering；结构化 payload 和 debug JSON 保持可读。Catalog 裁剪和应用层响应缓存暂缓到 F/G 端到端指标建立之后。

## 验证命令

Solver 回归：

```bash
cd server
uv run pytest tests/solver -q
git diff --check
```

低成本真实 smoke：

```bash
cd server
RUN_LLM_INTEGRATION=1 \
RUN_DEEPSEEK_STRATEGY_PLANNER=1 \
uv run python -m shuxueshuo_server.solver.deepseek_functional_batch \
  --case all \
  --samples-per-case 1 \
  --concurrency 10 \
  --max-attempts 3 \
  --batch-id functional-default-smoke
```

正式 acceptance 使用 `--samples-per-case 3 --concurrency 15`，并要求 successful sample 的 answer、protocol、runtime、provenance、closure、explanation gate 全部通过，configuration/unclassified error 为零。

## 当前文档

文档入口见 `docs/README.md`。各 Track 的实现细节保存在对应活文档，已完成迁移历史由 Git 保存。
