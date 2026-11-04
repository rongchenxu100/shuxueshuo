# 文档索引

文档维护当前架构、操作规则、能力边界与仍有效的扩展设计。实际接口以代码、Schema 和测试为准；本地实现、真实模型验收与生产发布分别表述。

函数专题当前收录七题，T1/T2 受限开放，T3/T4/T5 保留开发设计。学生拍题的图谱执行链与内部 FunctionalPlan 链分别维护。

## 系统与日常运行

- [系统能力与后续工作](functional-planner-next-stage-roadmap.md)
- [本地产品服务列表与启动、停止命令](product-local-services.md)
- [P2 本地运行手册](product-p2-local-runbook.md)
- [手机号登录：本地运行与测试](site-login-local-testing.md)
- [拍题学：单机生产接入与离线镜像演练](search-single-host-production.md)
- [拍题准入、每日额度与费用停止开关](search-admission.md)
- [拍题备份恢复：删除与到期不复活](search-backup-restore-local-acceptance.md)
- [真实 OCR 镜像本地验收（2026-10-24）](search-real-ocr-local-acceptance.md)
- [OCR 本地环境安装](ocr-local-environment-setup.md)
- [Solver 测试分级策略](solver-test-strategy.md)

## 专题与图谱

- [新专题与拍题学能力同步建设：开发流程](topic-and-photo-learning-development-workflow.md)
- [函数的概念：专题与拍题学同步建设计划](function-concepts-topic-and-photo-learning-plan.md)
- [函数单调性：专题题目、方法与技能建设计划](function-monotonicity-topic-plan.md)
- [3.1 函数的概念及其表示：知识图谱设计](function-concepts-and-representation-knowledge-graph-discussion.md)
- [高中数学公共知识图谱设计](public-knowledge-graph-ontology-design.md)
- [公共知识图谱：维护与发布](public-knowledge-graph-stage4.md)
- [个人知识图谱数据设计](student-knowledge-graph-data-design.md)
- [个人知识图谱：六阶段实现与验收](student-knowledge-graph-implementation.md)

## 函数题型与验收范围

- [T3 抽象函数的定义域问题：题型开发设计](abstract-function-domain-problem-type-design.md)
- [T2 具体函数的定义域问题：题型与代表题设计](function-domain-problem-type-design.md)
- [函数定义域 Q01：零次幂与约分前限制验收](function-domain-q01-acceptance.md)
- [函数的概念 Q04：定义域求参扩题验收](function-domain-q04-acceptance.md)
- [函数的概念 Q12：根式分母的定义域求参](function-domain-q12-acceptance.md)
- [函数定义域 Q15：实现范围与验收记录](function-domain-q15-acceptance.md)
- [函数的概念 Q23（2）：独立的定义域求参问题](function-domain-q23b-acceptance.md)
- [T1 判断是否为相同函数：题型开发设计](function-equality-problem-type-design.md)
- [T1 第20题：同一函数判定与两层交互验收](function-equality-q20-acceptance.md)
- [T4 求函数值：题型开发设计](function-evaluation-problem-type-design.md)
- [T5 求函数的值域：题型开发设计](function-range-problem-type-design.md)
- [FM-T1 判断函数的单调性：题型开发设计](function-monotonicity-problem-type-design.md)
- [FM-T1：实现范围、原图与专题验收](function-monotonicity-t1-acceptance.md)

## 拍题与交互课程

- [学生拍题学页面设计](student-problem-search-design.md)
- [公共题库、学生关联与解析复用：设计稿](shared-problem-library-and-student-learning-design.md)
- [公共题库、学生关联与解析复用：第一期实施说明](shared-problem-library-and-student-learning-stage1.md)
- [基于四阶段的交互课程生成设计](graph-guided-interactive-lesson-design.md)
- [图谱交互课程阶段①实现计划：题意与数学特征](graph-guided-stage-one-implementation-plan.md)
- [图谱交互课程阶段②实现计划：特征检查表判型与 D1、D2](graph-guided-stage-two-implementation-plan.md)
- [图谱交互课程阶段③实现计划：选法评估、方法驱动求解与数学步骤逐步交付](graph-guided-stage-three-implementation-plan.md)
- [阶段三执行器：PostgreSQL 存储实施说明](stage-three-postgresql-execution-storage.md)
- [阶段三步骤交互卡技术方案](stage-three-step-interaction-design.md)
- [恒成立 Q01 图谱解题 Demo](graph-walk-demo-q01.md)
- [图谱解题过程 Demo 技术设计：恒成立 Q01](graph-walk-demo-q01-design.md)
- [交互步骤卡片设计规范](interactive-step-card-design-spec.md)
- [交互题目：静态课程与一对一老师的职责](interactive-lesson-shared-runtime-design.md)
- [一元二次不等式的应用：恒成立问题题库设计](quadratic-inequality-always-true-practice-design.md)
- [全站手机号登录与题目学习标记计划](site-login-and-learning-marks-plan.md)
- [错题本内容与页面构建规范](mistake-book-authoring-guide.md)
- [高中数学方法可视化原则（知识库方法卡）](senior-high-method-visualization-principles.md)

## 内部产品与题意处理

- [工作台首版：上传图片生成解析网页](workspace-product-design.md)
- [产品服务架构：任务、实时交互、存储与版本](product-service-architecture.md)
- [产品数据库设计：工作空间、题目身份、版本与产物](product-database-design.md)
- [P1 内部接口与 P2 接入约定](product-p1-interfaces.md)
- [P2 产品接口与 P3 交接](product-p2-interfaces.md)
- [本机 Review 运行手册](review-runs-local.md)
- [G3-B：Review 修改与版本一致重建](review-rebuild-g3-b.md)
- [数学题意、运行时绑定与 Method 参数](math-notation-integration.md)
- [数学记法题意抽取：repair 与原图复核设计](math-notation-repair-design.md)
- [数学语义等价约束归一化实现设计](math-notation-equivalence-normalization-design.md)
- [数学记法抽取：已知限制](math-notation-known-issues.md)
- [Legacy 领域题意：图片到 Problem 模型](problem-extraction-context-design.md)
- [原图主导的题意抽取与独立复核](problem-source-review-v1.md)

## FunctionalPlan、证明与教学

- [基本不等式自动求解：能力边界与后续工作](basic-inequality-expression-method-implementation-plan.md)
- [高中基本不等式 Method 与讲解设计](basic-inequality-method-discussion.md)
- [Capability 编写指南](capability-authoring-guide.md)
- [M08 条件消元：阶段 5A](constraint-elimination-method-design.md)
- [FunctionalPlan 动态 Few-shot](dynamic-few-shot-strategy-plan.md)
- [ProblemIR 引用与 Typed Identity 规范](entity-fact-handle-naming.md)
- [Explanation Builder 设计](explanation-builder-design.md)
- [Functional Method DSL 编写规范](functional-method-dsl-authoring-guide.md)
- [FunctionalPlan Scope Retry 设计](functional-scope-retry-design.md)
- [F5-F5B/G1 Lesson Scope LLM Authoring 与视觉选择 vNext 设计](lesson-scope-llm-authoring-vnext-design.md)
- [LLM Context 模型设计](llm-context-model-design.md)
- [LLM Planner 可靠性工程](llm-planner-reliability-engineering.md)
- [LLM Sample 故障审查指南](llm-sample-failure-review-guide.md)
- [Method Solver 当前架构](method-solver-architecture.md)
- [整理式子 Method：q08 首轮实现](organize-expressions-q08-design.md)
- [路径最值原子 Macro 设计](path-minimum-macro-redesign.md)
- [Scope-native C0-C5 可执行门禁](scope-native-c0-c5-executable-gate.md)
- [Scope 事实复用与分层证明搜索](scoped-proof-search-architecture.md)
- [学生步骤、VisualSpec 与前端组件声明式绑定](student-step-visual-binding-design.md)
- [M07 换元：阶段 5B](substitution-method-design.md)
- [F5-F5 Teaching Scope、学生步骤、可视化与动画设计](teaching-scope-student-visual-animation-design.md)
- [逐帧数学状态机制（v1）](visual-math-state.md)
- [VisualStepIR v2：递归 Scope 图形状态设计](visual-step-ir-design.md)

## 实验与扩展设计

- [学生讲解模式：会话上下文设计](student-explanation-context-design.md)
- [学生讲解模式：我来讲解](student-explanation-mode-design.md)
- [学生讲解模式：交互设计（扩展设计）](student-explanation-interaction-design.md)
- [学生交互与个性化教学系统设计](student-tutor-chat-system-design.md)
- [基本不等式：最小学习空间](basic-inequality-minimal-learning-space.md)
- [不等式知识图谱与可视化组件绑定重构设计](inequality-visual-component-refactor-design.md)
- [Q01 交互 Demo：三个节点、页面交互与组件职责](q01-interaction-demo.md)

## 参考与维护

- [部署与安装](../deploy/product/README.md)、[服务器发布](../deploy/release.md)。
- [论文译文与阅读索引](translations/README.md)：研究资料不作为当前实现说明。
- [验证数据](validation/README.md)：保留回放和测试依赖资产，历史机器报告不代表当前通过率。

规范不追加讨论时间线、逐轮审查、提交状态或临时服务日志。完成的计划合并到当前规范；未完成设计须标明范围。原始实验材料保存在运行目录，稳定测试输入进入 fixture，代码演变由 Git 追溯。
