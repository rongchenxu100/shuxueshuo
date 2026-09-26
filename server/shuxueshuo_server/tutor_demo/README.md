# Q01 对话教学演示

前端继续使用 `site/demo/q01.html` 的交互组件与展示组件，部署时 API 随现有 `shuxueshuo_server.main:app` 运行，本机开发也可独立启动。题目、两条教学路径、节点通过标准、方法解释来自 `lessons/q01.json`。这是一版 Q01 专用适配器，图形和数学推导仍由前端已有展示组件渲染，并非任意 LessonIR 的通用渲染器。

## 启动

在 `server/.env` 或环境变量配置已有的 `DEEPSEEK_API_KEY`。复用 `DEEPSEEK_MODEL`、`DEEPSEEK_BASE_URL`；可用 `TUTOR_DEEPSEEK_MODEL` 单独覆盖模型。默认模型与本仓库当前 DeepSeek 配置一致。密钥不进入静态文件或响应。

从仓库根目录：

```sh
cd server
uv run uvicorn shuxueshuo_server.tutor_demo.api:app --host 127.0.0.1 --port 8766
```

直接打开 `http://127.0.0.1:8766/demo/q01.html`，同源访问 API。已有的 `http://127.0.0.1:8765/demo/q01.html` 也可使用：页面在本地 8765 时调用同主机的 8766，后端仅允许这两个本地 8765 origin。其他地址默认使用同源 `/api/tutor-demo`。

```sh
uv run pytest tests/tutor_demo -q
```

## 随现有后台部署

`main.py` 注册 `create_router()`，与独立开发入口共用 `/api/tutor-demo` 路由。路由 lifespan 负责关闭 DeepSeek 客户端，并保留原 product 应用的启动和资源清理流程。

1. 按仓库 `deploy/release.md` 构建并发布新版产品 API 镜像。现有 Dockerfile 会复制整个 `server/`，包括教学 JSON 和 Jinja 模板；只更新宿主机代码不会更新容器内 API。
2. 将 `site/demo/` 随主站静态文件发布，访问 `/demo/q01.html`。页面使用同源 `/api/tutor-demo`；现有 Nginx 的 `/api/` 转发到 8000，无需新增服务、端口或转发规则。
3. 服务器现有 `server/.env` 只读挂载到 API 容器，配置 `DEEPSEEK_API_KEY` 及需要的模型覆盖。修改配置后重启 API 容器。

发布后检查 `POST /api/tutor-demo/sessions`（JSON 请求体 `{"lesson_id":"q01"}`）返回 201，再在页面发送一句话验证实际 DeepSeek 配置。`/api/health` 仅说明后台存活，不验证模型密钥。

当前会话在进程内存中，沿用现有 Compose 的单进程 API；不能直接增加 Uvicorn workers 或 API 副本。重启会清空会话，已有页面需重新体验。未来多实例与进度恢复需要共享存储。

## 会话契约

- `POST /api/tutor-demo/sessions`：`{"lesson_id":"q01"}`，返回新的 session_id、revision=0、页面配置和空状态。
- `POST /api/tutor-demo/sessions/{id}/events`：event_id、revision、kind（ui/text/help）、action 或 text。返回完整权威状态和对话记录。
- `GET /api/tutor-demo/sessions/{id}`：读取快照。

UI action 分为 method、fill、swap、choice、submit，只能作用于当前节点。点击选择/填写存为 student/ui 结构化事件；输入文字存为 student/text；点击提示存为 student/help。打开候选菜单、滚动等不入历史。点选不调用模型，文字与提示调用一次 DeepSeek。每轮最多完成一个节点。

`session.py` 持有当前状态、当前节点接受的证据、完整事件序列和已完成节点快照。两个 Jinja 模板每次根据文件中的教学定义、当前节点要求、已完成摘要、当前节点最近24条记录与最新输入生成。不会不断累积已渲染 prompt。

模型返回简短回复、意图、证据和有限操作建议；服务端校验枚举、当前节点、必需证据、正项映射和取值条件后原子应用。证据齐全时按节点的 text_autofill 补齐确定的 m/n 或 yes 映射，并自动提交；完成回复用节点的 completion_reply 简短确认本步结论，信息齐全后不再追问，下一问题由下一张步骤卡提出。帮助请求与 question/other 意图不能改状态。不合法操作全部回滚，并用澄清问题替代可能声称“已完成”的回复。自然语言语义判断仍依赖模型，尚无通用符号证明器或全面错因评测。

页面按节点展示学生文字和老师回复；当前节点展开，已完成节点的对话默认折叠，可通过“查看本步对话”展开，手动展开/收起状态在页面更新时保留。等效答案自动填入和提交，无需重复点选。数学组件依旧负责呈现完整公式/图形，模型文字以转义后的纯文本呈现。

## 重试与重新体验

请求使用 revision 和 event_id。单会话串行处理，过期 revision 返回409；最近8个事件结果支持幂等重试。模型失败不修改状态或插入半条对话，页面保留输入并显示重试。等待回复期间暂停操作；重新体验随时可用。

重新体验创建新会话并清空页面输入、状态、对话与提示计时。旧响应通过前端会话代数丢弃，不会写入新页面。旧会话不再参与教学，内存中最多保留2小时；会话上限200、每会话消息上限400。刷新页面也创建新会话。服务重启后内存记录消失。

## 当前边界

定位为教学演示。未实现用户认证、持久化、按用户的调用配额、分布式会话、真正的token流式输出；公开地址上的访客可触发模型调用，现有 product 接口的权限边界不会自动覆盖 `/api/tutor-demo`。有限字段校验不能取代完整数学语义验证，后续需用错答/歧义输入回放评测迭代。已有10秒邀请提示仍是前端交互，只在学生主动点提示后调用模型。

## 多路径尝试与节点契约（v2）

同一个 session 下有多个 attempt。`attempt_id` 指向当前尝试；`attempts` 保存每次尝试的路线、状态（learning / paused / completed）、组件状态、节点快照、证据与对话。顶层 `messages` 是按 revision 排序的完整事件流，每条带 attempt_id、route、stage；顶层 state/completed/accepted_evidence 只属于当前尝试。

`switch_route` 是流程操作，value 必须属于 LessonIR 提供的可用路径。无论当前路径正在学习或已完成，都创建新 attempt，从目标路径首节点开始。原尝试以不可变快照保留，历史对话折叠展示。显式再做同一路径也创建新尝试，不恢复旧通过状态。重新体验仍创建全新 session。

模型输出的 `route_change` 意图只能包含一个 switch_route，不得同时填写、提交新节点。不存在的路径、混合操作、过期 revision 均不能修改当前尝试。切换确认由执行器成功后生成，不直接使用模型声称成功的文字。UI 切换按钮与文字请求走同一执行器。

`contracts.py` 根据作者提供的节点契约执行动作，不含 Q01 的变量、路由 id 或节点数量判断：

- initial_state：本题组件初始状态。
- interaction.actions：组件支持的动作、索引、候选值，以及服务端内部字段路径/值映射。
- interaction.validators：有限的 equals / set_equals / not_empty 判定算子及提示。
- required_evidence / criteria：语义通过标准。
- text_autofill / completion_reply：证据齐全后的确定性映射与简短确认。
- verified_facts / bindings：当前节点已核验事实及对象绑定；占位符使用双花括号。

通用 system prompt 只定义教学规则、流程意图和输出契约，不再包含本题变量、答案、路线 id 或针对本题的 few-shot。turn prompt 只传题目与方法说明、当前节点契约、可执行流程动作、本次路径的已完成节点及当前节点对话；初始选方法时补充各可选路径的首节点契约。旧尝试只作为路径进度摘要提供，旧证据不参与新尝试判定。内部可写路径与校验器不会交给模型或浏览器。

验证包含完整切换、途中切换、同路径重试、未知路径拒绝、过期事件、提示/疑问不切换、历史证据隔离，以及用不同变量和单节点路径验证执行器。真实模型验收可运行：

```sh
RUN_TUTOR_LIVE=1 uv run pytest tests/tutor_demo/test_tutor_live.py -q -s
```

这一版泛化的是会话流程、prompt 和契约执行器。Q01 的数学标准仍应由教学文件声明，前端图示仍是 Q01 展示适配器；尚未实现通用数学证明器、通用 LessonIR 渲染器或可复用 Method 教学目录。新增复杂题目可能需要新的受限契约算子和展示组件，不能仅凭本次验收宣称覆盖任意数学题。
