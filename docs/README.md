# 文档索引

`docs/` 保存当前架构、接口、实施计划和必要验收摘要；目标设计必须标明待实施。过期中间过程从计划移除，代码演变由 Git 追溯，原始调用与 fingerprint 证据留在运行产物。

## 当前路线

- [系统路线图](functional-planner-next-stage-roadmap.md)：拍照解析 → 官方题库 → 题目对话 → 逐次交互更新的个人知识掌握图谱与题目/专项练习推荐；当前聚焦一期。
- [在线服务开发计划](online-service-development-plan.md)：一期拍照解析服务的 P1–P5 技术实施顺序和验收标准。
- [产品服务架构](product-service-architecture.md)：PostgreSQL/Alembic、RabbitMQ/Celery、HTTP/WebSocket、存储、页面与学生空间的统一设计入口；待实施。
- [产品数据库设计](product-database-design.md)：用户/工作空间、题目与修订、构建/产物、空库初始化及目录设计；P1 已实现，本地验收通过，服务器完整验收待完成。
- [P1 安装与管理](../deploy/product/README.md)、[内部接口](product-p1-interfaces.md)、[验收记录](product-p1-acceptance.md)：原生 PostgreSQL 本地安装、服务器发布包、备份恢复和 P2 接入边界。
- [本机 Review 手册](review-runs-local.md)：迁移前现有服务的启动、操作与恢复。
- [Review 修订与重建](review-rebuild-g3-b.md)：已实现能力与有效验收摘要。
- `problem-extraction-context-design.md`：当前图片提取、验证、投影与 Solver 接线边界。

## Solver 与 LLM

- `method-solver-architecture.md`：当前 FunctionalPlan 到 runtime 的生产链。
- `functional-method-dsl-authoring-guide.md`：把 FunctionalPlan 视为 DSL 时，新增 Method 的语义边界、代码契约、诊断与测试规范。
- `capability-authoring-guide.md`：新增 Function、Macro、binding、return 与 closure contract 的规范。
- `llm-context-model-design.md`：Context version、dependency、stale/rebase 规范。
- `llm-planner-reliability-engineering.md`：失败归因、指标和候选选择原则。
- `llm-sample-failure-review-guide.md`：逐 sample 检查 prompt、thinking、Plan、runtime 与 retry 的证据流程；包含输出超长专项和逐轮图示规范。
- `solver-test-strategy.md`：Solver 测试分级、affected ownership、并行分片、单场景重放和真实 LLM 隔离规范。
- `functional-scope-retry-design.md`：当前 Annotated Plan、Scope-only authority、完整 Scope replacement 与 restore 规范。
- `scope-native-c0-c5-executable-gate.md`：scope、typed state、Scope Retry 与 closure 生成式门禁。
- `path-minimum-macro-redesign.md`：路径最值原子Macro的Planner边界、runtime证据、retry约束与F5-F4.3分段迁移计划。
- `dynamic-few-shot-strategy-plan.md`：FunctionalPlan mechanism few-shot 资产规则。
- `entity-fact-handle-naming.md`：ProblemIR 展示引用与 typed identity 边界。

## 课程页与交互

- `teaching-scope-student-visual-animation-design.md`：F5-F5 Canonical Scope 教学投影、学生步骤、VisualStepIR 与动画 timeline 的统一规范。
- `lesson-scope-llm-authoring-vnext-design.md`：F5-F5B 一次 Scope Lesson LLM、完整计算输入、recursive LessonIR、组件选择，以及和平二模纵向冒烟的分阶段实现计划。
- `explanation-builder-design.md`：verified solver artifact 到 LessonIR。
- `visual-step-ir-design.md`：LessonIR 到声明式视觉状态。
- `inequality-visual-component-refactor-design.md`：不等式 KnowledgePoint、Family、Problem 知识图谱以及 Method/Recipe 与共享视觉组件的确定性绑定协议。
- `basic-inequality-minimal-learning-space.md`：基本不等式最小学习空间（Hasse 前提、向下闭包、差分补齐）与对称结构用 \(s,p\) 替换的实质。
- `frontend-parallel-development-with-mock-api-plan.md`：工作台真实接入与 API/事件测试合同，Mock 仅用于测试和显式开发。
- `student-tutor-chat-system-design.md`：受控教学状态图、学习证据和学生长期知识图谱设计；后续学生端阶段实施。

## 文档维护规则

1. 文档描述当前事实和未完成工作，不追加时间线式 review 记录。
2. 完成的 migration plan 应删除或并入当前架构说明。
3. 代码、schema、测试是接口细节的最终权威；文档只保留稳定语义和入口。
4. 真实 batch 结果保存在 `internal/solver-runs/`，路线图只记录是否达到门禁。
5. 一个概念只保留一个规范入口，其余文档链接到该入口。
