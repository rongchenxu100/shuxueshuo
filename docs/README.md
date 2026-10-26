# 文档索引

`docs/` 保存当前架构、接口、实施计划和必要验收摘要；目标设计必须标明待实施。过期中间过程从计划移除，代码演变由 Git 追溯，原始调用与 fingerprint 证据留在运行产物。

## 当前路线

- [系统路线图](functional-planner-next-stage-roadmap.md)：拍照解析 → 官方题库 → 题目对话 → 逐次交互更新的个人知识掌握图谱与题目/专项练习推荐；当前聚焦一期。
- [在线服务开发计划](online-service-development-plan.md)：一期拍照解析服务的 P1–P5 技术实施顺序和验收标准。
- [产品服务架构](product-service-architecture.md)：PostgreSQL/Alembic、RabbitMQ/Celery、HTTP/WebSocket、存储、页面与学生空间的统一设计入口；待实施。
- [产品数据库设计](product-database-design.md)：用户/工作空间、题目与修订、构建/产物、空库初始化及目录设计；P1 已实现，本地验收通过，服务器完整验收待完成。
- [P1 安装与管理](../deploy/product/README.md)、[服务器发布手册](../deploy/release.md)、[内部接口](product-p1-interfaces.md)、[验收记录](product-p1-acceptance.md)：原生 PostgreSQL 本地安装、服务器发布包、备份恢复和 P2 接入边界。
- [本机 Review 手册](review-runs-local.md)：迁移前现有服务的启动、操作与恢复。
- [Review 修订与重建](review-rebuild-g3-b.md)：已实现能力与有效验收摘要。
- `problem-extraction-context-design.md`：当前图片提取、验证、投影与 Solver 接线边界。

## Solver 与 LLM

- `method-solver-architecture.md`：当前 FunctionalPlan 到 runtime 的生产链。
- [Scope 事实复用与分层证明搜索设计](scoped-proof-search-architecture.md)：已验证数学事实跨 Method 复用、Scope 与执行依赖授权、分层搜索和预算、证书回放及迁移门禁；目标设计，待实施。
- `functional-method-dsl-authoring-guide.md`：把 FunctionalPlan 视为 DSL 时，新增 Method 的语义边界、代码契约、诊断与测试规范；**§3 规定优先采用 `organize_expressions` 验证型范式，并给出防无限打补丁清单**。
- `capability-authoring-guide.md`：新增 Function、Macro、binding、return 与 closure contract 的规范；§1.1 与上条交叉引用。
- `organize-expressions-q08-design.md`：验证型 Method 参考实现（LLM 填式链、代码验等价）。
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

- [新专题与拍题学能力同步建设：开发流程](topic-and-photo-learning-development-workflow.md)：先建章节知识、题型节点与空专题；逐题型完成代表题双验收、其余题全量扩能力及专题精选，旧专题不迁移。
- [函数的概念：专题与拍题学同步建设计划](function-concepts-topic-and-photo-learning-plan.md)：P0 已交付 3.1 图谱与零题专题；本次唯一收录 Q15，之后按 T2、T1、T3、T4、T5 逐型扩能力并精选；保留历史与当前完成口径。
- [T2 具体函数的定义域问题：题型与代表题设计](function-domain-problem-type-design.md)：列条件求交集法、条件提取技能、知识依据、来源驱动交互及受限准入；首题数学和照片回放已接通，完整题型仍待扩充。
- [函数定义域 Q15 验收记录](function-domain-q15-acceptance.md)：原图、真实 extract/review 两次调用、边界与兼容回归；最终课包、专题与拍题双入口及学习记录已通过本地验收。
- [全站手机号登录与题目学习标记计划](site-login-and-learning-marks-plan.md)：手机号验证码登录、AI 接口登录校验，以及是否练习过和学习状态（未标记／熟练掌握／需要再次练习）；第一阶段登录与登出已实现，后续阶段待实施，尚未上线。
- [手机号登录本地测试说明](site-login-local-testing.md)：独立数据库、同源本地站点、模拟短信及阿里云 SendSms 真实联调。
- [基本不等式章节题库首版计划](basic-inequality-practice-bank-plan.md)：`/1` 章节入口、题目与 JSON 清单、个人做题状态、登录的四阶段计划；静态入口已实现、待发布。
- [图谱解题过程 Demo：恒成立 Q01](graph-walk-demo-q01-design.md)：学生与 LLM 共用决策协议，作答时同步展示图谱遍历、判断节点与方法模板执行；已贯通两条路线。
- [Demo 维护与验收](graph-walk-demo-q01.md)：本地入口、构建、真实 AI 录制命令及验收结果。
- [学生拍题学页面设计](student-problem-search-design.md)：“拍题学”学生产品层，对标作业帮的拍照搜题，但结果是 AI 陪学生把题学会；按题型开放，页面随四阶段生成链路分期开发，S5 完成后上线；讨论稿，待实施。
- [交互题目公共运行时设计](interactive-lesson-shared-runtime-design.md)：HTML 承担学生课程，教师 JSON + Context 支撑一对一对话；Q01 已实现本地练习和发起对话时批量同步，未部署。

- [错题本构建规范](mistake-book-authoring-guide.md)：原解保留、三步内容结构、错误分类、可视化、双视图浏览和新增题目检查规范。

- [工作台首版设计](workspace-product-design.md)：最新收敛范围，上传单题图片、中栏生成进度、右栏解析网页；批量、框选与其他功能后续重新讨论。
- `teaching-scope-student-visual-animation-design.md`：F5-F5 Canonical Scope 教学投影、学生步骤、VisualStepIR 与动画 timeline 的统一规范。
- `lesson-scope-llm-authoring-vnext-design.md`：F5-F5B 一次 Scope Lesson LLM、完整计算输入、recursive LessonIR、组件选择，以及和平二模纵向冒烟的分阶段实现计划。
- `explanation-builder-design.md`：verified solver artifact 到 LessonIR。
- `visual-step-ir-design.md`：LessonIR 到声明式视觉状态。
- `inequality-visual-component-refactor-design.md`：不等式 KnowledgePoint、Family、Problem 知识图谱以及 Method/Recipe 与共享视觉组件的确定性绑定协议。
- [基本不等式 Method 与讲解设计](basic-inequality-method-discussion.md)：8 个 Method 统一采用表达式优先协议，包含 M11 局部不等式识别、31 题网页生成目标、代表性集成测试集、Family 讲解规则与 Lesson LLM 边界；扩展能力待实现验证。
- [基本不等式表达式优先 Method 实施计划](basic-inequality-expression-method-implementation-plan.md)：Parser、证明内核、8 个 Method、31 题网页生成、代表性集成测试和切换门禁的分阶段计划。
- `basic-inequality-minimal-learning-space.md`：基本不等式最小学习空间（Hasse 前提、向下闭包、差分补齐）与对称结构用 \(s,p\) 替换的实质。
- [知识点与方法：专题地图、知识图谱与个人图谱设计](knowledge-graph-pages-design.md)：练习系统的知识点／方法数据（只有点和边的图谱、每个专题的关联文件、展示文件），专题页知识地图、跨专题 `/knowledge/` 页和个人图谱（练习覆盖 → 步骤级证据 → 推荐）；设计稿，待实施。
- `frontend-parallel-development-with-mock-api-plan.md`：工作台真实接入与 API/事件测试合同，Mock 仅用于测试和显式开发。
- [学生交互与个性化教学系统设计](student-tutor-chat-system-design.md)：文本表达解题思路（可使用系统语音输入法）、系统代办基础计算、受验证的解题 workflow、识别/求解/交互并行与五阶段实施验收；长期知识图谱作为后续扩展，目标设计待实施。
- [Q01 交互 Demo 讨论稿](q01-interaction-demo.md)：三个节点及通过条件、单栏可视化点选与默认可见对话框、Method 教学单元分别声明交互组件和展示组件；待实现。
- `translations/educational-knowledge-graph-reading-list.md`：教育知识图谱外文阅读清单与中文全文译文入口（ACE / 学习空间 / GbKT / LLM 建图等）。

## 文档维护规则

1. 文档描述当前事实和未完成工作，不追加时间线式 review 记录。
2. 完成的 migration plan 应删除或并入当前架构说明。
3. 代码、schema、测试是接口细节的最终权威；文档只保留稳定语义和入口。
4. 真实 batch 结果保存在 `internal/solver-runs/`，路线图只记录是否达到门禁。
5. 一个概念只保留一个规范入口，其余文档链接到该入口。
