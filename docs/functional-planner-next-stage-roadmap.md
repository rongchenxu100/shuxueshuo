# 系统能力与后续工作

本文按当前仓库实现维护能力边界。代码存在、本地验收、真实模型验收和生产发布是不同状态；具体环境操作以部署手册为准。

## 当前系统

| 入口 | 当前能力 | 规范 |
| --- | --- | --- |
| 学生拍题 `/lab/search/` | 手机号登录、OCR 选题、题意提取与复核、图谱判型、方法求解、步骤交互、个人历史、删除和到期清理 | [拍题页面](student-problem-search-design.md)、[单机运行](search-single-host-production.md) |
| 专题练习 `/1/`、`/2/`、`/topics/` | 静态练习、图谱课程、按需老师对话、学习记录 | [共享运行时](interactive-lesson-shared-runtime-design.md)、[专题开发流程](topic-and-photo-learning-development-workflow.md) |
| 公共及个人图谱 `/knowledge/` | 八类公共节点、教学关联、五题检测和个人节点状态 | [图谱模型](public-knowledge-graph-ontology-design.md)、[维护说明](public-knowledge-graph-stage4.md) |
| 内部工作台与 Review | PostgreSQL、任务队列、版本化产物、题意候选、修订与重建 | [服务架构](product-service-architecture.md)、[本地运行](product-p2-local-runbook.md) |
| FunctionalPlan Solver | 类型化调用、Scope Retry、分层证明搜索、教学与视觉编译 | [Solver 架构](method-solver-architecture.md) |

学生拍题使用 `graph_lesson` 链；内部 FunctionalPlan 生成链继续保留。两条链不能互相套用阶段编号、题型开放范围或验收结论。

## 当前开发重点

- 按题型同时扩充专题课程与拍题能力，复用识别、数学执行、教学交互及版本契约。
- 函数专题已收录 Q15、Q01、Q22、Q04、Q12、Q23b、Q20；T1、T2 为受限开放，未完成整个题型。剩余目标、真实照片与留出验收见[函数专题计划](function-concepts-topic-and-photo-learning-plan.md)。
- T3 抽象定义域、T4 求函数值、T5 求值域保留设计，实际开放以注册表、执行器和验收为准。
- 共享公共课程包、跨设备拍题作答同步、综合掌握评估与推荐尚属后续范围；不将规范题面去重等同于解析复用。
- 阶段④ LLM 教学问答、FunctionalPlan 的可选 LLM 视觉选择及新增配音/动画分别验收，不作为已有确定性课程的完成证明。

## 维护边界

来源复核不等于数学求解通过，数学正确不等于教学和交互完成，本地通过不等于生产发布。发布前须用目标提交、目标环境和冻结配置验证。

题意、执行证据与显示文案各有权威；版本变化使相关缓存和准入失效。私有题图及课程按用户隔离，删除和到期规则同时约束读取、后台写入与备份恢复。

运行手册维护当前命令和配置；实现规范维护稳定语义；试验响应、性能数字和逐轮审查不追加到规范正文。
