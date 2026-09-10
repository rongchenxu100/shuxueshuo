# G3-B：Review 修改与版本一致重建

实现入口：`server/shuxueshuo_server/review/` 和 `frontend/app/review/runs/`。

## 使用闭环

1. 在运行详情打开“编辑题意 JSON”，载入题意，修改后校验并预览差异。
2. 保存修订。保存不启动 worker，也不调用模型。
3. 检查“修改与重建”中的复用范围、重建范围及模型调用阶段，再点击“按影响范围重建”。
4. 在独立的新运行中检查结果。历史运行和产物保持不变。

教学与视觉仍修改仓库 Spec，页面样式仍修改课程页 CSS。Review 定期读取重建计划，但不自动提交。

## 版本证据

每阶段保存 `review-stage-manifest/v1`：内容哈希化的实际边界输入、阶段生产资源、有效配置及 manifest 指纹。输入边界由 `dependencies.INPUTS` 单独登记，产物原有的审计依赖继续保留。

生产资源新增、删除、改名都参与比较；时间戳和 Review 输出不参与。未识别的资源保守归入较早阶段，计划列出具体路径。生产资源归属测试用于提醒新资源维护者登记消费者。生产目录清单包含 Python 包、prompt、Schema、few-shot、模板、编译工具、课程页 JS/CSS 和依赖锁文件；仓库中的测试、报告、派生产物不作为生成依赖。

Method/Recipe 声明通过 AST 分离教学字段与视觉字段，剩余代码独立计入 Solver。运行时方法与 trace 实现变更仍重跑 Solver；同模块中的共享 helper 或声明结构改动也保守归入 Solver。完整 Spec 注册表视为对应阶段的生产依赖，不做跨题缓存或阶段内部片段缓存。

指纹探测和题意预览校验都使用新解释器。API 不缓存 Python 注册表、有效配置或生成结果，避免进程长驻造成的旧模块状态。`source_version` 保留审计用途。

| 变更 | 最早重建阶段 |
| --- | --- |
| 图片、来源入库实现或无法分类的共享生产依赖 | 来源入库 |
| OCR 实现或配置 | OCR 与观察 |
| 人工题意 | 题意完整校验、promotion 和新 Context，随后输入投影 |
| Solver 实现、合同、prompt、few-shot、配置 | Solver |
| 教学证据投影实现 | 教学证据 |
| Method/Recipe 教学 Spec、学生讲解实现或配置 | 学生讲解 |
| VisualSpec、视觉绑定或交互规则 | 图形生成 |
| 页面模板、课程页 CSS/JS、编译器 | 页面编译 |

多个变化取最早边界，再重建完整后续阶段。缺少可验证的恢复材料时进一步提前，并在提交前展示原因。

## 修订与事务

SQLite 另存 `review_subjects`、`review_revisions`、`review_run_versions`；按 `parent_run_id` 迁移历史链，不改历史 run 文档，不补造旧 manifest。

题意采用独立人工修订入口：`ProblemDraft.create(parent_revision_id=...)` → 原有 Schema/数学合同/题型校验 → `ProblemPromotionService` → Context → 正式 Bundle loader。保留差异、校验报告、来源关系和 Context 祖先；不使用 `ProblemRepairPatch`，不增加假的 provider attempt。

保存修订使用基础修订 CAS，相同语义不生成新修订。构建计划包含基础修订及指纹；提交过期计划返回 409。准备产物时保持 initializing，准备完成后在事务内绑定修订、目标依赖、最新请求并入队。

worker 检查冻结的目标依赖，保存阶段 manifest，最终登记前再次检查。相关变化保存证据并以 `build.source_changed` 停止。成功运行的当前页面指针只在 SQLite 事务中更新，必须同时满足最新请求 ID、当前修订和目标 manifest。晚完成任务仍保留成功历史，不能覆盖新请求。

页面有效性与执行状态分开：当前有效、已过期、缺少版本证据。新构建失败时当前运行显示错误及重建入口；历史页面带运行版本标签。

## API

- `GET /api/review/runs/{id}/problem`：domain、Schema、基础修订。
- `POST .../problem/preview`：校验与规范化差异。
- `POST .../problem/revisions`：同一校验入口加修订 CAS 保存。
- `GET .../rebuild-plan?requested_stage=...`：复用、重跑、原因、目标指纹和模型阶段。
- `POST .../rebuild`：提交已查看的计划。

现有从阶段重跑接口保留；若要比用户选定阶段更早开始，返回 409，要求查看影响范围。所有新入口沿用本机访问限制。

## 验收

2026-09-10 验收通过：Solver 离线全量 2,502 项、后端 75 项、前端 95 项、页面工具 152 项，共 2,824 项；前端 lint、TypeScript 与生产构建通过。真实模型调用另见以下运行，不混计为离线测试。

| 验收链 | run ID | 最早执行阶段 | 新 Solver / 讲解模型调用 | 耗时 |
| --- | --- | --- | --- | --- |
| 真实完整基线 | `494213b879294151a12c94c3ee8a63c5` | source | 1 / 1，另有抽取 1 次 | 180 秒 |
| JSON 修改 b=0、c=4 | `15e7e6f693174faba0d64efd358775dd` | extraction（人工校验） | 1 / 1，抽取模型 0 次 | 95 秒 |
| 教学 Spec 修改 | `f0af8e8f87f648c6b40b1f121388b0c0` | lesson | 0 / 1 | 20 秒 |
| VisualSpec 顶点颜色修改 | `349f722e05af43cebc554b2a5a30afc4` | visual | 0 / 0 | 10 秒 |
| CSS 背景修改 | `805e9dc455014d829a670bee1e0df688` | page | 0 / 0 | 6 秒 |
| 恢复临时 Spec/CSS 后的最终页面 | `9fd75633f69546baa7ddf13b3a730f1b` | lesson | 0 / 1 | 18 秒 |

从实际 Review 页面完成 JSON 校验、保存、影响预览和提交；页面核对答案 `P(0,4)、A(-2,0)`，VisualSpec 核对 SVG 顶点颜色 `#2563eb`，CSS 核对实际页面变量 `--bg: #eef6f5`。临时模板、颜色和 CSS 改动均已恢复；保留人工修订作为验收版本，原始题意和旧页面仍可从历史运行查看。

六个运行共 54 份阶段 manifest 已逐项校验；所有复用产物逐字节、哈希及依赖闭包检查通过。后四次运行无新 Solver 调用，Visual/CSS 两次无任何新模型调用。当前页面指针指向最终运行。

详细证据位于本机 `internal/review-analysis/g3-b-acceptance/results.json` 与同目录 `verify.py`；完整输入、实际请求/响应、manifest、修订差异和页面保存在对应 Review run。该审查目录按仓库约定被 Git 忽略。

C1 教学质量 5×3 为独立专项，本轮未运行。
