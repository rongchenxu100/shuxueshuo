# G3-A 本机真实生成与阶段 Review

入口：[运行列表](http://127.0.0.1:3000/review/runs)。独立于作者工作台的 Mock 上传接口。

## 启动

三个终端分别运行；全部只监听 loopback。不要以 `0.0.0.0` 暴露开发服务。

```sh
cd server
uv sync
uv run python -m uvicorn shuxueshuo_server.main:app --host 127.0.0.1 --port 8000
```

```sh
cd server
uv run python -m shuxueshuo_server.review.worker
```

```sh
cd frontend
npm run dev -- --hostname 127.0.0.1 --port 3000
```

所需配置沿用 `SolverRuntimeConfig`：`DEEPSEEK_API_KEY`、`DOUBAO_API_KEY`、对应的
base URL/model 配置。密钥不写入 Review 产物。2026-09-10 起 `.env` 与代码默认模型
统一使用 `deepseek-v4-flash`。Review 求解的 Pass 1 和语义重试均开启 low thinking，
通过 provider 请求选项设置，不增加 prompt 内容；学生讲解仍关闭 thinking。
不同服务端请显式配置该服务实际支持的模型；失败时不会自动切换模型或 Mock。

OCR 必须预先安装在 `server/.venv-ocr`，并准备现有 Paddle 模型；不安装到默认服务环境。
可通过 `REVIEW_OCR_PYTHON` 覆盖独立解释器。Next 的 `REVIEW_API_ORIGIN` 默认
`http://127.0.0.1:8000`，仅允许本机 HTTP(S) URL。

## 操作与恢复

1. 上传完整单题截图：PNG/JPEG/WebP、静态图片、最多 20 MiB / 2500 万像素。
2. 自动创建不可复用的 run ID、进入详情。无需阶段审批；模型调用会消耗对应服务额度。
3. 左侧选择阶段，右侧查看输入、输出、校验、调用记录。展开产物可搜索、复制、下载。
4. 最终课程页仅在全部阶段验证完成后开放，可在隔离 iframe 或独立窗口操作。
5. 关闭/刷新浏览器不会取消任务。详情从 SQLite 恢复，SSE 支持 Last-Event-ID，另有轮询兜底。
6. worker 异常退出后再次启动，将旧 running 标记 interrupted，不重做付费调用。
   「重新运行」基于原始图片创建新的记录，保留父运行及全部旧产物。queued 任务继续顺序处理。

`internal/review-runs/` 是 git-ignored 的本机数据目录，可用 `REVIEW_DATA_DIR` 覆盖，
API 与 worker 必须一致。SQLite 存 run/stage/event，文件目录存 UUID 产物和私有工作文件。
同一目录以文件锁限制一个 worker。HTTP/SSE 不承载生成任务。

Review 前端代理位于 `frontend/pages/api/review/[...path].ts`，URL 保持 `/api/review/*`。
它读取 Node 请求的 `socket.remoteAddress`，只允许回环来源；缺失来源时拒绝请求。
Host / Origin 仅作附加来源校验，`Forwarded` / `X-Forwarded-*` / `X-Real-IP`
不授予本机权限。Review 面向本机直连，不应通过对外反向代理转发；若以后需要远程使用，
应建立明确的身份认证与授权，而不是把反向代理的回环连接当作原客户端认证。

## 数据与边界

- `review-run/v1`、`review-stage/v1`、`review-artifact/v1`、`review-event/v1`。
- artifact 保存 SHA256、producer、依赖 ID；下载前重新校验 hash，禁止任意路径访问。
- G3-A 依赖采用保守的「全部先前证据」有向无环图，不做缓存复用；少数显式 raw→request 边
  直接绑定实际请求。后续 G3-B 可缩小依赖范围，但不能丢失真实消费关系。
- 代码/Spec/运行配置版本、实际模型请求、Schema、raw 返回与最终采用内容独立保存。
  构建源码哈希同时递归覆盖 `internal/llm-prompts/` 和 `internal/schemas/` 的路径与内容；
  提示词或 Schema 在构建期间修改、增加、删除或改名，均会触发 `build.source_changed`，
  拒绝登记新页面。仅文件时间变化和 Review 输出产物变化不会改变该源码哈希。
  执行 journal 在运行中持续导入，文件内容变化生成新 artifact，不覆盖历史版本。
- Scope Retry、transport retry、语法修复及 deterministic fallback 沿用现有服务合同。
  没有返回内容时不创建假 raw；没有 usage 时显示「未提供」。
- Snapshot 直接使用 `RuntimeOrchestrator.last_success_artifacts`，不从答案摘要重建证据。
- 上传适配不接受题号、GoldCorpusCase、authored selection 或 expected answer。
- 编译器 `--standalone` 嵌入固定 JS/CSS，不联网加载资源；内部模型文本按文本呈现。
  HTML 以 `sandbox allow-scripts` + CSP 隔离，无 same-origin 权限，不能访问 Review 的 DOM/storage/API。
- 运行期间源码或 Spec 变化会拒绝登记页面，要求新运行；这是版本防混用，不是 G3-B 局部重建。
- 本阶段不做编辑、审批、发布、配音、新动画、任务取消、分层复用或生产部署。

## 验证命令

```sh
cd server
uv run pytest -q tests/test_review_service.py
uv run python tools/run_solver_tests.py full
```

```sh
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
```

```sh
node --test tools/tests/*.test.mjs
```

真实外部验收与离线测试分开记录。失败运行是真实联调证据，不得替换为成功 fixture 或删除。

## 2026-09-09 真实验收记录

- [全过程 Review：d81a3338](http://127.0.0.1:3000/review/runs/d81a333888bd4b2591ef176dde54ffb8)
- [独立课程页](http://127.0.0.1:3000/api/review/runs/d81a333888bd4b2591ef176dde54ffb8/page/lesson.html)
- 从网页上传南开完整单题截图（1152×730），后续所有 rerun 均重做 OCR/模型调用；
  最终运行没有消费旧的 OCR、题意、Solver 或 Lesson 产物。
- 九个阶段成功，总耗时 261 秒；真实题意抽取 1 次，Solver 2 次调用（含 Scope Retry），
  教学 1 次调用。讲解采用混合结果：`ii` 为 deterministic fallback，其余 Scope 为 LLM，
  并有独立教学材料拆分修复；完整拒绝/修复原因见「学生讲解 → 校验」。
- 110 份登记产物逐一校验 SHA256，并验证依赖只指向本运行的既有产物。
- 浏览器验证：运行中刷新恢复、失败证据/历史 rerun、独立打开课程页、iframe 内 G/E 滑块
  联动与 SVG 更新、计算后续步骤 G/F/D′ 共线取等。未观察到浏览器 console error。
- 离线：Review API/worker 26 passed；Solver 全量 2413 passed（不运行 live_llm；serial 无匹配）；
  前端 83 passed，typecheck/lint/build 通过；页面工具 152 passed；`git diff --check` 通过。
- 真实生成页仍保留课程质量 Review 项：题号括号/分值单位重复包装、部分图中 D 标签重复。
  这不是 fixture 页面复用；它们在新规划拓扑下暴露，后续教学/视觉质量修复应保留这次产物作为证据，
  不覆盖本次成功运行，也不等同于已经完成五题课程质量验收。

## 从指定阶段重跑

详情页每个阶段提供“从此阶段重新运行”。请求为 `POST /api/review/runs/{id}/rerun?from_stage=visual`，无参数仍为整题重跑。支持 source、observation、extraction、projection、solver、evidence、lesson、visual、page。

重跑会创建子记录，保留 parent_run_id/from_stage。所选阶段之前必须全部成功，且恢复材料存在；此前产物按原始字节复制、验证 SHA256，记录 reused_from，依赖 ID 映射到子记录。当前及后续阶段重新执行，旧运行保持不变，失败时不展示旧页面。尚未结束的运行不能启动阶段重跑。源图标准化和来源身份准备开销很小，OCR 重跑时也会刷新来源配置；不会重用旧 OCR 输出。

可恢复边界：

| 阶段 | 恢复输入 |
|---|---|
| 来源/OCR | 原始上传图、规范化图 |
| 题意抽取 | initial Context、Observation Context、内容寻址的抽取产物库 |
| 输入投影/求解 | 上述 Context、Extraction Context、抽取产物库；重新通过 Bundle loader 验证来源与题意身份 |
| 教学证据 | VerifiedFunctionalPlanExecution + Evidence input checkpoint/v1（逐步 checks、答案、执行签名）+ 已验证 Bundle |
| 学生讲解 | ExplanationSnapshot；用当前教学模板重新投影材料 |
| 图形生成 | ExplanationSnapshot + 实际采用的 LessonIR |
| 页面编译 | geometry-spec、step-decorations、lesson-data 三份 JSON |

OCR 和抽取完成后会将独立产物库注册为 ZIP 检查点，每项仍按内容哈希校验。恢复时按哈希在新运行目录读取，不访问历史 locator，也不修改 Context 身份。旧记录若还留有原产物库，首次重跑时将其纳入检查点；旧记录没有完整教学证据输入时，教学证据按钮显示不可用，需从求解阶段重跑一次补齐。不能用旧 Snapshot 冒充重新执行的证据投影。

图形/页面重跑不需要 OCR 环境或模型密钥，也不调用模型。更早的重跑会继续到后续模型阶段，页面注明这一点。Worker 每次派生新解释器加载当前代码；运行开始和页面完成时比对代码版本，期间代码变化会明确失败。

复用内容中的原调用 ID、路径是历史记录，保留原字节；顶层 reused_from 和 dependency 引用说明其来自哪条运行。新阶段使用新的调用审计和代码版本。此功能以 Review 的九个流水线阶段为边界，不等同于重新执行某一条内部 LLM attempt 或单个数学 Function。
