# 手机号登录：本地运行与测试

第一阶段已接通账号、验证码核验、持久化登录 session、全站登录组件和登出。普通阿里云 `SendSms` 已由用户完成真实投递测试。第二阶段已接通 AI 登录限制与教学会话账号隔离；第三阶段已接通 PostgreSQL 学习标记、自评和题库展示。本文记录本地验证，尚未部署本次改动。

## 1. 固定本地实例

日常手动测试统一复用 `local` 实例，不随测试日期更换端口和目录。需要项目已有的 PostgreSQL 17 和 `uv`。

| 配置 | 固定值 |
| --- | --- |
| 网站与 API | `http://127.0.0.1:8779/` |
| 数据库 | `127.0.0.1:5432`，库名 `product`，应用用户 `product_app` |
| macOS 数据根 | `~/Library/Application Support/shuxueshuo/local/` |
| 数据库密码 | 数据根下 `config/app.env` 的 `PRODUCT_APP_PASSWORD` |
| 登录密钥 | 数据根下 `config/student-auth.env`，重启时复用 |

已有实例日常启动只需在仓库根目录运行：

```bash
uv run --project server python server/tools/run_site.py
```

拍题学第一期需要 `0013_student_search`（或更新）迁移。旧实例升级前先停止连接它的网站与产品服务，再运行 `./deploy/product/manage.sh --mode local deploy`；日常启动不重复迁移。拍题的四表、私有文件期限、清理/停用命令与独立测试实例见[第一期实施说明](shared-problem-library-and-student-learning-stage1.md)。拍题文件使用默认持久目录下 `work/search/private-v1/`，不把匿名旧文件自动归给当前账号。

启动器会启动或复用已安装的 PostgreSQL，随后提供静态网页、登录、学习记录和导师 API；不启动 Studio、RabbitMQ 或 Worker。数据库数据、账号和练习记录都保存在持久目录。启动日志打印实际网站地址、数据库端口和数据目录，不打印密码。显式 `--data-dir / --instance / --port` 仍可用于隔离联调；其中 `--port` 只控制网站端口，数据库端口由实例配置决定。

打开 <http://127.0.0.1:8779/> 或 <http://127.0.0.1:8779/1/q01/>。页面与 API 同源；只监听 `127.0.0.1`，不要换成 `localhost`，也不要对外转发这个开发端口。

仅新机器首次运行 `./deploy/product/manage.sh --mode local install`。已有实例需要升级表结构或导入新题目时，先停止连接它的网站与产品服务，再运行 `./deploy/product/manage.sh --mode local deploy`（先备份，再迁移、导入和自检）。日常重启不需要安装、迁移或恢复数据库。自动化测试仍使用第 5 节的隔离实例，不能使用日常或生产数据库。

### 专题内容同步

部署验收仍核对静态目录、源码导出和数据库的整体发布版本；日常专题练习改用本题的 `practice_version`。新增其他题目、修改无关图谱或展示提示，不再让未改动的题目暂停保存。修改课程后，仅重启 `run_site.py` 不会同步目录；启动器仍输出部署校验警告。

本题版本由作答契约和能力关联计算。页面先按实际加载的 HTML 配置或课包核对 `page_contract_hash`，再与 `/api/learning/content/problems/{id}` 比较；开始练习、恢复进度、关联导师均校验本题版本。步骤顺序、答案、选项含义、题干和能力关联变化仍受保护。标题、反馈、普通提示、样式、构建时间不作为作答契约。已有练习从冻结快照恢复，待保存队列也按本题版本判断兼容性。旧客户端暂时保留原全局版本检查，更新公共脚本后使用新协议。

静态练习先展示，学习服务不可用或本题不匹配仅暂停保存并提供重试；不会让整张图谱课页加载失败。

整体 `content_version` 只输出到 `site/knowledge/teaching/version.json`，用于部署核验、审计和回滚；不再复制到每个 HTML、题目 JSON、专题 JSON 和文件清单。发布时仍校验「源码导出 = 静态发布清单 = 学习数据库」，不能用删除检查代替同步。题目 JSON 只保留本题的 `page_contract_hash` 和 `practice_version`，题目路径统一放在 `teaching/problems.json`，详情页仅携带自己的资源配置。无需手动修改版本号，照常运行生成器，它只写内容真正变化的文件。

知识图谱的个人状态和目录进度是服务端按节点 ID 返回的实时只读数据，不再要求静态页面带相同的整体发布版本。五题检测从 `/api/learning/nodes` 取得本节点 `drill_version`，开始时核对该节点有效题目的身份、条目归属与内容摘要；修改其他知识点或题池不阻断本节点。修改本题池仍拒绝过期的新建请求，已返回的轮次保留冻结题目和首答记录。旧客户端的 `content_version` 协议暂时兼容；更新后的公共脚本使用按题或按题池协议。这些调整不改变拍题识别流程。

1. 若已有题目的步骤或判定规则发生变化，沿用课程版本惯例分配新的内部 ID（例如 `function-concepts-q23b-v2`），更新专题登记与页面课包引用，保留学生使用的页面地址。仅标题、反馈和提示等展示修订可沿用 ID。旧 ID 的发布内容和学习记录保留；不能直接改数据库摘要绕过检查。
2. 编译本次改动的课程，再运行 `node tools/build-public-knowledge-graph.mjs` 和 `node tools/build-topic-overviews.mjs`。用两条命令的 `--check` 确认生成文件与源码一致。
3. 停止连接日常实例的网站和产品服务，运行 `./deploy/product/manage.sh --mode local deploy`。该命令先备份，再事务发布；不要使用清空个人记录的重建操作。
4. 运行 `./deploy/product/manage.sh --mode local verify-release --site-version site/knowledge/teaching/version.json`，确认返回 `site: match` 后重新启动网站，并刷新原题页。

2026-11-03 的本地同步将函数概念 Q23（2）、Q28（1）—（4）、Q29（2）的已更新课包登记为 `-v2`；基本不等式、恒成立专题的题目身份与教学契约保持原样。

2026-11-03 按题兼容性调整验收：

- 101 道已发布题目的实际 HTML/课包、公开摘要、Python 判定投影和运行中的本地 API 全部一致；`build-public-knowledge-graph.mjs --check` 无需再生成文件。
- 前端兼容性、待提交队列、导师入口、图谱课页异步加载共 55 项通过。隔离数据库中的按题兼容性、导师续接及启动保护共 52 项通过；既有学习记录、图谱课程、导师重试回归 58 项通过、1 项跳过。
- 本地浏览器核对 `/1/q01/`、`/2/q01/`、`/topics/function-representations/q11c/` 和 `/lab/search/`，未提交学生答案。本次仅重启服务，没有运行数据库发布、迁移或改写学生记录。
- 扩展检查仍有 3 项既有断言失败：`test_learning_publish.py::test_shared_export_has_complete_next_content` 将题量写死为 45（现为 101）；`graph-walk-topic.test.mjs` 的 2 项构建一致性检查发现此前的 Q15 页面资源引用和 `function-representations-b11-v1` authored flow 尚未重建。本次未修改这些课包或批量重建课程；其余发布保护 39 项通过。

## 2. 模拟短信登录

默认使用模拟短信，不产生真实短信费用：

1. 点击页面导航中的“登录”，输入任意符合格式的测试手机号。
2. 点击“获取验证码”。本地开发站点的验证码固定为 `000000`，页面自动填入并登录；导航显示“尾号 xxxx”，点开账号菜单可退出。
3. 切换到其他题库或题目页，确认仍登录；退出后恢复游客状态。

固定验证码只在“模拟短信 + 写入本地目录”时生效（`tools/run_site.py` 启动的本地站点），模拟模式本身仅允许回环地址访问；此时不做发送冷却与频率限制，发送接口额外返回 `dev_code`。验证码仍有 5 分钟有效期、一次性核验和核验频率限制。模拟短信同时写到数据根下的 `work/mock-sms/<challenge_id>.json`。自动化测试注入的内存模拟短信仍生成随机验证码，并完整执行限流；真实短信模式从不返回验证码。

登录 HMAC 密钥首次启动时自动生成到实例的 `config/student-auth.env`，不会打印到日志。正常重启复用该密钥，已登录会话仍有效。更换密钥会使旧凭证无法使用。

### AI 登录限制验收（第二阶段）

- 游客可打开题目并点选练习，文字提问和“给点提示”会弹出登录框。取消后输入与本地选择保留。
- 登录成功后继续原来的提问或提示，不需要再次点击发送；输入验证码期间不计入 AI 请求超时。
- 登录过期时重新验证，同一账号保留本地练习与待重试请求；重试沿用原事件 ID，避免重复模型调用。
- 显式退出或切换账号会重置当前页的临时练习和对话，丢弃旧账号的迟到响应。
- `/api/tutor-demo` 整组接口检查 Cookie；匿名返回 401，登录服务关闭时返回 503，其他账号的会话返回 404。写入接口同时检查 Origin。
- 统一使用上述 8779 同源入口；旧 8765 静态页跨端口调用 8766 的方式已移除。独立 `tutor_demo.api:app` 未配置登录服务时禁止调用 AI，但仍可本地点选练习。

### 学习标记验收（第三阶段）

1. 游客完成任一道题的一条完整解题路径，出现“登录后保存这道题的练习记录”和“登录并保存”；登录框标题为“登录后保存学习记录”。未完成不自动记录。
2. 本页登录后自动保存，显示灰色“待自评”和“已保存”。
3. 选择“已熟练掌握”显示绿色“已掌握”；选择“还需再练”显示橙色“需再练”；清除选择回到“待自评”。
4. 返回题库，标题下显示练习汇总与图例，练过的题号圆圈按状态变为绿色实心、橙色粗边或灰色虚线，未练习的保持原样；“待自评”入口定位题页自评区域。重新打开题页从第一步开始，已有自评仍可修改。
5. 再次完成不会覆盖自评。断网保存失败保留本页待保存操作，恢复后点“重试保存”；不要关闭该页，当前不保存游客历史。
6. 退出或换号后清除本页账号状态；同一手机号在别的设备登录后读取同一份记录。第一、二章的 Q01 不互相影响。

前端异步状态测试在仓库根目录运行 `node --test tools/test-learning-marks.mjs`，覆盖登录衔接、失败重试、迟到响应和账号切换。

## 3. 阿里云真实短信

用户已确认使用普通短信服务 `SendSms`。在本机 `server/.env` 配置以下变量，值从阿里云已有服务取得；不要提交真实凭据：

```dotenv
ALIYUN_SMS_ACCESS_KEY_ID=
ALIYUN_SMS_ACCESS_KEY_SECRET=
ALIYUN_SMS_SIGN_NAME=
ALIYUN_SMS_TEMPLATE_CODE=
```

签名、验证码模板需可用；本版模板变量名为 `code`。在本地关闭模拟站点进程，再启动：

```bash
uv run --project server python server/tools/run_site.py --sms aliyun_sms
```

此时填入自己的真实手机号，验证码会发到手机，产生正常短信费用。后端通过 HTTPS 主动调用阿里云，无需为本地站点设置公网回调。配置缺失直接报错，不会静默回退模拟短信。

## 4. 行为与配置

**本地开发入口 `tools/run_site.py` 不限制模型调用次数**：会话、个人每日和全站每日额度均不拦截，也不写入生产额度账本。练习对话、讲解模式及格式自动重试均适用；登录、会话归属、并发和幂等保护仍保留。该入口要求 `settings.mode=local` 且认证环境为 `development`，并只监听回环地址。

线上入口仍使用以下规则：AI 次数按已登录账号每日累计，默认 `TUTOR_USER_DAILY_CALL_LIMIT=50`，北京时间零点恢复。跨题目、设备和重新登录累计，成功请求的幂等重试不重复扣次。单次教学会话 50 次与全站每日 200 次继续作为上限；页面分别提示个人或全站用尽，仍可点选练习。限额账本统一使用登录服务的 PostgreSQL，应用 `0006_tutor_usage` 迁移后从零计数，不导入旧 SQLite。无需配置 `TUTOR_USAGE_DB` 或额外数据库连接。详见 [教学额度说明](../server/shuxueshuo_server/tutor_demo/README.md#小范围公开试用控制)。

- 默认登录期限 30 天，可通过 `AUTH_SESSION_SECONDS` 配置。
- 验证码有效期 5 分钟，每个验证码最多核验 5 次；手机号 60 秒发送冷却，每 24 小时最多发送 10 次。
- 同一来源 IP 每小时最多发送 20 次，每 15 分钟最多核验 30 次；全站每 24 小时默认最多发送 200 次，可通过 `AUTH_SMS_DAILY_LIMIT` 调整。计数使用数据库中的固定时间窗，从首次请求开始；失败的短信发送也占用发送配额，服务重启不清零。
- 退出撤销当前 session，其他设备的独立 session 不受影响。跨标签页通过不含个人数据的状态通知刷新账号；退出或换号时题页重置临时教学状态，丢弃旧响应。
- 公共入口只在 `/api/auth/me` 确认服务已启用后显示：游客为“登录”按钮，登录后为“尾号 xxxx”账号按钮（手机端只显示图标），点开菜单可看脱敏手机号并退出。纯静态服务器或接口不可达时不显示入口；已登录用户遇到临时故障时保留账号按钮，菜单内提示“登录状态暂时无法确认”。手机端登录框为底部弹层。
- `AUTH_SMS_MODE=disabled` 时不显示登录入口；生产启用需设置 `aliyun_sms`、稳定的 `AUTH_SECRET`、准确的 `AUTH_ORIGIN` 和真实短信配置。
- 生产 Cookie 使用 `__Host-sss_session`、HttpOnly、Secure、SameSite=Lax、Path=/；仅本地 HTTP 使用 `sss_dev_session`，关闭 Secure。浏览器不保存可供 JS 读取的登录 token。
- 修改账号状态的请求校验精确 Origin；代理后的来源 IP 由 Uvicorn 的可信代理配置解析，应用不直接信任任意 `X-Forwarded-For`。生产 API 容器经 Docker 网桥接收 Nginx 转发（2026-10-03 服务器确认网段 `172.19.0.0/16`、网关 `172.19.0.1`），`compose.app.yml` 与 `Dockerfile.app` 的 uvicorn 已加 `--forwarded-allow-ips 172.16.0.0/12`，覆盖 Docker 默认私有地址池，网络重建后网段变化也无需修改；Nginx 保持 `$proxy_add_x_forwarded_for`，uvicorn 从右取第一个不可信地址，客户端伪造的前缀不生效。8000 只绑定 `127.0.0.1`，不向公网开放。发布后发一次请求，用 `docker logs --tail 5 <API容器名>` 确认日志里是真实公网 IP 而非 `172.x`。
- 阿里云调用只发送一次，不在网络超时后自动重试，避免重复收费。短信服务错误向页面返回通用提示，不回显验证码或签名凭据。

## 5. 验证命令

自动化测试与日常手动测试分开。首次在仓库根目录创建专用测试实例，以后重复使用同一目录和端口；已有测试实例只需 `db-start`，代码需要新迁移时用 `deploy`：

```bash
./deploy/product/manage.sh --mode local \
  --data-dir /private/tmp/sss-auth-stage1 --instance auth-stage1 --port 55439 install
```

然后在 `server/` 下执行：

```bash
PRODUCT_TEST_DATA_DIR=/private/tmp/sss-auth-stage1 \
PRODUCT_TEST_INSTANCE=auth-stage1 \
uv run pytest tests/auth -q
```

自动化测试验证真实 PostgreSQL、应用角色权限、并发验证码消费、手机号唯一身份、session 持久化与退出、CSRF、发送与核验限制、模拟文件权限和短信适配器契约，不调用付费短信或模型。缺少独立数据库配置时数据库测试会跳过，不能把跳过当作通过。

日常网站按 Ctrl+C 停止，数据库保持运行。需要停止固定数据库时，在仓库根目录执行：

```bash
./deploy/product/manage.sh --mode local db-stop
```

再次运行默认网站命令会重新启动数据库，数据不会清空。隔离测试实例的管理命令必须继续附上其 `--data-dir / --instance`。

## 7. 发布前

遵循[三阶段计划](site-login-and-learning-marks-plan.md)，三个阶段可一并发布。部署包含迁移至最新的 `0007_learning_marks`（含账号与额度迁移）、后端与主站文件，并确认登录密钥稳定且不会进入 Git。需要重新构建旧静态页面时，`node tools/add-site-auth.mjs` 可补齐不使用共享运行时的页面入口；交互题和共享 lesson runtime 会自行加载公共组件。
