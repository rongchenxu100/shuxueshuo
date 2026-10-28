# 公共题库、学生关联与解析复用：第一期实施说明

本文维护学生拍题的登录、公共题目身份、个人历史和私有数据生命周期。执行状态统一使用[PostgreSQL 存储](stage-three-postgresql-execution-storage.md)，备份与删除重放见[恢复契约](search-backup-restore-local-acceptance.md)。公共课程包和跨设备作答同步仍属后续范围。

## 1. 已接入的实现

- 现有手机号 Cookie 登录用于 `/api/search`，写操作验证 Origin；所有页面、提交、图片和课程读取以数据库中的用户归属为准。WebSocket 在连接及推送期间检查身份与权限。
- `0013_student_search` 新增 `search_problems`、`student_search_problems`、`search_pages`、`search_submissions` 四表。公共题目不要求 workspace 成员身份，正文不可变，只允许停用状态变化。
- 阶段一通过新的 `search-problem-extraction/v1` 契约提供规范公共题面与复核证据；v1 身份构造器只在来源已复核、身份内容完整时归并，不用图片哈希或答案替代题目身份。不能安全构造身份的提交保留为个人待确认记录。
- `POST /api/search/problems` 的 `client_request_id` 按账号唯一。网络重试返回已有提交，只有新插入的提交启动任务；主动再次拍摄使用新请求 ID。
- `GET /api/search/problems?limit=20&offset=0` 从数据库分页查询，已关联同题聚合一条，未关联提交独立显示。打开入口优先最近有可用私有课程的提交，另行显示最新提交状态。
- `DELETE /api/search/problems/{search_id}` 删除该账号该公共题目的全部已关联提交；未关联记录只删除自身。删除时尚未关联的其他提交之后可以正常建立新的历史关系。
- 第一期课程继续按每次私有提交生成，不创建公共课程包。个人作答仅在浏览器本机按账号和课程作用域保存。

## 2. 存储、期限与删除

数据库和文件均使用 `Settings` 配置的持久实例目录。macOS 默认目录为 `~/Library/Application Support/shuxueshuo/local/`；文件存放在其 `work/search/private-v1/` 下，数据库只保存相对 storage key。

| 路径/数据 | 用途与保留规则 |
| --- | --- |
| `pages/<page_id>/` | 整页 source/page/preview、OCR、区域文件；首次上传起 24 小时，旋转副本继承原期限 |
| `submissions/<search_id>/` | 独立 `original.png` 原始裁剪图、`question.png` 预处理图、转录、模型调用、各阶段课程与 `unsupported` 产物；提交起 30 天 |
| `locks/` | 独立生命周期与读取文件锁；不存照片、题面或模型内容 |
| `search_pages.pending_cleanup_keys` | 事务内登记待清目录与最小重试状态；不新增任务表 |

**删除单题不会提前删除整页。** 来源整页及旋转副本保持原 24 小时期限，在此期间仍可能包含已删除题目的像素，且仍供本人重新裁剪。同页其他已经建立的独立题目不受影响。

到期或删除立即停止新的私有访问；物理文件由清理任务重试删除。整页到期只留非图像元数据。提交满 30 天后，已关联记录保留公共规范题面且课程变为 `expired`；未关联记录整条删除。私有课程随原始转录及产物一起到期，第一期不从公共题面重新生成课程。

后台完成和删除锁定同一提交行；清理同时检查任务生命周期锁和读取锁，避免任务或事件读取重建已清目录。进程启动将无人持锁的非终态任务标为 `interrupted`，不自动重发模型请求。启动及之后每分钟执行清理，并扫描新命名空间中的孤立文件；旧匿名拍题目录保留，不入库、不再开放直链，也不在新清理范围内。

## 3. 本地运行与维护

日常实例仍使用 8779。已有实例升级前先停止网站及其他连接该实例的服务，然后在仓库根目录运行已有部署流程（本地备份、迁移与自检）：

```bash
./deploy/product/manage.sh --mode local deploy
uv run --project server python server/tools/run_site.py
```

迁移版本应为 `0013_student_search` 或更新版本。模型调用仍需显式启用，并使用既有本地 OCR 和 provider 配置：

```bash
RUN_LLM_INTEGRATION=1 uv run --project server python server/tools/run_site.py
```

不开启真实模型时，登录、历史和维护可独立测试；点击新题生成会返回阶段一未启用。上述命令不会部署线上服务。

按需手工清理：

```bash
uv run --project server python -m shuxueshuo_server.search.maintenance cleanup
```

运营停用公共题目（使用公共题目 UUID，不使用私有 search_id）：

```bash
uv run --project server python -m shuxueshuo_server.search.maintenance disable <problem_id>
```

停用后停止新关联和私有课程访问，历史显示下线提示；不通过该命令修改题目正文。隔离实例的维护命令在子命令之前指定 `--data-dir` 与 `--instance`。

## 4. 自动化验证与边界

测试必须使用独立 PostgreSQL 实例；不得使用日常或线上数据库。一次性创建示例：

```bash
./deploy/product/manage.sh --mode local \
  --data-dir /private/tmp/sss-search-stage1 --instance search-stage1 --port 55443 install
```

已有实例按相同参数执行 `db-start`，有新迁移时执行 `deploy`。在 `server/` 目录运行：

```bash
PRODUCT_TEST_DATA_DIR=/private/tmp/sss-search-stage1 \
PRODUCT_TEST_INSTANCE=search-stage1 \
uv run pytest tests/search/test_identity.py tests/search/test_repository.py tests/search/test_private_api.py -q
```

完整拍题与登录回归：

```bash
PRODUCT_TEST_DATA_DIR=/private/tmp/sss-search-stage1 \
PRODUCT_TEST_INSTANCE=search-stage1 RUN_LLM_INTEGRATION=0 \
uv run pytest tests/search tests/auth -q -rs
.venv-ocr/bin/python -m unittest discover -s tests/search -p test_ocr_orientation_worker.py
```

数据库存储及私有 API 用例在该实例内建立临时 schema，执行完整四表 DDL、外键、唯一约束与应用角色权限；认证仍复用该隔离实例的站点用户。每例结束移除临时 schema，避免未来时钟的到期测试改变其他用例的数据。数据库未配置导致的跳过不能作为通过；存储测试缺少配置时直接失败。

覆盖场景包括身份不误合并、两账号并发归并、请求重试、跨账号访问、Origin、WS 退出/删除/到期/停用、历史入口、提交删除和后台完成交错、历史分页与后台关联/删除交错、24 小时与 30 天期限、旋转不续期、清理失败重试、工作/读取锁和重启中断。上传测试同时验证超过登录接口 4 KiB 的图片可用，以及流式 20 MiB 上限；课程完成但没有已验证教学路线时不会误报可学习。

前端在仓库根目录执行以下回归，**299 passed**；导航同步检查通过，知识图谱生成检查 `changed: 0`。

```bash
node --test tools/tests/graph-walk-*.test.mjs tools/tests/search-*.test.mjs tools/tests/site-header.test.mjs
node tools/sync-site-header.mjs --check
node tools/build-public-knowledge-graph.mjs --check
```

目前新公共身份契约使用离线题目样例和模拟/录制结果验证。此说明不声称已经完成新契约的真实 LLM 端到端调用，也不把真实 PostgreSQL 测试等同于真实 OCR/provider 质量验收。

公共课程包、跨设备作答同步和账号注销仍属后续范围；备份恢复的删除重放已实现，见[恢复契约](search-backup-restore-local-acceptance.md)。后续已完成生产入口、清理生命周期及 OCR/代理/WebSocket 的单机接入，见[单机生产接入与离线镜像演练](search-single-host-production.md)；尚未部署线上，历史验收数字不据此改写。
