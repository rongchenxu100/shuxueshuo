# 本地实例升级记录

2026-09-17。用户明确要求本地数据不备份，执行迁移并重启整套应用服务。目标仅为本机 `local` 实例，未操作远程生产环境，也未调用模型。

## 执行与检查

从仓库根目录依次执行，均成功：

```bash
./deploy/product/manage.sh --mode local services-stop
./deploy/product/manage.sh --mode local migrate
./deploy/product/manage.sh --mode local services-start
./deploy/product/manage.sh --mode local services-doctor
```

- 数据库从 `0002_product_runtime_indexes` 升级至 `0003_problem_understanding`；应用权限检查通过。
- 前端、API、Worker、Publisher 已换成当前版本，RabbitMQ 正常；PostgreSQL 在应用停机期间保持运行。
- 该次升级部署指纹：`02379a620d2c26de737fe3a4520416069c2d136f7edb7b376d578003a233435f`。
- Worker、Publisher 心跳正常，待发布消息及过期租约均为 0。
- 908 个已登记产物完整性检查通过，无孤立文件。
- 题目 `a33ef03c-09fa-44b4-8fed-05af0dd5b2d3` 的 `understanding`、`candidates`、`extraction-runs` 查询均返回 HTTP 200。
- 浏览器实测题意页面显示原图入口、提取操作、候选历史、JSON 修订及原有完整生成记录；不再显示接口 404 对应的“请求未完成”。
- 此题尚未发起新的题意抽取，因此新候选与运行列表为空，这是预期状态。旧正式题意及页面指针保留。

## 启停兼容修复

升级前发现 `services-stop` 初始化新版 `Application`，会因旧数据库尚未迁移而拒绝停机。改为直接连接数据库查询既有 `jobs` 表完成排空检查，不加载需要新版表结构的应用；有活动任务时仍等待，超时仍保留服务与任务。

新增回归覆盖无活动任务、任务排空后停机、排空超时不终止服务。相关离线验证：

```bash
cd server
uv run pytest -q tests/product/test_runtime_lifecycle.py tests/product/test_runtime_config_broker.py
```

结果：16 passed；迁移前使用真实本地旧数据库执行正常停机也已成功。

## 工作台列表更新

同日 13:33 完成工作台列表更新并重启本地应用服务。本次没有新增数据库迁移或模型调用。

- 列表接口读取当前来源、候选、运行及复核状态，返回统一展示信息；旧正式题意与页面指针保持独立。
- 有候选时显示数学题意摘要；尚无文字内容时显示原图缩略图与“待提取题目”，不再使用文件名充当题目。
- 已复核的未匹配题显示“题意已提取 · 暂不支持题型”；缺图优先显示“待确认题目 · 缺少配图”；已生成旧解析页显示“解析已生成”。
- 运行结束更新题目时间并发布事件；工作台保持轮询，并在重新获得焦点或可见时刷新。
- 浏览器实测函数量词题 `3d5f8255-ef7f-48cb-8a04-7baca90982a2` 已显示 `f(x)`、`g(x)` 及条件摘要和“题意已提取 · 暂不支持题型”。
- 中间栏涉及新旧工作流切换，按用户要求暂缓；后续统一路径后展示整体步骤、停留位置、原因和下一操作。

验证：真实 PostgreSQL 相关回归 60 项通过（含七题录制保存与查询），前端 44 项通过，类型检查、相关 ESLint 和生产构建通过。七题保存验收不代表七题数学语义全部通过。

本次部署指纹：`2f6281d116a30164ef6c3798f0800857b13731fbf1430ae042f565d77e760043`。`services-doctor` 返回正常：前端、API、Worker、Publisher 版本一致且运行中，数据库版本 `0003_problem_understanding`，965 个产物完整，待发布消息和过期租约均为 0，心跳与 RabbitMQ 正常。
