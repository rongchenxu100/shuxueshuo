# 文档索引

`docs/` 只保存当前有效的架构、接口和实施计划。已完成迁移的逐轮记录、旧协议说明、batch 流水和 source fingerprint 由 Git 历史保存，不继续维护独立文档。

## 当前路线

- `functional-planner-next-stage-roadmap.md`：唯一总路线图，当前顺序为 F/G → E。
- `problem-extraction-context-implementation-plan.md`：Track F 详细计划。
- `online-service-development-plan.md`：在线服务和对象图边界。

## Solver 与 LLM

- `method-solver-architecture.md`：当前 FunctionalPlan 到 runtime 的生产链。
- `capability-authoring-guide.md`：新增 Method、Function、Macro、Contract 的规范。
- `llm-context-model-design.md`：Context version、dependency、stale/rebase 规范。
- `llm-planner-reliability-engineering.md`：失败归因、指标和候选选择原则。
- `cross-scope-version-executable-oracle-design.md`：scope/version 生成式门禁。
- `dynamic-few-shot-strategy-plan.md`：FunctionalPlan mechanism few-shot 资产规则。
- `entity-fact-handle-naming.md`：ProblemIR 展示引用与 typed identity 边界。

## 课程页与交互

- `explanation-builder-design.md`：verified solver artifact 到 LessonIR。
- `visual-step-ir-design.md`：LessonIR 到声明式视觉状态。
- `frontend-parallel-development-with-mock-api-plan.md`：创作后台和 API 契约。
- `student-tutor-chat-system-design.md`：学生对话式导师边界。

## 文档维护规则

1. 文档描述当前事实和未完成工作，不追加时间线式 review 记录。
2. 完成的 migration plan 应删除或并入当前架构说明。
3. 代码、schema、测试是接口细节的最终权威；文档只保留稳定语义和入口。
4. 真实 batch 结果保存在 `internal/solver-runs/`，路线图只记录是否达到门禁。
5. 一个概念只保留一个规范入口，其余文档链接到该入口。
