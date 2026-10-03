# 手机号登录：本地运行与测试

第一阶段已接通账号、验证码核验、持久化登录 session、全站登录组件和登出。普通阿里云 `SendSms` 适配器已实现，真实投递需配置并联调。AI 登录门禁与学习标记仍属于后续阶段，当前版本不单独部署到公网。

## 1. 独立本地实例

本机需要项目已有的 PostgreSQL 17 和 `uv`。以下命令在仓库根目录执行，创建独立开发数据库，不修改正在使用的产品实例。数据和模拟验证码均位于静态站点目录以外。

```bash
cd server
uv run python -m shuxueshuo_server.product.admin.cli \
  --mode local --data-dir /private/tmp/sss-auth-stage1 \
  --instance auth-stage1 --port 55439 install

uv run python tools/run_site.py \
  --data-dir /private/tmp/sss-auth-stage1 --instance auth-stage1
```

打开 <http://127.0.0.1:8767/> 或 <http://127.0.0.1:8767/1/q01/>。页面与 API 同源；只监听 `127.0.0.1`，不要换成 `localhost`，也不要对外转发这个测试端口。

已有独立实例需要新迁移时，用相同 `--data-dir`、`--instance` 执行管理 CLI 的 `migrate` 命令。不要把生产实例的数据库 URL 用于自动化测试。

## 2. 模拟短信登录

默认使用模拟短信，不产生真实短信费用：

1. 点击页面导航中的“登录”，输入符合格式的测试手机号。
2. 点击“获取验证码”。模拟短信写到 `/private/tmp/sss-auth-stage1/work/mock-sms/<challenge_id>.json`，查看最新文件中的 `code`。
3. 填入该六位验证码并登录；导航显示脱敏手机号和“退出登录”。
4. 切换到其他题库或题目页，确认仍登录；退出后恢复游客状态。

模拟文件仅供本机测试，目录权限为 0700，文件权限为 0600；网页和 API 不返回验证码。不是固定万能验证码，过期、错误次数、发送冷却和一次性核验与真实模式共用。临时目录可能被系统清理；需要长期保留测试账号时，使用自己的独立持久数据目录。

登录 HMAC 密钥首次启动时自动生成到实例的 `config/student-auth.env`，不会打印到日志。正常重启复用该密钥，已登录会话仍有效。更换密钥会使旧凭证无法使用。

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
uv run python tools/run_site.py \
  --data-dir /private/tmp/sss-auth-stage1 --instance auth-stage1 --sms aliyun_sms
```

此时填入自己的真实手机号，验证码会发到手机，产生正常短信费用。后端通过 HTTPS 主动调用阿里云，无需为本地站点设置公网回调。配置缺失直接报错，不会静默回退模拟短信。

## 4. 行为与配置

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

在 `server/` 下执行：

```bash
PRODUCT_TEST_DATA_DIR=/private/tmp/sss-auth-stage1 \
PRODUCT_TEST_INSTANCE=auth-stage1 \
uv run pytest tests/auth -q
```

自动化测试验证真实 PostgreSQL、应用角色权限、并发验证码消费、手机号唯一身份、session 持久化与退出、CSRF、发送与核验限制、模拟文件权限和短信适配器契约，不调用付费短信或模型。缺少独立数据库配置时数据库测试会跳过，不能把跳过当作通过。

本地站点按 Ctrl+C 停止；如需停止该独立数据库：

```bash
uv run python -m shuxueshuo_server.product.admin.cli \
  --mode local --data-dir /private/tmp/sss-auth-stage1 --instance auth-stage1 db-stop
```

## 6. 本次验证结果（2026-10-03）

- PostgreSQL 17.10 独立实例完成 `0005_student_auth` 迁移与权限自检。
- 登录测试 14 项通过；交互题非真实模型测试 279 项通过，53 项真实模型测试未执行。
- 合并运行登录、产品管理/API/数据库及交互题回归：351 项通过，5 项旧内容生成测试失败。用 HEAD 版本的已修改 product 模块在相同数据库上复现了相同失败：四项 `test_complete_page_and_resource_access` 缺少新版流水线要求的产物，一项 `test_definition_versions_and_deferred_stage_set` 重复定义已有 v3。未在登录变更中修改这些内容生成测试。
- 独立 lesson 编译测试通过；新增 Python 代码 Ruff 检查通过。
- 浏览器完成“模拟发码 → 登录 → 首页切到 Q01 仍登录 → 退出恢复游客”验证，登录弹窗无控制台错误。阿里云发送适配器只做了请求契约与失败处理测试，没有发送真实短信。

## 7. 发布前

遵循[三阶段计划](site-login-and-learning-marks-plan.md)，阶段 1、2 一起首次发布。部署包含 `0005_student_auth` 迁移、后端与主站文件，并确认登录密钥稳定且不会进入 Git。需要重新构建旧静态页面时，`node tools/add-site-auth.mjs` 可补齐不使用共享运行时的页面入口；交互题和共享 lesson runtime 会自行加载公共组件。
