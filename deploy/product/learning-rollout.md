# 学习内容正式替换

本工具包只准备发布能力。执行服务器操作前核对目标实例、维护窗口和回滚包；本地开发与演练不能证明服务器当前数据库版本。
首次替换只允许删除旧公共内容，**任何旧个人学习记录都令操作停止**。该命令不删除用户、登录或业务数据，也不提供服务器清理记录的选项。

## 同提交发布包

先运行 `node tools/build-public-knowledge-graph.mjs`，审阅并提交所有产物，再执行 `build-release.sh`。
构建器要求干净工作树，并从同一 `git archive` 构建管理/API 镜像、复制脚本。发布包**不含静态站**：
主站由 Nginx 直接读取服务器仓库 `site/`，用 `git pull` 更新。构建仍运行图谱生成器 `--check`，
并核对该提交 `site/knowledge/teaching/version.json` 与结构化导出的内容版本一致。

包中 `release.env` 记录 source revision、Alembic revision、content version、schema version、固定镜像内容 ID；
`manifest.json` 校验脚本、`release.env` 和镜像哈希。
镜像清单同时保存归档验证过的 Config 与 OCI manifest 内容 ID；目标引擎选择其可运行的固定 ID，不用可变 tag 部署。归档解析校验两种 ID 的内容对应关系和平台，兼容 classic dockerd 与 containerd 镜像存储。
校验和不替代可信分发渠道。服务端小题答案只在镜像内，不进入仓库 `site/`。

## 只读预检

使用目标包的脚本，数据目录和实例名始终显式指定。若目标镜像尚未载入，先准备包：

```bash
RELEASE=/absolute/path/release
"$RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo --release "$RELEASE" prepare-release
"$RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo --release "$RELEASE" preflight-learning
```

`prepare-release` 校验归档并载入缺少的镜像，不创建实例配置、不启动数据库或应用。
`preflight-learning` 使用现有容器网络、只读配置挂载和只读数据库事务，不创建管理锁、不初始化配置、不启动服务、不载入镜像。
连接失败直接报告失败，不把无法查询当成空库。

| state | 含义 | 后续操作 |
| --- | --- | --- |
| `empty` | 尚未安装，或已知迁移链上没有旧学习内容与记录；`0009` 之前只有整题学习标记时也属此类，输出 `kept` 计数，迁移 `0008` 原地改为新题号并保留 | 新实例 `install`；已安装实例普通 `deploy` |
| `legacy_public_only` | `0010` 下只有旧公共内容，全部旧个人学习表为空 | 明确使用 `deploy --replace-legacy-public` |
| `current` | 已有第二版公共内容结构 | 普通 `deploy` |
| `blocked` | 旧个人记录存在、未知迁移版本或不支持的内容结构 | 停止，另行设计保留历史的迁移，不能使用本地清理命令绕过 |

预检只返回版本、数量和状态，不返回用户身份、题目答案或凭据。`student_learning_marks` 即使属于其他旧题，也会阻止首次公共内容替换；工具不会猜测哪些旧记录可以删除。

## 维护窗口与首次替换

1. 保留当前完整发布包和数据库配置路径，记下服务器仓库当前提交（`cd "$HOME/code/shuxueshuo" && git rev-parse HEAD`），用于回退页面。

停服务或改库前先获取目标提交，检查仓库干净且能快进到该提交。检查只读，不更新网页；仓库已领先、分叉或有本地改动时停止，不自动回退：

```bash
set -euo pipefail
REV=$(sed -n 's/^PRODUCT_SOURCE_REVISION=//p' "$RELEASE/release.env")
SITE_REPO=${PRODUCT_REPO_HOST:-"$HOME/code/shuxueshuo"}
(cd "$SITE_REPO" && git fetch)   # 服务器 git 1.8 不支持 -C
bash "$RELEASE/scripts/server/check-site-revision.sh" \
  --repo "$SITE_REPO" --revision "$REV" --allow-forward
```

2. 停止接收新任务，等待任务完成，使用当前包的 `services-stop` 停止所有受管应用连接。停止其他连接该库的 API、清理和管理进程；PostgreSQL 保持运行。
3. 预检为 `legacy_public_only` 时执行：

```bash
"$RELEASE/scripts/server/deploy.sh" --data-dir /srv/shuxueshuo --release "$RELEASE" --replace-legacy-public
```

`current` 或已安装的 `empty` 状态去掉最后的参数。普通迁移仍保留 `0011` 的旧数据保护，普通发布不会自行删除旧图谱。

停写后备份，再次核对数据状态。
删除旧公共表数据、Alembic 升级、新内容导入在一个 PostgreSQL 事务内完成。导入失败会一起回滚 DDL 和数据。
提交后执行 doctor；`deploy` 不修改仓库 `site/`。成功结束时数据库账号已恢复 LOGIN，应用服务仍保持停止；仓库更新及严格校验完成后再启动应用。`services-start` 不负责恢复数据库账号登录权限。

部署失败时先核对事务是否提交、实际 schema/content version 和 app 登录状态，再按下表处理；不能仅凭命令退出码选择恢复包。

| 失败阶段 | 数据库状态 | 恢复方式 |
| --- | --- | --- |
| 预检失败，尚未停写 | 原数据库和登录状态未被此次部署改变 | 修正问题后重新预检；无需为此次失败执行 `resume` |
| 已停写，但数据库事务尚未提交 | DDL 和导入数据回滚，仍是旧库；app 保持 NOLOGIN | 仓库**不要** `git pull`；用**旧发布包**执行 `resume`，再启动旧包应用 |
| 数据库事务已提交，doctor 失败 | 数据库保留新版本；app 保持 NOLOGIN | 排除失败原因后，用**目标发布包**执行 `resume`，再按第 4 步继续；不能用旧包 `resume` |

提交前失败的恢复命令如下。`OLD_RELEASE` 必须是部署前保留、与旧数据库匹配的完整包，脚本本身和 `--release` 都使用旧包：

```bash
set -euo pipefail
OLD_RELEASE=/absolute/path/previous-release
"$OLD_RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo --release "$OLD_RELEASE" resume
"$OLD_RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo --release "$OLD_RELEASE" services-start
```

旧 `0010` 包的 `resume` 按旧 schema 执行 doctor。新管理器要求新 schema，不能用于恢复仍为 `0010` 的旧库。

提交后失败不要手动开放登录。目标包 `resume` 先核对数据库内容与目标包完全一致（不会再次迁移或导入），再执行 doctor 并开放登录：

```bash
"$RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo --release "$RELEASE" resume
```

需要跨版本回退时按下节恢复到独立实例。

4. **`deploy` 成功后（新装库为 `install`），把服务器仓库前进到发布包的同一提交，再严格校验。** 该提交须已 push。主站 Nginx root 一直是仓库 `site/`，无需修改 Nginx 配置。

```bash
set -euo pipefail
(cd "$SITE_REPO" && git merge --ff-only "$REV")
"$RELEASE/scripts/manage.sh" --mode server --data-dir /srv/shuxueshuo --release "$RELEASE" verify-release
```

显式执行 `verify-release` 时先检查仓库干净且 `HEAD == PRODUCT_SOURCE_REVISION`；`merge --ff-only` 自身不能保证这个条件（服务器领先于目标时也可能成功）。随后核对「镜像原稿 = 学习库 = 仓库 `site/knowledge/teaching/version.json`」的 content/schema version，
三者一致时输出 `"site": "match"`；仓库版本文件缺失或不一致时报 `release.site_content_missing` / `release.site_content_mismatch`。
`run.sh` 把仓库 `site/knowledge/teaching/` 只读挂载给管理容器，仓库路径由 `PRODUCT_REPO_HOST` 决定（默认 `$HOME/code/shuxueshuo`）。

5. 用目标包 `services-start` 启动应用，再执行 `services-doctor`。启动前核对镜像原稿与数据库内容版本，不一致直接停止；仓库 `site/` 不一致只在输出中报告 `site`，不阻止无人值守启动，因此第 4 步的严格校验不能省略。
6. 检查 `/knowledge/teaching/version.json` 与 `/api/learning/content` 版本一致，手动走一次登录、整题记录、小题和节点状态。保留一页旧标签：无关内容更新后应仍可保存；本题作答契约或本节点题池变化时，过期的新建请求应被拒绝。

## 静态资源与缓存

`git pull` 直接替换仓库 `site/`。页面引用的脚本、样式都是固定地址（知识图谱用 `/assets/knowledge-next/`，题页用 `/assets/practice/`），不带版本号；已打开的旧页面在 `git pull` 后懒加载到的是新模块，出现异常刷新即可。
整体发布版本集中于 `teaching/version.json`，不复制到每份静态文件。练习按本题 `practice_version` 校验，五题检测按本节点 `drill_version` 校验，个人图谱状态与目录进度读取实时 API；无关发布不停止学习记录。仅页面、样式或图片变化（教学内容版本不变）直接 `git pull`，不需要发布包。

主站 Nginx 与本地网站对全部静态文件设置 `Cache-Control: no-cache`，浏览器每次凭 ETag / Last-Modified 协商，未变化时得到 304。因此改共享脚本或样式只改它本身，不需要改引用它的页面。API 保留自身的缓存策略。Nginx 配置变化时复制到 `/etc/nginx/conf.d/` 后 `nginx -t` 并 reload。

共享教学流程变化后，应先在配置好独立测试数据库的环境重建 `build-graph-walk-topic.mjs`，再运行 `build-public-knowledge-graph.mjs` 和 `build-topic-overviews.mjs`，提交生成产物。只重建知识索引不能更新课程的教学证据；发布检查会拒绝陈旧证据。

课包重新验证产生的运行编号、选项排列，以及说明文字或辅助图的增减标记，不应改变原题的步骤编号和练习兼容版本。构建器先核对题目、步骤、作答规则和图形条件，再沿用原有公开编号，同时保留本次验证的真实运行证据。真正改变条件、选项含义、答案或步骤时，构建器会要求新的课程 ID；不能删除旧课包来绕过检查，也不能用手工统一修改 JSON version 的方式解决。发布后仍须完成上述 `verify-release`，保证站点、应用和学习库来自同一次发布。

`/knowledge-next/` 的服务器重定向保留查询参数，不依赖 JavaScript。生成的跳转页另有 `noscript` 下的 `meta refresh`；正常启用 JavaScript 时继续保留查询参数、锚点及图谱上下文。纯静态托管或直接访问旧节点别名页且禁用 JavaScript 时，HTML 只能跳到预设目标（含预设条目），不能动态转发任意当前查询参数。

`publish-learning` 在服务器仅允许当前版本的幂等重发，版本升级统一走 `deploy`。

## 备份和回滚

自动备份包含数据库 dump、登记产物、行数、schema revision、SHA256 和旧发布包路径。
它不复制旧镜像包或 Nginx 配置，因此必须保留这些原件；页面由仓库提交历史保留。

旧 `0010` 数据备份必须用**对应旧版本管理包**恢复，不能用新管理器伪称通过新 schema 的 doctor。
恢复始终使用新实例、新数据目录和独立端口；绝不覆盖原库。校验备份 SHA256、行数、身份数据和旧内容后，再决定切换流量。
新版本的备份可用同版本 `restore` 恢复，仓库 `site/` 保持在对应提交。

跨 schema 回滚不是只回退仓库：先停写，恢复旧数据库到独立实例，使用旧 API/管理包，仓库回到旧提交，验证后一起切换。
失败实例和备份保留用于排查。本地 `rebuild-learning` 仍只在本机原生环境可用，服务器与容器都拒绝该清理入口。
