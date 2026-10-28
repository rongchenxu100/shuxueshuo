# 拍题准入、每日额度与费用停止开关

日期：2026-10-25。范围仅为既有拍题链路的单机保护；不增加收费业务、分布式队列、Redis、自动重试或 OCR 进程。本轮不调用付费模型或真实短信，不部署线上、不 push。

## 1. 业务规则

| 限制 | 默认值 | 计量范围 |
| --- | --- | --- |
| 每账号每日新生成 | 10 次 | 新拍题、主动重拍、重新识图；同一提交的识别、原图复核与课程生成合计一次 |
| 每账号每日课程重跑 | 3 次 | 对已有提交重新生成一轮课程，整个账号共用，不是每题三次 |
| 全站每日新生成 | 100 次 | 所有账号合计，与账号额度同时满足才接受 |
| 全站每日课程重跑 | 50 次 | 所有账号合计，与账号额度同时满足才接受 |
| 每账号生成并发 | 1 个 | 排队和运行中的任务合计；跨标签、跨设备共用 |
| 全局生成容量 | 2 个运行 + 4 个等待 | 新生成、重跑、原运行继续计算共用；队列满立即拒绝，不无限排队 |
| 每账号上传/OCR 在途 | 2 个 | 上传与旋转共用，覆盖解码、缩图及 OCR；防止单个账号占满全站入口 |
| 全站上传/OCR 在途 | 10 个 | 全部账号共用；超限立即拒绝，不再另加排队层 |

上传及旋转走同一套 OCR 在途保护；OCR 仍为一个进程，推理串行。单账号最多两个在途请求，全站最多十个；这不是严格公平调度，也不代表十份模型并行。解码及缩图继续一次一张，锁在 OCR 等待前释放；文件上限仍为 20 MiB，全部格式统一 32MP，归一化长边最多 4096。

在读取请求体之前先校验账号、Origin 和换号标识，再占用上传名额。客户端取消请求不能提前释放仍在运行的 OCR 线程所占名额；名额保持到实际线程完成。取消后尚未启动的处理不能重新占位启动 OCR。

每日额度按 **Asia/Shanghai 的自然日**结算。受理时预留，开始执行时消耗；跨午夜的任务仍计入受理当天。未开始执行便取消、入队失败或明确被拒绝时释放预留；开始后的识别失败、不支持、超时或课程失败仍消耗额度。删除题目、到期清理、退出、换设备及重启不能退回已经消耗的次数。

同一 `client_request_id` 的网络重试不重复计次。一次用户主动操作生成一个 ID；在网络结果不明确时保留该 ID 手动重试，不自动循环提交。新生成接口沿用既有 ID；课程重跑 `POST /api/search/problems/{search_id}/lesson` 的 JSON 请求体也携带 `client_request_id`。请求 ID 按登录账号隔离，页面退出或换号时丢弃旧账号标识与迟到响应。

提交删除后，旧请求 ID 不能复活该提交：返回 `409 search.request_retired`，不创建记录也不新增额度。前端提示旧记录已删除并清空对应请求意图，下一次手动点击才生成新 ID；网络超时等结果不明的失败仍复用原 ID，不自动重试。未使用的 `search.request_pending` 错误码已删除。

读取历史、图片、课程、事件流、删除题目和退出不消耗额度。`lesson/start` 与原 `run_id` 的 `resume` 继续已有运行，不额外扣每日生成/重跑额度，但仍受账号并发、全局容量及原运行持久预算约束；不重置预算。等待学生交互时不占后台运行槽。

前端区分“账号正在处理”“账号今日额度用完”“全站今日额度用完”“系统繁忙”“生成暂停”。限制数字不硬编码到拒绝文案中，配置调整后文案不失真；拒绝不会丢掉当前选区或已有课程，不会自动重试。全站次数是工作量保护，**不是人民币费用硬上限**；不同题目、模型重试和单次调用的费用仍可能不同。

## 2. 配置

在 API 进程的环境中配置，默认值见 `server/.env.example`；调整后重启 API 生效：

```dotenv
SEARCH_GENERATION_ACCOUNT_DAILY=10
SEARCH_RERUN_ACCOUNT_DAILY=3
SEARCH_GENERATION_GLOBAL_DAILY=100
SEARCH_RERUN_GLOBAL_DAILY=50
SEARCH_GENERATION_ACCOUNT_CONCURRENCY=1
SEARCH_GENERATION_WORKERS=2
SEARCH_GENERATION_QUEUE_SIZE=4
SEARCH_UPLOAD_ACCOUNT_LIMIT=2
SEARCH_UPLOAD_GLOBAL_LIMIT=10
```

额度、幂等受理与开关复用现有 PostgreSQL。任务实际执行仍为本机线程池；只支持一个 API worker、一个 API 实例使用该数据根，不把数据库计数解释成已支持多机调度。保持 OCR 单进程，不通过上述变量扩容 OCR。

已显式配置 `SEARCH_UPLOAD_ACCOUNT_LIMIT=10` 的实例需将该值改为 `2` 并重启 API；更改代码默认值不会覆盖现有环境变量。

应用启动前须按现有停服、备份及迁移流程应用 `0016_search_admission`，新增 `search_admission_control` 与 `search_admission_tickets`。准入票据不随私人提交级联删除，应用角色不能删除额度账本或改写账号、题目和受理日期。现有 `0015` v2 备份可以恢复后迁移到新版本，但恢复目标一律关闭费用开关。

后台任务完成或取消时若数据库短暂不可用，保守保留其容量占位并重试终态写入；写入恢复后再派发等待任务。补偿只修复账本及未完成状态，不重新执行模型、不重复释放文件锁；进程重启仍按原规则将遗留任务标为中断。

## 3. 费用停止与恢复

费用开关持久化在 PostgreSQL，初始为关闭，**没有一个默认自动开启的环境变量**。需要操作员明确开启；`RUN_LLM_INTEGRATION=1` 仍是独立的付费 provider 门槛，单独开启任一门槛均不能绕过另一个。

以下命令从 `server/` 执行。先核对数据根和实例名，不要把本地验收实例换成日常数据库；服务器选择 `--mode server` 及容器内真实数据根。在已配置的 API 容器里去掉 `uv run` 即可：

```bash
uv run python -m shuxueshuo_server.search.maintenance --mode local \
  --data-dir /private/tmp/sss-search-stage1 --instance search-stage1 generation-status
uv run python -m shuxueshuo_server.search.maintenance --mode local \
  --data-dir /private/tmp/sss-search-stage1 --instance search-stage1 generation-stop
uv run python -m shuxueshuo_server.search.maintenance --mode local \
  --data-dir /private/tmp/sss-search-stage1 --instance search-stage1 generation-enable
```

`generation-stop` 无需重启 API：立即阻止新生成和重跑；排队中尚未执行的计费任务在后台检查后取消并释放预留。运行中的后续每次付费模型请求在实际 transport 发出前重新检查开关，包含识别、复核、修复和 provider 重试。已经发出的调用不能保证终止或退款；如果剩余步骤完全在本地计算，运行中的任务仍可能正常完成。关闭时已经占用的运行资源需要等当前工作退出，不能把关闭理解为强杀线程或承诺所有在途任务都变为“中断”。

拍题识别与课程生成在创建 live provider 前必须存在准入任务上下文；漏设时直接失败，不创建 provider 或发送模型请求。通用 provider 的可选检查保留兼容性，不把非拍题业务误纳入本功能的额度控制。

只读访问、删除和纯本地的原运行继续计算仍可使用；如果后续路径需要新付费调用，仍被开关拦住。再次开启不会自动重新提交已中断任务，学生需要明确操作。开关只覆盖拍题生成，不替代全产品其他模型功能、短信或供应商账号的费用控制。

从旧备份恢复会回滚备份之后的额度计数，因此恢复目标强制关闭生成开关。操作员必须核对目标实例、当前费用和当日额度风险，再显式开启；旧备份中“已开启”状态不能自动恢复接单。删除和到期不复活仍遵循原独立删除日志及恢复流程，本功能不改变那些规则。

## 4. 离线回归与验收

不得用数据库测试跳过代替成功。后端应使用独立 PostgreSQL、应用角色、MockSMS、明确标记的离线 fixtures；`RUN_LLM_INTEGRATION=0`，在测试边界注入 fixture provider，禁止调用真实模型或短信。验收至少覆盖：

- 账号 10/3 和全站 100/50 边界、两个账号并发争最后一个名额、上海午夜、跨午夜排队、删除不退款、重启保留消费。
- 单账号只能有一个排队/运行任务；两个运行槽加四个等待满后立即拒绝；结束、异常、未执行取消和入队失败释放槽与对应预留。
- 新生成与课程重跑各自幂等；网络重试只扣一次；同 ID 不得跨账号、操作或题目误用；原运行继续计算不新增每日次数。
- 停止开关默认关闭、持久化、热关闭、排队取消；运行中下一次付费调用被阻断，已完成课程仍能读取；恢复目标强制关闭。
- 上传/OCR 同账号前两个请求可受理、第三个立即拒绝，其他账号仍可使用余下名额；全站十个可受理、第十一个拒绝。并发争用也不能突破两个边界，上传异常、无效图片、旋转异常及断连正确释放名额；解码串行不占住 OCR 等待。
- 前端七类 POST 的全部准入提示不泄露内部码、不自动重试，不丢选区/课程；重跑重复点击只发一个请求，网络不明重试保留 ID，终态后主动重跑新 ID；退出/换号后迟到成功不得恢复课程。

### PostgreSQL 与后端

```bash
cd server
PYTHONDONTWRITEBYTECODE=1 RUN_LLM_INTEGRATION=0 RUN_SEARCH_BACKUP_RESTORE_TEST=1 \
PRODUCT_TEST_DATA_DIR=/private/tmp/sss-search-stage1 PRODUCT_TEST_INSTANCE=search-stage1 \
uv run pytest -q -ra tests/search tests/auth/test_auth.py tests/auth/test_tutor_auth.py \
  tests/product/test_search_backup_restore.py tests/product/test_search_backup_files.py \
  tests/product/test_restore_fence.py tests/solver/test_deepseek_files.py \
  tests/solver/test_math_notation_providers.py tests/solver/test_problem_domain_provider.py
```

独立 PostgreSQL 实例为本机 `55443`，不是日常实例；已完成 `0016` 迁移。审查修复后的结果 **1073 passed，5 skipped，0 failed**（297.05 秒），日志 `/private/tmp/search-admission-review-final-20261025.log`；没有数据库测试跳过。五项跳过均为需要隔离 OCR 解释器的方向测试，已用下列命令补跑，**5 tests OK**，日志 `/private/tmp/search-admission-review-ocr-20261025.log`；使用假模型和数组 fixtures，不加载或调用真实模型。

```bash
PYTHONDONTWRITEBYTECODE=1 RUN_LLM_INTEGRATION=0 \
.venv-ocr/bin/python -m unittest discover -s tests/search -p test_ocr_orientation_worker.py
```

完整回归包含入队失败后的恢复、数据库短故障后的完成/取消补偿、请求断连后 OCR 名额保持，以及清理与另一页面准入的锁顺序。本次新增验证默认账号 2／全站 10 的并发边界、删除后旧 ID 并发重试不新增记录或额度、换账号不误命中旧 ID，以及两个拍题 provider 入口缺失上下文时零创建、零发送。相关实现和测试的离线 Ruff 检查、`git diff --check` 均通过；后端仅有既存 Alembic `path_separator` 配置弃用警告。

### 前端

```bash
node --test tools/tests/*.test.mjs
```

结果 **919 passed，0 failed，0 skipped**，日志 `/private/tmp/search-admission-review-node-20261025.log`。包含全部准入消息、删除后旧请求 ID 的手动恢复、网络不明时保留 ID、重跑幂等、跨账号迟到响应，以及原跨标签登录、历史分页、删除和进度隔离回归。

### 真实本地 HTTP＋离线 fixtures

```bash
cd server
PYTHONDONTWRITEBYTECODE=1 RUN_LLM_INTEGRATION=0 \
PRODUCT_TEST_DATA_DIR=/private/tmp/sss-search-stage1 PRODUCT_TEST_INSTANCE=search-stage1 \
uv run python -m tests.search.local_admission_rehearsal \
  --output /private/tmp/search-admission-review-local-20261025.json
```

脚本先绑定空闲 loopback 端口，再创建独立数据库 schema；端口占用时失败，不停止已有服务。本次实际使用 `57598`，报告 `passed: true`，配置确认上传/OCR 每账号 2／全站 10；验证模拟短信登录、上传/旋转、默认关闭、10/3 边界、幂等、账号并发、历史分页/账号隔离、停止后读取和删除、同题十条记录删除后源页面保留、已用额度不退回。

fixture 识别十次、课程十三次，**付费模型调用 0，真实短信 0**。已有 `8779` 服务未替换；这不是浏览器视觉验收、真实模型识别、TLS 或线上容量证明。Docker 离线演练入口已同步准入开关与额度断言，但本轮没有重建或运行 Docker 镜像，也没有增加 OCR 进程。

后续已另行完成[最终容器离线演练](search-single-host-production.md)：重新构建最新应用/管理镜像，运行原生产三份 Compose 与 Nginx，通过默认 10/3、100/50、上传 2/10、生成 1 与 2+4，以及默认关闭、热停止和关闭状态跨重启验收。日额度采用明确标记的隔离票据预置与真实 HTTP 边界请求，未调用付费模型或真实短信；该报告与本节早先的无 Docker 验收分别保留。
