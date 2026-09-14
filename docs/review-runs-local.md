# 本机 Review 运行手册

入口：[运行列表](http://127.0.0.1:3000/review/runs)。本文描述现有 SQLite/worker/SSE 实现；
工作台仍是 Mock。目标产品架构见[产品服务架构](product-service-architecture.md)，
迁移前仍按本文启动，不把 RabbitMQ/Celery 当作已经接通。

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
base URL/model 配置。密钥不写入 Review 产物。当前 `.env` 与求解代码默认模型
使用 `deepseek-v4-flash`，提取仍使用豆包；DeepSeek 多模态切换尚待实施。该模型别名不代表固定权重版本。
Review 求解的 Pass 1 和语义重试均开启 low thinking，
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
   「重新运行」创建独立记录并保留父运行及旧产物；按影响范围重建可复用有效上游。queued 任务继续顺序处理。

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
- 原有产物依赖保留审计关联；G3-B 另用明确阶段输入及 manifest 判断失效与复用，
  不直接把全部审计依赖当作重建范围。
- 代码/Spec/运行配置版本、实际模型请求、Schema、raw 返回与最终采用内容独立保存。
  全局 `source_version` 只作审计；构建检查使用阶段实际依赖指纹，包含相关 prompt、Schema、Spec 和配置。
  相关依赖变化触发 `build.source_changed`；无关文件、仅修改时间或 Review 输出不应使整条运行失效。
  执行 journal 在运行中持续导入，文件内容变化生成新 artifact，不覆盖历史版本。
- Scope Retry、transport retry、语法修复及 deterministic fallback 沿用现有服务合同。
  没有返回内容时不创建假 raw；没有 usage 时显示「未提供」。
- Snapshot 直接使用 `RuntimeOrchestrator.last_success_artifacts`，不从答案摘要重建证据。
- 上传适配不接受题号、GoldCorpusCase、authored selection 或 expected answer。
- 编译器 `--standalone` 嵌入固定 JS/CSS，不联网加载资源；内部模型文本按文本呈现。
  HTML 以 `sandbox allow-scripts` + CSP 隔离，无 same-origin 权限，不能访问 Review 的 DOM/storage/API。
- G3-B 已支持题意 JSON 编辑、预览、修订 CAS 与按影响范围重建；保存修订不自动调用模型。
- 当前不提供完整人工通过流程、公开发布、配音、新动画、任务取消、跨题缓存或生产任务部署。

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

## 验收与重建说明

当前修订、阶段 manifest、接口和有效验收摘要见[G3-B 说明](review-rebuild-g3-b.md)。
本手册不维护旧运行的耗时、测试计数及已过期的中间问题清单；历史代码由 Git 追溯，原始运行证据保留。

## 从指定阶段重跑

详情页每个阶段提供“从此阶段重新运行”。请求为 `POST /api/review/runs/{id}/rerun?from_stage=visual`，无参数仍为整题重跑。支持 source、observation、extraction、projection、solver、evidence、lesson、visual、page。

重跑会创建子记录，保留 parent_run_id/from_stage。实际起点受依赖计划约束：若需比所选阶段更早执行，返回 409 并要求查看影响范围。可复用前缀必须成功且恢复材料存在；此前产物按原始字节复制、验证 SHA256，记录 reused_from，依赖 ID 映射到子记录。当前及后续阶段重新执行，旧运行保持不变，失败时不展示旧页面。尚未结束的运行不能启动阶段重跑。源图标准化和来源身份准备开销很小，OCR 重跑时也会刷新来源配置；不会重用旧 OCR 输出。

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

实际计划仅执行图形/页面时，不需要 OCR 环境或模型密钥，也不调用模型；若失效或缺少恢复证据要求提前，按预览计划执行。更早的重跑会继续到后续模型阶段，页面注明这一点。Worker 每次派生新解释器加载当前代码；运行开始、阶段前后和最终登记检查目标依赖，相关变化会明确失败。

复用内容中的原调用 ID、路径是历史记录，保留原字节；顶层 reused_from 和 dependency 引用说明其来自哪条运行。新阶段使用新的调用审计和代码版本。此功能以 Review 的九个流水线阶段为边界，不等同于重新执行某一条内部 LLM attempt 或单个数学 Function。
