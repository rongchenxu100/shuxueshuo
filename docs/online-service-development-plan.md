# 在线服务开发计划

## 1. 目标

在线服务围绕可版本化的数学教学对象图构建：

```text
题目来源
→ ExtractionContext / ProblemIR
→ Solver / PlannerStateContext
→ ExplanationContext / LessonIR
→ Diagram / Voiceover / Animation Context
→ LessonPageContext
→ 作者与学生交互
```

网页不是事实源；它由结构化 Context 和 artifacts 编译而来。

F/G 首先实现并验证完整冷路径；最终课程页缓存、分层复用和并发构建去重在端到端事实链稳定后由 Track E实现。

## 2. 责任边界

LLM 负责：

-题目语义抽取与歧义标注；
- FunctionalPlan 能力选择；
-讲解、视觉和交互意图；
-作者 patch 和学生回答的结构化候选。

代码负责：

- identity、scope、version 和 dependency；
- method 执行与验算；
- Context、artifact 和发布版本；
- schema validation、局部编译和失效传播；
-权限、任务、日志和可观测性。

## 3. 核心对象

- `ProblemSource / ExtractionContext`：原始文本、图片、evidence 和抽取状态；
- `ProblemIR`：canonical 数学题意；
- `PlannerStateContext`：verified calls、versions、checkpoint 和 retry；
- `ExplanationContext / LessonIR`：教学结构；
- `DiagramContext / VisualStepIR`：视觉场景；
- `VoiceoverContext / AnimationContext`：音频与时间线；
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

F/G 阶段的构建每次从 source运行到最终页面：

```text
source
  -> extraction
  -> solver
  -> lesson Contexts
  -> render
  -> complete quality gate
```

- 每阶段记录 latency、token、外部模型调用次数、retry、artifact大小和失败authority。
- Context和artifact记录source、contract version与dependency hash，但本阶段不据此跳过任何阶段。
- 只有通过extraction、answer、runtime、provenance、explanation、visual、animation和页面门禁的artifact可以成为E的缓存候选。
- 冷路径稳定和指标完整是启动缓存与Best-of-N的前置条件。

Track E再实现最终`LessonArtifactBundle`缓存、相同key并发build去重、分层缓存与DAG最小失效。缓存命中直接返回页面；冷启动单候选失败或证据不足时才触发Best-of-N。

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

当前顺序：

1. Track F：ExtractionContext 与 ProblemIR source/evidence。
2. Track G：统一 Context orchestration 和 artifact dependency。
3. 完成图片到网页与动画的完整冷路径门禁。
4. Track E：最终artifact cache、并发去重、分层复用和条件式Best-of-N。
5. 完成作者生成/修改闭环。
6. 完成学生TutorContext与临时交互。

## 12. 验收

-任意发布页面可追溯到 source、ProblemIR、verified solution 和 Lesson artifacts；
-局部 patch 只重建必要资产；
-失败有稳定 stage/code，configuration 与模型错误分离；
-Mock/real API contract 一致；
-学生对话不泄露隐藏答案或修改课程事实；
-Gap 可转为离线 fixture 和门禁。
-完整冷路径各阶段成本与失败可观测；
- dependency manifest足以支持Track E的缓存键与最小失效；
- Track E完成后，最终lesson cache命中时外部LLM调用数为零，重复请求只产生一个build job。
