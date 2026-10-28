# 公共知识图谱：维护与发布

公共原稿、教学导出和学习数据库按内容版本校验。本文描述当前操作，不维护阶段计数或历史发布包。

## 1. 正式入口与维护

| 地址 | 用途 |
| --- | --- |
| `/knowledge/` | 高中知识图谱总览 |
| `/knowledge/chapters/compulsory-1-ch2/` | 第二章二维图及节点目录 |
| `/knowledge/3d/` | 三维图 |
| `/knowledge/<节点ID>/` | 正文、关联、个人状态与证据 |
| `/knowledge/nodes/` | 八类节点文字目录 |
| `/1/`、`/2/`、`/topics/` | 原有专题编排，使用新关联 |
| `/knowledge-next/…` | 仅兼容跳转，没有另一套正文 |

公共原稿仍维护于 `site/data/knowledge-next/`，小题私有原稿仍维护于 `server/shuxueshuo_server/learning/drills-next/`。不改节点、内部条目、题目、路线或步骤身份。

```bash
node tools/build-public-knowledge-graph.mjs
node tools/build-public-knowledge-graph.mjs --check
./deploy/product/manage.sh --mode local check-learning
./deploy/product/manage.sh --mode local publish-learning
```

生成器用各输出目录的 `manifest.json` 管理自己的文件，未登记文件不删除。首次替换旧目录只处理 `tools/data/public-knowledge-legacy-files.json` 登记且哈希未变的文件；遇到改动或冲突停止。旧节点别名按迁移表跳转，`case-merge` 保留多个去向的说明页。兼容跳转保留条目、搜索、筛选和图谱返回上下文。

旧公共数据和旧小题已移入 `server/tests/fixtures/learning-legacy/`，仅供一次性迁移核对；旧图谱加载器及旧生成命令退役。显式资源目录引用的旧图解模块、样式与共享辅助代码继续保留。其他独立题的提示兼容 API 也读取新公共正文。

## 2. 学习与预览模式

| 模式 | 行为 |
| --- | --- |
| 发布清单中的普通题页 | 默认新关联；匿名静态作答，登录后按版本启用记录及恢复 |
| `?preview=1` | 无记录预览；不初始化记录器、学习标记、导师或小题检测 |
| `?knowledge=next` | 兼容无记录预览 |
| `?knowledge=next&learning=1` | 兼容正式学习 |
| 同时存在 `preview=1` | 预览优先 |
| 未在发布清单中的题页 | 保持独立作答和导师，不因使用共享 runtime 而自动入库 |

统一模式解析位于 `site/assets/practice/learning-mode.mjs`。专题、题页、详情和图谱间保留预览；显式退出预览的链接恢复正式模式。公开清单同时核对题目 ID 与页面路径。

记录版本检查失败时显示重试，静态作答和独立导师仍可使用。已有本地作答或独立导师对话不能在版本迟到后被补录成正式记录。只有服务端确认通过的实际选择用于分支归因；导师判过但未确认选择时只显示候选。Q30 未答和草稿选择均不泄漏正确选项。

## 3. 个人图谱

二维图、三维图、目录与详情共用 `personal-state.mjs`，每页复用一次 `/api/learning/nodes` 请求。默认登录即开启，开关按账号保存于当前浏览器；缓存只保存开关，不持久化个人评估或证据。

- 知识点、技能、方法、题型：徽标区分已掌握、待巩固、未检测（内部状态 `unassessed`），保留原节点类型颜色。
- 教材、章、节：包含与拓展分别去重汇总；尚未录入章节不显示未评估。二维图的详细计数默认折叠，保留图谱主体的浏览空间。
- 判断规则：只展示实际判断证据，不显示掌握状态或概率。

新增鉴权接口 `GET /api/learning/progress/batch?scope=<目录ID>&scope=<目录ID>`，返回 `{content_version, progress:[…]}`；保留单目录接口。每份 HTML 固化 `knowledge-content-version`，节点状态及目录结果与这份页面的版本比较，不使用最新静态版本文件替旧页面放行。加载失败显示暂不可用并允许重试；不会用未评估代替失败。

退出和换账号时清空当前个人数据并使旧请求失效。五题检测完成通过页面事件与跨标签页通知刷新状态。仍使用 `drill_round_v1`：仅完成五题检测后更新对应节点，首答 5/5 为已掌握，否则为待巩固；整题过程、关联节点与目录均不传播掌握状态。

## 发布

部署流程以[产品部署手册](../deploy/product/README.md)和[学习内容发布手册](../deploy/product/learning-rollout.md)为准。发布包不包含静态站；服务器仓库维护 `site/`。完整发布核对仓库提交、镜像原稿、学习库和静态教学版本，不能混用不同版本。

本地内容变更依次构建、检查和发布学习内容；服务器升级使用目标发布包和匹配的仓库提交。数据库备份与恢复由管理脚本完成，不手工覆盖内容版本或删除既有学习记录。运行历史、账号和个人证据不随公共内容重建清空。

## 验证入口

```bash
node tools/build-public-knowledge-graph.mjs --check
node --test tools/tests/public-knowledge-*.test.mjs tools/tests/learning-*.test.mjs
```

页面验证覆盖正式/预览隔离、匿名和登录、旧链接、账号切换、检测完成后的状态刷新，以及手机公式和图解。测试环境、真实模型和生产部署分别报告。
