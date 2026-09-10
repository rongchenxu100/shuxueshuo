# 在线服务开发计划

当前优先级（2026-09-09）：**G3 真实图片上传 → 课程页 → 上游变更重建**。
本文 §11 为下一阶段执行计划，尚未宣称端到端验收完成。G1 的 LLM 视觉选择不列为必做项；
G2 新动画能力、配音与音画同步延后。已有确定性图形和滑块继续保留并验证。

## 1. 目标

在线服务围绕可版本化的数学教学对象图构建：

```text
题目来源
→ ExtractionContext / ProblemIR
→ Solver / PlannerStateContext
→ ExplanationContext / LessonIR
→ DiagramContext / VisualStepIR
→ LessonPageContext
→ 作者与学生交互
```

网页不是事实源；它由结构化 Context 和 artifacts 编译而来。

G3 首先验证无配音课程页的完整冷路径与依赖变更重建；最终课程页缓存、分层复用优化和
并发构建去重在端到端事实链稳定后由 Track E 实现。Voiceover / 新 Animation 能力是后续扩展，
不是当前页面完成的必要依赖。

## 2. 责任边界

LLM 负责：

-题目语义抽取与歧义标注；
- FunctionalPlan 能力选择；
-讲解文案与学生步骤编排；
-作者 patch 和学生回答的结构化候选。

代码负责：

- identity、scope、version 和 dependency；
- method 执行与验算；
- VisualSpec 选择、角色绑定、图形、交互和最短路径状态；
- Context、artifact 和发布版本；
- schema validation、局部编译和失效传播；
-权限、任务、日志和可观测性。

## 3. 核心对象

- `ProblemSource / ExtractionContext`：原始文本、图片、evidence 和抽取状态；
- `ProblemIR`：canonical 数学题意；
- `PlannerStateContext`：verified calls、versions、checkpoint 和 retry；
- `ExplanationContext / LessonIR`：教学结构；
- `DiagramContext / VisualStepIR`：视觉场景；
- `VoiceoverContext / AnimationContext`：后续音频与时间线扩展，不阻塞本阶段；
- `LessonPageContext`：发布资产聚合；
- `ArtifactPatch`：作者持久修改；
- `TutorContext`：学生会话的受限 projection；
- `GapRecord`：当前能力无法处理的结构化缺口。

## 4. 服务模块

```text
Source service
Extraction worker
Solver worker
Lesson compiler
Artifact store
Version/publish service
Tutor service
Job/event service
Observability and gap queue
```

耗时工作统一使用异步 Job；前端通过 SSE/event stream 获取阶段进度。

## 5. 构建与可观测性

G3 首次验收完整运行冷路径，不用预生成的 Solver/Lesson fixture 替代真实阶段：

```text
source
  -> extraction
  -> solver
  -> lesson Contexts
  -> render
  -> complete quality gate
```

- 每阶段记录 latency、token、外部模型调用次数、retry、artifact大小和失败authority。
- Context 和 artifact 记录 source、contract version 与 dependency hash。变更重建按依赖重跑
  受影响阶段，不重跑无关上游；这不是引入跨任务缓存。
- 只有通过 extraction、answer、runtime、provenance、explanation、visual 和页面门禁的
  artifact 才能标为 ready。已有交互也须通过验证；不要求新增动画或配音。
- 冷路径稳定和指标完整是启动缓存与Best-of-N的前置条件。

Track E 再实现最终 `LessonArtifactBundle` 缓存、相同 key 并发 build 去重和分层缓存优化。
依赖失效与正确重建必须在 G3 完成，不延到 E。Best-of-N 也不纳入当前主链。

## 6. 版本与依赖

- Context 和 artifact 均不可原地修改；
-新版本引用 parent 和 dependency hashes；
-上游变化只失效受影响的下游资产；
-发布版本固定引用完整 dependency closure；
-作者 patch 经过 validator 后生成新版本；
-学生临时互动不修改发布事实。

## 7. 作者工作流

```text
上传题目
→ 抽取/确认 ProblemIR
→ 求解与讲解生成
→ 页面预览
→ 提交结构化 patch
→ 局部重建
→ 发布
```

作者可修改题意识别、对象、讲解粒度、视觉和文案；不能直接编辑 runtime identity、裸答案或任意 HTML/JS。

## 8. 学生工作流

```text
打开发布 Lesson
→ 浏览步骤和交互
→ TutorContext 回答当前问题
→ 临时高亮/动画/提示
```

学生对话只读取发布 facts 和当前 UI state，不产生持久数学事实。

## 9. Gap 流程

无法处理的样本生成 GapRecord：

-失败 authority stage；
-最小输入与 evidence；
-缺失 capability/schema/visual action；
-相关 Context/artifact ids；
-是否可重试；
-匿名化回归 fixture。

Gap 应进入离线能力建设，而不是在线注入单题代码。

## 10. API 与前端

API 至少覆盖 source、problem、lesson、scene、timeline、tutor session 和 job。具体 contract 见：

- `docs/frontend-parallel-development-with-mock-api-plan.md`
- `docs/student-tutor-chat-system-design.md`

## 11. 实施顺序

### G3-A：先跑通一张真实图片（COMPLETE · 2026-09-09）

已交付独立 `/review/runs` 和详情页面，南开真实图片冷链九阶段通过。
运行链接、启动方式、测试与已知课程质量 Review 项见
[G3-A 本机运行手册与验收记录](review-runs-local.md#2026-09-09-真实验收记录)。
本阶段没有迁移作者工作台，也没有实现阶段编辑或局部重建。

1. 盘点现有上传入口、后端 Job、各阶段 Context/artifact 与页面服务，明确断点；复用已有合同，
   不另建一条仅供脚本演示的生成链。
2. 从用户实际上传开始，走真实抽取、题意确认、Solver、Lesson、Visual、编译和服务预览。
   首题选择已支持题型；不得用 authored plan、expected answer 或预生成中间产物代替真实生成。
3. 前端能看到阶段进度、失败原因和重试入口；成功后直接打开该次构建的课程页，
   不依靠手工定位 `internal/solver-runs` 或 `file://` 页面。
4. 保存原图身份、各阶段输入输出、provider/model、prompt/spec/contract 版本、耗时、token
   与验证结果，形成一份可复查的端到端验收记录。

退出条件：一张真实上传图片在服务中得到可审阅课程页，全链依赖可追溯；
失败不能被标为成功，人工确认不能变成手工补齐执行产物。

### G3-B：上游变化后正确重建（NEXT）

每个阶段固定其输入版本与实际消费的 dependency hash，包括相关生成配置、Spec 和编译器版本。
依赖发生变化时先标记受影响资产 stale，再重建；新的 ready 页面只能引用验证通过的完整依赖闭包。

| 变化来源 | 必须失效并重建 | 不应无条件重跑 |
| --- | --- | --- |
| 原始图片替换 | 抽取、确认状态、Solver、Lesson、Visual、页面 | 无；这是新来源冷路径 |
| 确认后的题意修改 | 题意校验、Solver 及受影响下游 | 原图上传与已保存的抽取观察 |
| Solver 合同或实际消费的求解配置变化 | Solver 及受影响下游 | 来源与题意抽取 |
| 教学材料、教学 Spec 或 Lesson 生成配置变化 | 受影响的教学投影、Lesson 及依赖它的 Visual/页面 | 抽取与 Solver |
| VisualSpec / 绑定或交互规则变化 | 受影响的 Visual 与页面 | 抽取、Solver 与纯教学生成 |
| 页面模板、CSS 或渲染器变化 | 受影响的页面编译产物 | 数学求解、教学与视觉语义生成 |
| 学生拖动临时滑块 | 仅当前页面临时交互状态 | 所有持久 Context 与发布版本 |

表格按实际依赖传播，不靠题号、文件时间或显示文案猜测。相同规范化输入不应产生虚假失效；
允许继续引用仍有效的不可变父产物，但本阶段不要求跨任务缓存。

必须覆盖以下竞态与失败：

- 上游已变更，旧任务晚完成：可以保留旧版本记录，不得覆盖最新构建的状态或页面指针。
- 下游生成失败：保留阶段错误与重试所需证据，不把旧页面冒充新版本；旧预览若保留须明确版本。
- 重试成功：消费当前构建固定的依赖，禁止把不同版本的 Lesson、Visual 和 HTML 混装。
- 草稿重建不自动修改已发布版本；发布仍由作者明确操作。

退出条件：上述变化矩阵、失败重试、并发旧结果覆盖防护均有自动回归；至少一次在真实页面中
验证“修改题意 → 重建”和“修改教学/视觉 → 不重跑 Solver → 新页可见”。

### G3-C：扩到五题并完成课程页审阅

- 用已支持的五个代表题型分别真实上传，保存原图到服务页面的构建记录；不只重编译旧 fixture。
- 检查公式、图形完整性、缩放、已有滑块、最短路径与后续计算步骤的场景保持。
- C1 teaching-only `5×3` 继续作为教学质量专项验收；不阻塞 G3-A/B 接线，也不能替代上传链验收。
  既有 `5×1` / `5×3` 批次及离线测试仅作历史证据，当前版本仍须记录实际结果和人工结论。
- 跑相关离线全量门禁；真实外部调用与离线回归分开报告，不把 skipped/live 未运行写成通过。

### 后续阶段（不阻塞 G3）

1. Track E：缓存、并发去重、分层复用优化和条件式 Best-of-N。
2. 扩展作者编辑体验与学生 TutorContext；基础上传、修改和重建闭环已在 G3 完成。
3. G2 新动画能力、配音与音画同步按产品需要安排，不作为上述阶段前置条件。
4. G1 的 LLM 视觉选择仅保留为可选研究设计；出现确定性视觉无法满足的具体需求后再评估。

## 12. 验收

-任意发布页面可追溯到 source、ProblemIR、verified solution 和 Lesson artifacts；
-局部 patch 只重建必要资产；
-失败有稳定 stage/code，configuration 与模型错误分离；
-Mock/real API contract 一致；
-学生对话不泄露隐藏答案或修改课程事实；
-Gap 可转为离线 fixture 和门禁。
-完整冷路径各阶段成本与失败可观测；
- G3 的 dependency manifest、失效传播、重建与版本一致性已实际验证，不仅预留缓存字段；
- Track E完成后，最终lesson cache命中时外部LLM调用数为零，重复请求只产生一个build job。
