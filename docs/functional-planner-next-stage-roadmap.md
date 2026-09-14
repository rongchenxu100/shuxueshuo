# 数学说系统路线图

更新：2026-09-11。**当前产品目标：一期拍照上传题目，生成可查看的解析网页。**
路线图只维护当前能力与未完成工作；详细排期见[在线服务开发计划](online-service-development-plan.md#11-实施顺序)，
选型和职责边界见[产品服务架构](product-service-architecture.md)。

## 当前能力

| 能力 | 状态 |
| --- | --- |
| FunctionalPlan、typed runtime、Scope Retry、原子路径 Macro | 已实现并有回归门禁 |
| 图片观察、题意校验、promotion、Bundle 投影 | 已实现；DeepSeek 多模态提取切换待实施 |
| 教学证据、递归 LessonIR、确定性 VisualSpec 与页面编译 | 已实现；C1 teaching-only 5×3 质量专项待验收 |
| G3-A/B：Review 上传、修订、失效判断、按阶段重建、版本一致性 | Review 范围已验收，见[实现与验收](review-rebuild-g3-b.md) |
| 工作台真实上传与批量任务 | 尚未接通；现有入口仍是 Mock |
| 产品 PostgreSQL、SQLAlchemy/Alembic 与产物存储 | P1 本地验收通过；P2 已接入产品入口；服务器 Docker 验收待完成 |
| RabbitMQ/Celery、产品 WebSocket | P2 本地已实现并通过离线/故障验收；唯一真实构建在题意抽取失败，完整验收待通过 |
| 学生账户、课程授权、实时 Tutor | 后续扩展；首版固定工作空间、无登录 |

## 产品版本顺序

```mermaid
flowchart LR
    V1["一期：拍照上传 → 解析网页"] --> V2["二期：官方题库"]
    V2 --> V3["三期：围绕题目对话讨论"]
    V3 --> V4["四期：个人知识掌握图谱 → 题目与专项练习推荐"]
```

| 产品阶段 | 目标与边界 |
| --- | --- |
| 一期：拍照解析（当前） | 拍照或选择完整单题图片上传，真实生成解析网页；支持状态恢复、失败重试和必要的修订重建。批量工作台是同一生成服务的入口 |
| 二期：官方题库 | 官方工作空间维护题目，审核后发布固定版本供学生使用；建立题目与知识、方法、题型的基础关系，学生练习与题库内容分离 |
| 三期：题目对话 | 围绕官方题目或自己的题目追问、解释与讨论，绑定具体题意/解析版本，保存可追溯会话 |
| 四期：个人知识掌握图谱与推荐闭环 | 基于每个学生围绕自己上传题目和官方题目的对话交互建立个人知识掌握图谱；每次交互后评估并更新图谱，再据此推荐题目和专项练习 |

四期的核心资产是持续更新的个人知识掌握图谱，推荐消费该图谱。每次交互都进入证据评估和图谱更新流程，
不等到整题完成或会话结束；证据不足时保留未知或原掌握结论并记录本次评估，不强行改变掌握分数。

官方工作空间、发布授权及 PostgreSQL 知识图谱方向作为二期及后续设计，见[后续产品架构](product-service-architecture.md#61-后续产品版本的职责)。
一期不以官方题库、知识图谱、题目对话、学生掌握模型或推荐系统为前置条件；也不迁移旧运行记录。

## 一期技术实施步骤

以下 P1–P5 是技术工作项，**不是产品的一期到五期**；P4/P5 为生成链的模型与质量工作，不改变上述产品顺序。

当前先完成本地系统，再部署服务器。P1 本地数据底座和正式实例已就绪；P2 已接通本地 Review/API/队列及九阶段适配器，离线和队列故障测试通过，但唯一真实单题在题意抽取校验与超时处失败，暂不标记完整完成。详见 [P2 验收记录](product-p2-acceptance.md)。服务器 Docker 验收延后至部署阶段，仍是上线前必做项。

1. **P1**：产品数据模型、PostgreSQL/Alembic、产物存储接口，包含流水线版本与构建定义冻结；空库初始化默认用户、默认工作空间及成员关系，不迁移旧记录。
2. **P2**：产品共用 API/任务/事件服务，RabbitMQ/Celery 执行；Review 迁移为同一服务的审查入口。
3. **P3**：工作台批量上传、状态恢复、失败题重试、修订重建和人工审查；完成五题真实页面闭环。
4. **P4**：DeepSeek 多模态对照与默认切换；适配和对照可与 P1–P3 同期开展，切换后验证全链。
5. **P5**：有界 Plan 多候选，默认 N=1，先测 N=1/N=3 的成本与质量收益；不阻塞实际批量做题。

G3-C 五题上传/课程页审阅并入 P3/P4。C1 仍独立，不以旧批次通过代替当前模型和产品链验收。
缓存、跨题复用、复杂发布、多节点扩容按后续生产需求安排；Best-of-N 不再绑定缓存建设顺序。
G1 LLM 视觉选择保持可选；G2 新动画、配音延后，已有图形与滑块继续通过门禁。

## 保留的领域主链

```text
原图 → SourceObservation → VerifiedProblem / Bundle
     → FunctionalPlan → typed compiler / transactional runtime / Scope Retry
     → VerifiedFunctionalPlanExecution → ExplanationSnapshot
     → LessonIR → VisualStepIR → 版本化课程页
```

技术合同详见[Solver 架构](method-solver-architecture.md)、
[Scope Retry](functional-scope-retry-design.md)、[原子路径 Macro](path-minimum-macro-redesign.md)、
[教学与视觉](teaching-scope-student-visual-animation-design.md)。

## 不变量

- VerifiedProblem 是题意语义权威；Solver 状态不回写题意，网页与显示文案不成为事实源。
- identity、owner、可见性、版本与依赖由代码维护；expected answer 仅用于测试。
- 首轮与 repair 共用公开合同和精确诊断；重试仅按合法归属开放 Scope，保守整块替换。
- Macro 的内部搜索、候选和 witness 不扩大 Planner/Retry wire；不以增加上下文掩盖合同问题。
- 教学与视觉消费已验证公开执行，沿用 Canonical Scope/Goal topology；失败、shadow 和 provisional 不进入课程。
- 修订、构建和产物不可变；依赖重建保留证据，旧任务不能覆盖新修订或当前页面。
- 队列允许重投递，业务提交必须幂等；连接中断不取消任务，事件可补读。
- 无登录首版仍有固定工作空间；个人学习状态与共享课程内容分离，私有产物不能自动公开。
- 实际模型调用、候选选择与复用分别审计；历史成功、当前有效、人工通过和公开发布分别表达。

## 文档与证据

[在线服务开发计划](online-service-development-plan.md)是实施顺序入口；
[产品服务架构](product-service-architecture.md)是基础设施与存储边界入口；
[本机 Review 手册](review-runs-local.md)仅描述当前可运行实现。
已完成阶段的逐轮迁移、旧 Prompt 尺寸、试验比较和 batch 流水从路线图移除；
有效验收摘要保留在专项说明，原始输入输出保留在运行产物，代码演变由 Git 追溯。
