# P1 实现与验收记录

日期：2026-09-11。结论：**P1 代码已落地，本地原生 PostgreSQL 验收通过；服务器 Docker 完整验收未完成，P1 暂不标记全部完成。**

## 已实现

- 27 张 SQLAlchemy Core 产品表、初始 Alembic revision `0001_product`、跨空间/同题复合外键、不可变历史触发器和分角色权限。
- 默认 user/workspace/member 的幂等初始化；没有历史导入器，没有搬迁或修改旧 Review 数据。
- 文件 SHA256 匹配、批次复用、正式题意校验和 promotion、修订 CAS。
- 版本化 pipeline、构建冻结、请求幂等、execution/epoch/lease、阶段与调用审计、页面包及当前版本指针、事件和 outbox 事务接口。
- 不覆盖的原子文件存储、授权页面资源查找和孤立文件报告；无静态目录公开入口。
- 本地原生安装/启停、自检、备份恢复；服务器 Compose、固定镜像发布包、安装和部署脚本。

源码入口：`server/shuxueshuo_server/product/`；管理入口见[运行手册](../deploy/product/README.md)，P2 接口见[接口说明](product-p1-interfaces.md)。

## 已执行的验证

| 验证 | 实际结果 |
| --- | --- |
| 原生 PostgreSQL | macOS Apple Silicon，Homebrew PostgreSQL 17.10；SQLAlchemy 2.0.52、psycopg 3.3.5、Alembic 1.19.2 |
| 空库安装 | 专用 `/private/tmp/shuxueshuo-p1 acceptance-final`，端口 55438；初始 doctor 报告 artifact 为 0、无孤立文件；只初始化三条业务种子 |
| 产品事务与旧 Review 回归 | **107 passed**，55.01 秒；包含现有 Review 服务、修订、依赖、重建及人工题意修订回归，无付费模型调用 |
| 管理与交付布局测试 | **4 passed**；配置/密码重复安装保持、未安装 status 不写配置、发布包独立目录中的管理入口分发、Bash 语法 |
| Alembic 模型差异 | `alembic.command.check`：No new upgrade operations detected |
| 实际备份 | 专用验收库生成 `backups/924cde9838e24563ae36d18af9f3b8ff`；该快照包含 **70 个已登记产物** |
| 实际恢复 | 新目录 `/private/tmp/shuxueshuo-p1 restored`、新实例 `p1-restored`、端口 55439；行数、迁移版本、角色权限和 70 个文件哈希全部通过 |
| 恢复后重复安装 | install + seed + doctor 成功，保留恢复后的业务记录和 70 个产物 |
| 维护窗口管理逻辑 | 在原生恢复测试实例执行 deploy 成功：暂停 app 登录、备份、重复迁移、维护模式 doctor、恢复登录；新备份为 `e017cc2bbd1f40fca72b5e6b26cd80ee`。此项不替代 Docker 部署验收 |
| Compose 静态检查 | `docker compose ... config --quiet` 通过；使用非秘密示例值，不启动容器 |
| Python/Bash/差异检查 | compileall、Bash 语法及 `git diff --check` 通过 |

测试命令（从 server 目录执行）：

```bash
PRODUCT_TEST_DATA_DIR='/private/tmp/shuxueshuo-p1 acceptance-final' uv run pytest \
  tests/product tests/test_review_service.py tests/test_review_versions.py \
  tests/test_review_rebuild.py tests/test_review_dependencies.py \
  tests/solver/test_review_human_revision.py -q --tb=short
uv run pytest tests/product/test_admin.py -q --tb=short
```

107 项回归在添加独立的 4 项管理测试前执行，两组共 111 项通过。
测试会追加独立用户/空间和离线持久化 fixture；故障注入产生的未登记文件只报告，不自动清理。
这些 fixture 验证数据库和存储合同，不声明执行了真实识别、求解或教学生成。

本次创建的三个原生测试实例（端口 55437、55438、55439）均已通过 `db-stop` 停止，数据和备份保留在上述临时目录；没有停止或接管其他数据库实例。

回归发现旧 Review 资源扫描把新增 product 模块列为未知数学依赖；现已明确标记为独立基础设施，
并增加测试验证修改 product 代码不会改变现有 Review 数学阶段的依赖快照。领域算法及旧数据库访问逻辑未替换。

## 服务层审查修复后的回归

针对两个 P1 和四个 P2 finding 完成修复：

- executed 阶段、调用审计的产物必须属于本 build 的具体 attempt；跨构建只通过已接受阶段的显式复用，最终页面再次验证来源链。
- `resolved_revision_id` 在提交时为空；提取完成后绑定新版本或语义相同的原版本。跳过提取时使用显式 `bind_requested_revision`；绑定仍为一次性且检查执行权。
- 省略 commit 的 attempt_id 只允许结束已有唯一 running attempt，不隐式插入第二条成功记录。
- 失败、中断、租约换代和预算耗尽均同步关闭相关阶段状态，保留成功阶段。
- 复用验证完整输出映射并填写 `reused_from_artifact_id`；调用引用继续标记 reused，不重复计费记录。
- 发布前拒绝有修改或未跟踪文件的工作树，镜像源码与交付脚本均来自清单所指提交的 `git archive`。

使用上述专用 PostgreSQL 验收实例执行完整产品与 Review 回归：**134 passed in 63.54s**，无跳过、无付费模型调用。
命令仍为上文包含 `tests/product` 和五组 Review 测试的完整命令；这次已一并包含全部管理测试及新增归属/状态回归。
正向场景包含跨构建复用完整页面、复用来源链和并发绑定；反向场景包含同用户跨题/跨构建及跨 attempt 的产物冒用、
过期 execution、复用输出替换、无变化修订绕过执行权和脏发布目录。发布测试模拟 Docker 命令，但实际运行 Git 归档、打包和校验和逻辑；不算 Docker 镜像验收。

本次未修改模型或基础 migration，不改写已有冻结记录、正式本地业务库或旧 Review 数据。原有缺失 producer_attempt/复用证据的记录不能继续复用或重新发布，不自动补造证据。
`clean_config()` 白名单配置投影仍列为 P2 接线待办；服务器验收仍按下节安排。

## 尚未执行及关闭 P1 的条件

2026-09-11 用户调整实施顺序：先跑通本地系统，再部署服务器。正式本地实例已初始化并启动，本地 P2 可以开始；以下服务器验收作为部署阶段的待办保留，不阻塞本地开发，不记为已通过。

服务器镜像构建请求被拒绝，因此没有构建/运行 P1 admin 镜像，没有执行 Linux 容器安装、部署或容器内备份恢复。
不能把 Compose 静态校验和本地 PostgreSQL 结果视为服务器验收通过，也没有部署到现有服务器。

允许执行镜像构建后，仍须完成：

1. 按运行手册分别生成 linux/arm64 和 linux/amd64 发布包，验证镜像架构、内容 ID、离线包与脚本清单。
2. 在隔离 Linux Docker 实例执行空库安装、重复安装、doctor，核对种子和卷/目录绑定。
3. 执行新版本 admin 部署，验证备份、迁移锁、维护窗口及失败后的受控 resume。
4. 在新卷、新数据目录恢复备份，比较数据库行数和全部登记产物哈希。

全部通过后再把路线图与在线开发计划中的 P1 状态改为完成。P2 的 HTTP/WebSocket、RabbitMQ/Celery、
Worker、真实上传和页面路由仍按原计划接线；领域适配器继续负责数学 checkpoint 恢复和 typed 合同校验。
