# 文档索引

`docs/` 只保存当前有效的架构、接口和实施计划。已完成迁移的逐轮记录、旧协议说明、batch 流水和 source fingerprint 由 Git 历史保存，不继续维护独立文档。

## 当前路线

- `functional-planner-next-stage-roadmap.md`：唯一总路线图，当前顺序为 F5-F4.3 → F5-F5/G → E。
- `problem-extraction-context-design.md`：当前图片提取、验证、投影与 Solver 接线边界。
- `online-service-development-plan.md`：在线服务和对象图边界。

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

- `explanation-builder-design.md`：verified solver artifact 到 LessonIR。
- `visual-step-ir-design.md`：LessonIR 到声明式视觉状态。
- `inequality-visual-component-refactor-design.md`：不等式 KnowledgePoint、Family、Problem 知识图谱以及 Method/Recipe 与共享视觉组件的确定性绑定协议。
- `frontend-parallel-development-with-mock-api-plan.md`：创作后台和 API 契约。
- `student-tutor-chat-system-design.md`：学生驱动的可验证解题循环、教学反馈、掌握证据与个性化解题页设计。

## 文档维护规则

1. 文档描述当前事实和未完成工作，不追加时间线式 review 记录。
2. 完成的 migration plan 应删除或并入当前架构说明。
3. 代码、schema、测试是接口细节的最终权威；文档只保留稳定语义和入口。
4. 真实 batch 结果保存在 `internal/solver-runs/`，路线图只记录是否达到门禁。
5. 一个概念只保留一个规范入口，其余文档链接到该入口。
