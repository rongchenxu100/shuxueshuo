# 拍题学：单机生产接入与离线镜像演练

拍题服务与产品基础设施共用单机部署。准入额度及费用停止见[准入规范](search-admission.md)，数据库和私有文件恢复见[备份恢复](search-backup-restore-local-acceptance.md)。离线镜像演练不能代替真实 OCR、模型、短信或目标服务器验收。

## 1. 生产入口与持久化

服务器使用既有 `shuxueshuo_server.main:app`，`PRODUCT_MODE=server` 且非 legacy 后端时自动安装拍题 API。它与登录、产品服务复用同一个 `Settings`、PostgreSQL 引擎及应用角色，迁移必须包含 `0014_lesson_execution`、`0015_search_recovery` 和 `0016_search_admission`。不再通过开发用的 `run_site.py` 启动生产服务。

`compose.app.yml` 与应用镜像固定一个 Uvicorn worker。拍题仍使用进程内两个工作线程和本机文件锁；不能在同一数据根上启动多个 API 副本。`PRODUCT_EXECUTION_STORAGE_CONTEXT_REQUIRED=1` 禁止网页路径漏设执行上下文后回退到默认本地数据库。

私有数据位于 `${PRODUCT_DATA_DIR}/work/search/private-v1/`，容器内统一挂载 `/var/lib/shuxueshuo`。数据库只保存相对 storage key；该目录不能作为 Nginx 静态目录暴露。测试、旧匿名文件、本地虚拟环境及真实 `.env` 不打入应用镜像。

## 2. OCR 与代理

- 服务器拍题通过 `PRODUCT_OCR_URL=http://ocr:8080` 调用常驻 sidecar 的 `POST /v1/search/observe`；没有配置该变量的 Mac 开发环境保留原隔离解释器。远程失败不静默回退本地。
- 请求只有绝对图片路径及 `auto_orient`；响应为拍题所需的方向、尺寸、文本行和版面，不复用产品 OCR 的 stdout 协议。原产品 `/v1/observe` 仍可用，两种推理共享串行锁。
- sidecar 只读 `work/search/private-v1/pages/<12位十六进制ID>/source.png`。逐层无符号链接打开，并限制格式、像素、文件大小、请求及响应大小。OCR 不暴露宿主端口；不能把它作为公开无认证 API。
- 上传文件上限仍为 20 MiB；所有支持格式（包括 JPEG、PNG、WebP）统一在解码前检查 32MP（32,000,000 像素）上限，改用 JPEG 或伪造 `Content-Type` 均不能绕过。限额内图片归一化后长边最多 4096，再做 EXIF 转正、RGB 转换和元数据清除，保存后最多 4096×4096 像素，满足 sidecar 的 4000 万像素/64 MiB 限额。超限和解压炸弹返回 `413 page.pixels`；48MP/50MP 手机图片需先降低分辨率，仅压缩文件体积不够。
- API 进程内互斥解码和缩图，进入 OCR 等待前释放预处理锁，后一张图片不必等待前一张 OCR 完成才开始预处理。这减少同时解码原始大图的峰值，但不限制请求体和等待 OCR 的已缩图图像总量，不承诺并发总内存硬上限。
- 生产 Nginx 的 HTTPS 及 HTTP/CDN 入口均有独立 `/api/search/` 代理，支持 WebSocket Upgrade、20 MiB 原始上传、长连接及 `no-store`，保留原始 Origin。真实身份与归属仍由 API 验证，代理不会替客户端合成合法 Origin。
- 搜索代理丢弃客户端自报的 X-Forwarded-For 链，只传 Nginx 看到的对端；若以后增加 CDN 真实访客 IP 解析，需另行配置受信代理范围，不能直接信任任意请求头。

真实服务器还需预装匹配架构的 OCR 镜像和模型缓存，以及合法生产登录配置。修改 sidecar 使用的服务器仓库代码时，须与应用镜像保持同一版本；不支持只更新其中一侧协议。

`server/.env.example` 默认关闭付费生成与短信。正式获准启用时，需显式配置 `RUN_LLM_INTEGRATION=1`、有效 provider 密钥，以及 `AUTH_ENVIRONMENT=production`、正确的 `AUTH_ORIGIN`、`AUTH_COOKIE_SECURE=1`、稳定的 `AUTH_SECRET` 和 `AUTH_SMS_MODE=aliyun_sms` 的凭据。不开启生成门槛时，历史读取仍可用，新提交返回 `stage_one.disabled`；本次没有修改真实 `.env`。

sidecar 启动时严格预热产品和搜索模型（含方向模型），全部加载成功后才就绪，请求中不再首次加载。产品 OCR 保留原来一直等待模型锁的行为，搜索独立等锁最多 100 秒；读请求体仍限 15 秒，搜索客户端 HTTP 读取等待仍为 120 秒。API 自身的串行 OCR 锁没有排队时限、不计入 HTTP 读取等待，因此产品整页识别繁忙时，多次上传可能逐个等待 100 秒后失败，端到端耗时并无 120 秒保证；很晚才拿到 sidecar 锁的请求也可能在推理完成前超时。客户端超时不会终止已经进入 Paddle 的推理，若推理永久卡住需重启 sidecar。本次保留这些行为，详见 [OCR 排队与容量限制](../deploy/ocr/README.md#已知容量与排队限制)。真实 OCR 镜像导入、五种模型缓存、断网预热和双模型常驻内存已另行完成[本地真实镜像验收](search-real-ocr-local-acceptance.md)，不是此次 fixture 演练的结果；目标服务器仍须按[原生环境复验清单](../deploy/ocr/README.md#真实镜像本地验收与上线前复验)检查。

OCR 初期保持 **单容器、单 Python 进程**。`ThreadingHTTPServer` 可以并发接收请求，但共享模型锁仍串行推理；搜索模型的 `cpu_threads`（默认 1，`SEARCH_OCR_CPU_THREADS` 可调）不是 OCR 进程数，API 仍是一个 worker。本轮不扩 OCR 进程或副本。先测真实 CPU、RSS/峰值内存、排队时间和延迟；若产品长任务明显阻塞学生请求，再评估按产品/学生拆分实例及其模型内存成本，不能盲目增加共享 sidecar 副本。

## 3. 启停与维护

启动时先恢复遗留非终态任务为“中断”，再执行到期清理，随后每 60 秒重试清理。清理仅处理尚未完成的过期项及待清目录，不重复锁住所有已处理历史。物理删除失败会记录日志并留待下轮；HTTP 访问期限判定不等待清理完成。

`services-stop` 先持久写入 `locks/services-draining`，拒绝新的拍题 POST，保留已登录的读取及删除；先等待 API 退出，再停 worker/publisher，最后停止 OCR/RabbitMQ，PostgreSQL 保持运行。API 停机先停止接收任务并等待已有拍题线程结束，然后关闭 OCR 客户端；Compose 提供 10 分钟宽限。若被强杀，下一次启动标记中断，不自动重新计费。`services-start` 成功启动并完成检查后才清除 draining；失败时保留它，不自动恢复接单。

排空期间拍题 POST 仍返回 `503 service.draining`；学生界面将它统一显示为“系统维护中，请稍后再试。”，不把内部错误码直接展示给学生，也不因此自动重试生成。

`/api/health` 与 `services-doctor` 均显示顶层 `accepting` / `draining` 布尔值；活性正常但排空时仍可返回成功，不能把活性成功等同于已接单。doctor 不清除标记、不恢复接单（既有服务器包装脚本仍会确保依赖服务启动以便检查）。手工 `docker compose up` 不会清除持久排空状态，这是有意保留的停写保护。推荐通过正式 `services-start` 完成检查后恢复；若确需手工恢复，先确认管理操作已结束、实例正确、API/OCR/数据库检查均通过，且明确要重新接单，才删除**该实例唯一标记文件**：

```bash
rm -- /srv/shuxueshuo/locks/services-draining
```

`/srv/shuxueshuo` 必须替换成实际实例数据根，不删除整个 `locks/`。随后重新检查 `/api/health` 或 `services-doctor` 的 `accepting: true, draining: false`。若标记已不存在而内存仍处于停止准入状态，需检查/重启 API，不能靠删文件绕过。

现有发布包管理入口保持不变，参见 [产品部署手册](../deploy/product/README.md)。清理和停用使用同一个维护模块；在已配置的 API 容器内可执行：

```bash
python -m shuxueshuo_server.search.maintenance --mode server \
  --data-dir /var/lib/shuxueshuo --instance server cleanup
python -m shuxueshuo_server.search.maintenance --mode server \
  --data-dir /var/lib/shuxueshuo --instance server disable <公共题目UUID>
```

实例名必须与实际配置相同，也可继承容器的 `PRODUCT_MODE`、`PRODUCT_DATA_DIR`、`PRODUCT_INSTANCE`。上述命令不创建账号、不修改题目正文、不调用模型或短信。页面仍保留 24 小时、提交私有产物 30 天；删题不提前删除来源整页。

拍题备份恢复使用 `product-backup/v2`，登记尚未到期的页面/提交文件及其哈希、大小和原截止时间；不复制匿名或孤立目录。运行文件保持启动及每分钟清理，备份清理改为启动及每小时；上述单次 `cleanup` 和独立 `backup-prune` 立即执行，不等待定时周期。完整备份最多保留 30 天，私有文件副本仍按原截止时间提前移除，恢复不续期。数据库 dump 随备份有限保留，不承诺删除请求立即物理擦除所有备份；恢复必须先重放当前源的删除记录并过滤到期内容。

停服或删除日志故障时仍须按期清理备份。独立管理命令 `manage.sh --mode local|server ... backup-prune` 不连接数据库、不依赖删除日志；实际使用时选定一种 mode 并填写实例参数，完整示例见[部署手册](../deploy/product/README.md#备份和恢复)。停服期间由值守人员或既有系统 timer 执行，本轮不安装新的服务器调度；正常 `cleanup` 即使运行文件清理失败也会尝试备份清理。

`work/search/private-v1/recovery/deletions.jsonl` 是独立于数据库回滚的删除权威，写入并 `fsync` 后才删除数据库记录；日志仅含账号、提交 ID 及创建时间。追加失败尝试截回原长度并刷盘，初始化只允许在排他锁下、完整前缀与数据库游标校验通过后修剪末尾无换行残片；缺失、完整行/中间记录损坏、日志落后或 authority 不匹配仍失败关闭，不得手改日志或游标绕过。恢复旧备份必须额外指定当前源的 `--search-recovery-root`，不能使用旧备份内日志替代；源实例必须先停止全部写入，恢复共享锁冲突时删除返回 503（不是删除成功），不能以此代替停源。迁移中的 authority/cursor 校验不等于能判断任意离线副本是否最新，部署者须独立保管当前日志，不能用回滚数据库覆盖它。目标恢复全程 `NOLOGIN`，删除重放、到期清理、中断恢复及 doctor 全部通过后才放行；失败保留 `locks/restore-incomplete`，禁止通过 `resume`/`services-start` 绕过。操作细节与真实 PostgreSQL 本地验收见[拍题备份恢复说明](search-backup-restore-local-acceptance.md)。

含拍题数据的 `0014` 备份及所有含拍题数据的 v1 备份不支持新版私有拍题恢复。迁移到 `0015`、当前日志首次初始化成功后，必须立即停止业务写入和清理，创建并核验首份 v2 备份、独立保管当前日志，然后才重新接单；在这份备份建立前没有新版拍题可用恢复点，不应等下一次日常备份。

隔离恢复演练不切流量，原源实例继续作为当前权威；若以后正式切换到恢复目标，须同时切换到目标新 journal 并立即创建新 v2 备份。旧备份与新 authority 不匹配时失败关闭，不能再把旧备份和仍存在的旧源日志当作最新恢复入口；工具不自动决定哪个实例已成为正式源。

## 4. 可复现的离线镜像演练

使用本机已存在的应用、管理、PostgreSQL、Nginx、RabbitMQ 和真实 OCR 镜像，不拉取镜像。应用和管理镜像的依赖锁必须与当前 `deploy/product/requirements.lock` 相同；脚本复用缓存依赖层，再按生产 Dockerfile 的 COPY 和启动段装入当前代码，并检查镜像未包含测试及 `.env`。

```bash
python3 deploy/product/rehearse-search.py \
  --app docker.io/library/shuxueshuo-product-app:p2-app-202610151203 \
  --admin docker.io/library/shuxueshuo-product-admin:p2-app-202610151203 \
  --postgres docker.io/library/shuxueshuo-product-postgres:p1-20260912 \
  --nginx docker.io/library/nginx:1.28-alpine \
  --rabbitmq docker.io/library/rabbitmq:4.3.2 \
  --ocr docker.io/library/shuxueshuo-ocr:3.3.0 \
  --output /private/tmp/search-image-rehearsal-new
```

输出目录必须全新且位于仓库外。构建使用 `--network=none`，运行合并原生产 `compose.yml`、`compose.server.yml`、`compose.app.yml` 与隔离 overlay：只使用独立内部网络，不发布宿主端口；数据库从空卷通过真实迁移和应用授权安装。保留生产依赖健康检查、admin 只读根目录与 API 十分钟排空宽限，启动原产品 worker/publisher 但不投递产品任务。TLS 使用一次性自签名证书，Nginx 使用原生产配置；不挂载日常数据库或真实模型/SMS `.env`。Nginx 与 API 共享网络命名空间，以保留配置中的 loopback 上游；这不是服务器宿主 Nginx 网络拓扑验收。

仅在 `/rehearsal:ro` 挂载测试适配器：短信写本地 fixture，新公共身份复核是明确标记的合成数据，阶段二回放已核验录制；真实 OCR 镜像运行当前 sidecar，但预热和推理使用 fixture，不加载 Paddle 模型。生产认证、真实 OCR HTTP 传输与路径检查、阶段三 PostgreSQL 执行、HTTP/WS 和 Nginx 均未替换。测试适配器不进入发布镜像，不能用于线上。

脚本检查登录 Cookie、匿名及跨账号拒绝、上传旋转、错误 Origin、20 MiB/32MP/4096 边界、幂等提交、课程快照/事件及 TLS WebSocket、停机准入、运营停用、删题及整页保留、重启中断和到期清理，并执行一次服务器模式维护命令。准入检查使用未覆盖的生产默认限额：账号每日 10/3、全站 100/50、上传 2/10、生成账号 1 与全局 2+4；日额度使用明确标记的隔离账本预置和真实边界 HTTP 请求，不冒充实际生成 150 次。费用开关初始关闭，由维护 CLI 显式开启，热停止取消等待任务，重启后保持关闭。结束时清理本次临时容器、网络和数据库卷；输出保留镜像 ID、源码版本及脏工作树摘要、日志与 `report.json`。只有 `passed: true` 才表示该轮完成。

输出目录还含一次性测试凭据与 Cookie，不应提交或公开。演练派生镜像留在本机，后续可按输出记录的名称清理。本工具不是正式 `build-release.sh` 发布包，不绕过其干净工作树和提交快照要求。

## 5. 验收边界

- 缓存依赖层演练不等同于从零联网安装依赖，也不等同于服务器架构的性能测试。
- 没有调用付费模型、真实短信或 Linux Paddle 推理；实际 OCR 镜像/模型缓存和真实供应商配置仍需在授权后另行验收。
- 本次不启动或扩展拍题的 RabbitMQ/Celery 路线。原产品服务仍保留它们；拍题仅在单 API 进程内运行。
- 本次不新增业务能力、跨设备进度、集群调度或自动线上发布。
- 私有拍题文件与删除/到期重放现使用 v2 备份恢复契约，验收状态单独记录在[拍题备份恢复说明](search-backup-restore-local-acceptance.md)，不由历史产品备份验收代替。长期容量/配额、锁文件 inode 运维及当前删除权威的独立异地保管仍是上线前工作；本轮不实现账号注销。

## 维护拒绝与上传限制

维护拒绝后保留原图、手动选区、课程和提交幂等键，不自动重试 POST；换号后的迟到响应不能更新界面。所有支持格式统一按 32MP 上限在解码前检查，不能通过改用 JPEG 绕过；超限须降低分辨率。上传大小、像素数和并发内存是不同限制，目标服务器的峰值内存和 OCR 排队仍需实际测量。
