# 个人知识图谱数据设计

更新：2026-10-08。数据保存、身份、关联、首期记录及节点小题的固定达标规则已确定；仅第 7 章的综合学习效果评估策略保留讨论。实现与验收见[六阶段实现记录](student-knowledge-graph-implementation.md)。线上发布需按该文档执行，开发验收不等于已上线。

复用现有 PostgreSQL 与用户登录。公共内容由文件编写、发布时导入数据库，数据库不独立编辑；学生记录由服务端保存。个人图谱在公共节点上叠加学生状态，不为每个学生复制节点或连线。

相关文档：[知识图谱页面设计](public-knowledge-graph-ontology-design.md)、[知识点与方法清单](public-knowledge-graph-ontology-design.md)、[登录与学习标记](site-login-and-learning-marks-plan.md)。数据保存与记录范围以本文为准。

## 1. 数据保存分工

| 内容 | 维护来源 | 数据库与页面分工 |
| --- | --- | --- |
| 知识点、方法节点及关系 | `site/data/knowledge/graph.json` | 发布时导入节点、前置依赖与使用关系；页面可读取同版 JSON |
| 节点简介、图解引用 | `site/data/knowledge/display.json` | `summary / sheet` 随节点入库 |
| 节点详细说明 | 节点图解 JS 的可读正文 | 定义、公式、适用条件及必要解释以 Markdown／LaTeX 入库，供查询与 LLM 使用 |
| 图解、详情页、样式 | 节点 JS、HTML、CSS 与资源文件 | 文件发布；数据库保存引用，讲解文字复用说明原稿 |
| 专题基本信息 | `site/data/knowledge/topics/<topic>.json` | `id / label / path` 导入专题表 |
| 专题图谱范围、方法栏编排 | 专题 JSON 的 `nodes / sequence` | 保留 JSON，不另建展示编排表；展示范围不直接作为练习证据 |
| 题型目录、题目卡片与排序 | 当前目录 HTML | 保留现状，不入库；统一原稿与自动生成目录不作为首期前提 |
| 原题与题目身份 | 现有题页、教师 JSON 中的可信原稿 | 完整题干、已有结构化条件与目标、必要资源引用随题目入库 |
| 完整教学流程 | 题页 `practice-config`、教师 JSON、模板与组件 | 保留文件，继续校验重复配置一致；不整体导入公共内容表 |
| 步骤身份、标题与顺序 | 题页 `practice-config` 的路线步骤数组 | 导入 `practice_steps`；教师 JSON 校验一致，专题 JSON 只提供步骤—节点关联 |
| 专题—题目、题目—方法、步骤—节点关联 | 专题 JSON 的题目与路线映射 | 发布时导入关系表，不独立编辑；`examples` 暂不单建表 |
| 节点小题库 | `server/shuxueshuo_server/learning/drills/*.json` | 题干、选项、标准答案、解析入库，直接关联节点 |
| 整题练习记录 | 学生实际操作与对话 | 保存必要上下文和原始事件，并生成步骤汇总 |
| 节点小题练习 | 点击刷题创建一轮 5 题的 attempt，服务端规则判定 | 保存固定题目清单、首答选项 ID、正误与时间；同轮 5 题首答全对才达标 |
| 自评、练习标记 | 现有学习标记功能 | 保留现有表，与系统评估区分 |
| 节点掌握状态 | 小题按固定规则；综合评估使用学习记录 | 首期从最近完成的小题 attempt 推导达标状态，见第 5.5 节；后续综合评估见第 7 章 |
| 缩放、展开等界面偏好 | 浏览器本地 | 不入库、不作为学习证据 |

节点图解继续使用 `site/assets/explain/knowledge/<id>.js` 或 `method/<id>.js`，详情页使用 `site/knowledge/<id>/index.html`。首期由发布工具渲染节点图解 JS，提取可读正文与 LaTeX 入库，过滤 SVG 与脚本；不另手工维护一份正文。原题入库不要求题页改为动态渲染；图片等二进制资源仍由文件保存，并提供持久引用。

公共内容描述题目与知识本身；整题练习快照记录学生当时看到的内容。快照不随公共文件更新，同次练习内的重复内容通过引用复用。

## 2. 身份与发布规则

- **节点 ID 全局唯一，发布后不得修改或复用。** 顶层只有知识点与方法，表达式变形方法属于方法子类；跨专题复用同一节点。
- 公共关系只包含知识点之间的前置依赖 `prerequisite`、方法指向知识点的使用关系 `uses`。方法组合和先后顺序由题目路线表达。
- 题目 ID 表示固定教学身份，统一格式及现有短 ID 的一次性迁移见第 2.1、2.2 节。页面路径、题号与数组位置不作为身份；不建立题目内容版本表。
- 步骤使用 `problem_id + route_id + step_id` 定位。保留现有 ID；新增步骤 ID 使用有教学含义的小写英文与下划线，不用 `step1` 等顺序编号。`stage` 只表示当前位置。
- 节点小题使用 `(node_id, item_id)` 定位，直接关联该节点。

| 变更 | 处理 |
| --- | --- |
| 名称、措辞、排版修改，教学含义不变 | 保留 ID，同步文件与数据库；不覆盖既有练习快照 |
| 原题、答案、步骤结构、判定标准或节点映射实质变化 | 下架旧题、新增 ID；节点小题采用同一规则 |
| 节点含义变化、合并或拆分 | 保留旧身份与历史关联，明确新旧映射；不自动继承掌握结论 |
| 下架题目或节点 | 停止用于新练习，保留历史引用需要的正文、资源与关系 |
| 新增专题 | 复用已有节点，只补充专题映射；新增题目未做不代表原有能力退步 |

发布需保证 ID 与引用有效、前置依赖无环、文件配置与导入内容一致、正文及必要资源齐全。重复导入不重复建记录，不覆盖同 ID 的不同教学内容，不级联删除学生历史。题目练习中途下架时保留已提交记录，提示另开新题，不将旧提交交给新题判分。现有 `version` 仅用于前后端同步检查。

步骤发布校验按题目、路线逐一进行：专题 JSON、题页配置与教师 JSON 的路线及步骤 ID 集合必须一致，路线内步骤 ID 不得重复；题页与教师 JSON 的步骤标题及数组顺序必须一致。缺项、多项或不一致均阻止发布，不依赖专题 JSON 对象的键顺序。

### 2.1 题目永久 ID

正式 ID 统一为 `<命名空间>-<题目键>`，使用小写英文、数字与连字符，全局唯一。命名空间在首次分配时确定；题目调整目录、加入其他专题或更改展示题号，均不改变 ID。题目键只用于分配身份，不随页面排序重新编号。

| 题库 | 当前 ID | 正式 ID | 页面路径 |
| --- | --- | --- | --- |
| 基本不等式 | `q01` 至 `q30` | `basic-inequality-q01` 至 `basic-inequality-q30` | 保留 `/1/q01/` 至 `/1/q30/` |
| 二次不等式恒成立 | 如 `quadratic-always-q01` | 保持现有 ID | 保留 `/2/q01/` 等路径 |

基本不等式的调整是**同一道题的身份规范化，不是删除旧题、创建新题**，不产生新的练习证据。用一份显式映射清单逐项登记这 30 个旧 ID 与正式 ID，供迁移及兼容读取共同使用；不得对仓库里所有 `q01` 字符串做全局替换。

规范化后，正式 ID 永久不变、不复用；旧 `q01` 等 ID 永久保留为对应题目的别名，不能再分配给其他专题。数据库只保存正式 ID，不为别名建立第二道题；以后新增题目直接分配正式 ID。

### 2.2 现有引用与学生记录迁移

**迁移前现状：** 题页 `practice-config.id`、教师 JSON 的文件名与内部 `id`、专题 JSON 的题目及示例引用仍使用短 ID。`student_learning_marks` 以 `(user_id, problem_id)` 为主键；学习标记接口按教师 JSON 文件名校验题目并过滤列表，因此只改文件名会让旧记录在页面上消失。

在启用本文新的练习记录表之前，完成以下一次性迁移：

1. **统一引用。** 按映射清单同步教师 JSON 文件名及 `id`、题页配置、目录卡片、专题题目／示例关联、导师默认课程 ID 和相关测试。`route_id / step_id`、页面 URL 与展示题号保持不变；已有导入关系也使用同一映射更新。
2. **迁移学习标记。** 备份后新增数据库迁移，不修改已执行的 `0007_learning_marks`。暂停相关写入，在事务内将这 30 个旧 `problem_id` 更新为正式 ID，原样保留 `user_id / practiced / learning_status`。若同一用户在新旧 ID 下各有一条记录，预检失败并停止，不静默覆盖或合并；当前表没有更新时间，不能推断哪条自评较新。
3. **兼容旧入口。** 学习标记 API 与导师课程加载先将旧 ID 解析为正式 ID，再校验、查询或写入；响应统一返回正式 ID。前端匹配目录卡片、完成事件与学习标记时使用同一身份映射，避免重复计数或漏显；不能只改写入接口。
4. **协调发布。** 文件、接口及数据迁移一起切换，确认旧服务不会继续写入短 ID 后再恢复请求；更新静态资源缓存并提示已打开的旧页面刷新。导师会话目前仅保存在进程内，不属于此次数据库迁移；服务重启后需重新建立会话，不承诺迁移临时对话历史。
5. **验收。** 映射一一对应；迁移前后每个用户的标记数量及状态一致；正式 ID 与旧别名访问同一条记录，写入不产生短 ID 行；两专题同题号不串题。重复执行迁移不重复建记录，已经迁移的记录保持不变。

后续新表的外键只引用正式 ID。此次规范化与第 2 节的内容变化规则分开处理，不重置已有学生状态，也不为保留历史引入题目内容版本表。

## 3. 公共内容与关联表

以下表由发布工具同步。现有 `problems / problem_revisions` 属于题目生产系统，练习题库使用 `practice_` 前缀。

| 表 | 主要字段与约束 |
| --- | --- |
| `knowledge_nodes` | `id` 主键、`label / kind / subtype / summary / explanation_md / sheet / is_active` |
| `knowledge_edges` | `source_id / target_id / relation_type` 均非空；两端外键到节点，三字段组合唯一 |
| `practice_topics` | `id` 主键、`label / path` |
| `practice_problems` | `id` 主键、`label / path / lesson_file / statement_md / problem_data / is_active` |
| `practice_topic_problems` | `(topic_id, problem_id)` 联合主键与外键；不存目录分组、排序 |
| `practice_problem_methods` | `(problem_id, route_id)` 联合主键、`method_node_id`，关联全局方法节点 |
| `practice_steps` | `(problem_id, route_id, step_id)` 联合主键、`title / position`；所属路线外键，路线内位置唯一 |
| `practice_step_nodes` | `(problem_id, route_id, step_id, node_id)` 联合主键；外键到步骤和节点 |

`statement_md` 保存完整原题，`problem_data jsonb` 保存原稿已有的结构化条件、目标与必要图形／资源引用。节点与题目的正文保留 Markdown／LaTeX。

`practice_steps` 从题页 `practice-config.routes[route_id]` 的步骤数组导入：`step_id` 取步骤的 `id`，`title` 取 `title`，`position` 取从 0 开始的数组下标。教师 JSON 的 `routes[route_id].nodes` 用于校验同一套 ID、标题与顺序，不在冲突时任选一份。专题 JSON 的 `problems[problem_id].routes[route_id]` 只提供“步骤 ID → 节点列表”；没有节点关联的步骤也须显式保留空数组 `[]`，不能省略步骤。

`practice_problem_methods` 已表达路线，不再建重复路线表；其中记录主要方法，其他涉及节点通过步骤关联。首期不增加关联角色或节点内考查项。内容表外键限制删除，历史原题及关联须可查询。

发布时停用原稿中已移除的节点、题目与小题；节点状态列表只返回启用节点，停用节点不能新开练习。历史记录及其题目、步骤关联保留，同一身份重新发布可恢复启用。公共边、专题—题目关系按本次原稿完整同步；无学生历史直接引用的已移除专题删除。当前原稿不能继续引用已移除的节点或专题。

公共数据的约束与校验分工：

| 对象 | 数据库约束 | 发布导入器校验 |
| --- | --- | --- |
| 节点 | `kind NOT NULL`，`CHECK (kind IN ('knowledge', 'method'))` | 方法子类合法；已发布身份含义不变 |
| 图谱边 | `CHECK (relation_type IN ('uses', 'prerequisite'))`、`CHECK (source_id <> target_id)`，以及上述唯一约束、外键 | `uses` 只能是 `method → knowledge`；`prerequisite` 只能是 `knowledge → knowledge`，且前置依赖无环 |
| 路线方法 | `method_node_id` 外键到节点 | 被引用节点必须为 `method` |
| 步骤 | `title / position NOT NULL`、`CHECK (position >= 0)`、`UNIQUE (problem_id, route_id, position)` | 第 2 节的集合、标题及顺序一致性；每条路线的位置从 0 连续排列 |

图谱 JSON 的 `from / to / type` 分别导入边表的 `source_id / target_id / relation_type`。边的端点类型和依赖环涉及多行数据，不写成跨表 `CHECK`；导入器在同一事务内校验待发布的完整节点与边，失败整批回滚。节点类型变更时也重验已有相邻边。所有导入入口执行同一校验，不只依赖前端检查。

## 4. 整题练习记录

### 4.1 一次路线练习：`student_practice_attempts`

一行表示某学生采用某条路线练习一次题。**同一学生、同一道题最多一轮进行中，跨路线共用此限制**；不同题目可以同时练习。重复打开同题返回已有尝试，明确重新开始或切换路线时，在同一事务中关闭旧的未完成尝试并创建新 ID，不关闭已完成记录。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | `uuid` 主键 | 稳定尝试 ID，创建重试复用 |
| `user_id` | `uuid` 外键 | 登录用户 |
| `problem_id / route_id` | `text` | 联合外键到题目路线 |
| `problem_context` | `jsonb` | 当时题干、条件、目标与路线背景，一次练习只存一份 |
| `status` | `text` | `in_progress / completed / closed` |
| `started_at / updated_at` | `timestamptz` | 开始与最近更新时间 |
| `completed_at` | `timestamptz`，可空 | 全路线完成时间 |

题目背景由服务端核对同次发布的原题与练习配置后固定。只有所有必要步骤通过才能标记完成；意外离开不把未做步骤记错。

两种尝试表 `student_practice_attempts / knowledge_drill_attempts` 均使用以下数据库约束：用户、题目／节点、`status / started_at` 非空；`CHECK (status IN ('in_progress', 'completed', 'closed'))`；`CHECK ((status = 'completed') = (completed_at IS NOT NULL))`；`CHECK (completed_at IS NULL OR completed_at >= started_at)`。服务端只允许 `in_progress → completed / closed`，历史尝试不能重新变为进行中。

整题必建索引：

```sql
CREATE UNIQUE INDEX uq_student_practice_active
    ON student_practice_attempts (user_id, problem_id)
    WHERE status = 'in_progress';
CREATE INDEX ix_student_practice_history
    ON student_practice_attempts (user_id, started_at DESC);
CREATE INDEX ix_student_practice_problem_history
    ON student_practice_attempts (user_id, problem_id, started_at DESC);
```

普通创建发生唯一冲突时读取已有进行中尝试；明确重开／切换须携带预期旧 attempt ID，服务端锁定并核对后再切换，旧页面不能关闭后来创建的尝试。唯一索引承担并发兜底，不用“先查没有、再直接插入”代替。

### 4.2 原始交互：`student_practice_events`

**上下文只保存一次，每条记录只保存新增内容。** 网页、文字和语音共用一张表，保留真正发生的全部提交和对话。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | `uuid` 主键 | 事件 ID，网络重试沿用 |
| `attempt_id` | `uuid` 外键 | 所属练习 |
| `step_id` | `text` | 服务端核对属于本次题目路线 |
| `sequence` | `bigint` | 尝试内顺序，与 `attempt_id` 组合唯一 |
| `event_type` | `text` | 下列五种类型 |
| `related_event_id` | `uuid`，可空 | 所回答、判定或纠正的记录，必须属于同次练习 |
| `payload` | `jsonb` | 本条内容 |
| `created_at` | `timestamptz` | 服务端记录时间 |
| `displayed_at` | `timestamptz`，可空 | 提示或老师消息首次确认展示时间，独立于原始内容 |

| 类型 | 保存内容 |
| --- | --- |
| `context` | 步骤问题、选项 ID 与文本、必要判定依据；问题或选项改变才新建上下文 |
| `answer` | 网页选择的选项 ID 或填空输入，引用 `context`；不重复选项文本 |
| `grade` | 引用原输入，保存通过／错误／信息不足及 `rule / llm` 来源 |
| `hint` | 使用的提示内容，重复内容可引用原提示 |
| `message` | 发言方、单条文本、学生输入渠道（文字／语音转写）；老师回复与转写纠正引用原消息 |

数据库要求 `attempt_id / step_id / sequence / event_type / payload / created_at` 非空，设置 `UNIQUE (attempt_id, sequence)`、`CHECK (sequence > 0)`、`CHECK (event_type IN ('context', 'answer', 'grade', 'hint', 'message'))` 和 `CHECK (jsonb_typeof(payload) = 'object')`。`related_event_id` 外键到本表 `id`；唯一约束已提供按尝试顺序读取的索引，另建 `(attempt_id, step_id, sequence)` 索引供步骤回溯。

服务端按 `event_type` 选择固定 payload schema，校验必填字段、类型、枚举及引用：作答须对应题目选项／输入格式，判定来源和结果须合法，消息须含发言方与正文。拒绝未知字段或结构不符的数据；同时校验步骤属于本次路线、引用事件属于同次尝试且类型符合用途（如 `answer` 引用 `context`、`grade` 引用学生输入）。客户端不能写入老师消息、判分或内部判定依据；LLM 输出也须通过校验后才能落库。

- 题目背景从尝试读取，不在每条事件复制；用户、题目、路线及节点身份通过关联取得。
- 对话输入仅存为 `message`，不再复制为 `answer`；反馈文字只存老师消息，不在判定中重复。
- 同一步选项文本只存一份。学生先选 A 后选 B，保留两次选择，查询时再还原选项文本。
- 刷新、重绘、网络重试不重复记录；真正的新提交即使内容相同也保留。
- 保存语音最终转写及纠正，不存音频、中间转写、鼠标轨迹、未提交输入、页面 HTML 或完整模型请求包。
- 提示与老师消息记录展示状态，语音中断标记未完整播放；未确认提供的内容不能算作已获得帮助，展示不等于理解。
- 原始表达与上下文不覆盖；应用账号仅获 `displayed_at` 列的更新权限，不能更新 `payload`；重复展示确认保留首次时间。改判和纠正保留引用。必要判定依据由服务端保存，不提前发送给学生。

### 4.3 步骤汇总：`student_step_results`

由原始事件生成，主键为 `(attempt_id, step_id)`，用于快速查询，可重新计算。

| 字段 | 含义 |
| --- | --- |
| `passed` | 是否通过 |
| `submit_count / wrong_count` | 有效作答与错误次数，不含网络重试和普通求助 |
| `hint_used` | 通过前是否有已确认向学生展示的提示；按第 4.2 节的展示状态统计 |
| `last_grading_source / last_submitted_at` | 最近判定来源与作答时间 |
| `summary_through_sequence` | 汇总已处理到的事件位置 |
| `reasoning_summary jsonb`，可空 | 可选思路总结、来源事件、生成时间与策略标识 |

首次有效作答判定后建汇总；仅有提示或对话也应保存事件。待判定与信息不足不自动记错；计数字段非空，数据库设置 `CHECK (wrong_count >= 0 AND submit_count >= wrong_count)`。通过后的普通讨论不改写此前完成时的统计，正式重练另开尝试。

仅点击提示按钮、生成或发送了提示，但未确认展示，不将 `hint_used` 置为真。首期按服务端收到展示确认的时间判断；迟于通过的补报不反推为通过前帮助，不能把通过后才展示的提示算入通过前的帮助。

思路总结属于第 7 章的评估处理，不能替代原始记录，也不能把老师提供的推导写成学生的独立思路。

### 4.4 上报与一致性

- 开练创建尝试；首次进入步骤保存上下文；提交、提示及实际对话及时上报，不等整题完成。
- 用户只提交输入，正误由服务端判定。规则判定无需 LLM；对话先存学生消息，再调用模型，调用期间不持有长数据库事务。
- 判定、汇总更新与步骤推进在短事务内完成。最后一步通过时更新尝试和 `student_learning_marks.practiced`，不覆盖自评。
- 稳定事件 ID 去重，同 ID 不同输入拒绝；同一提交只计一次。并发或网络重试复用处理结果，先识别重试再判断步骤是否已完成。
- 模型失败保留原消息，不记为数学错误；迟到回复只关联原尝试与步骤，不能推进新尝试。
- 展示状态补齐或改判时，更新尝试时间、重算受影响汇总并标记待评估，不能只看新增事件序号。

## 5. 知识节点小题

### 5.1 小题库：`knowledge_drill_items`

小题由文件编写，发布时导入数据库，直接关联图谱节点。首期一题对应一个节点，不增加映射表。

| 字段 | 含义 |
| --- | --- |
| `node_id` | 外键到图谱节点 |
| `item_id` | 节点内稳定小题 ID，与 `node_id` 组成主键 |
| `statement_md` | 题干及必要资源引用 |
| `question_type` | 单选、多选、判断、受限填空 |
| `options jsonb` | 选项 ID、文本及原稿配置的选项反馈，非选择题可空 |
| `answer_spec jsonb` | 标准答案与明确的规则配置，仅供服务端判分 |
| `explanation_md` | 预先编写的解析 |
| `is_active` | 是否可用于新练习 |

题意、答案或所属节点实质改变时，下架旧小题并新增身份。选项 ID 不重新分配给其他含义；选项含义或反馈所指的误解实质改变时，同样新增小题身份。旧题、选项反馈及判定依据保留，历史结果关联原题，不为每条结果复制题干。

### 5.2 一轮 5 题练习：`knowledge_drill_attempts`

点击节点的“刷题”按钮，创建一次 attempt。开练时由服务端固定该节点下 5 道不重复的小题及顺序，题目清单直接保存在本轮的 5 条 `knowledge_drill_answers` 记录中，不另存一份数组；这些记录此时尚未作答。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | `uuid` 主键 | 本轮练习 ID，创建重试复用 |
| `user_id` | `uuid` 外键 | 登录用户 |
| `node_id` | `text` 外键 | 本轮练习的图谱节点 |
| `status` | `text` | `in_progress / completed / closed` |
| `started_at` | `timestamptz` | 开始时间 |
| `completed_at` | `timestamptz`，可空 | 5 题均已首次作答的时间 |

- 本轮与 5 条作答记录一起创建；可用小题不足 5 道时不启动检测，不降低达标题数。
- 中途退出可以继续原 attempt，刷新不重抽题；明确重新开始时关闭旧的未完成轮次并创建新 attempt。同一学生、同一节点只保留一轮进行中的练习。
- “已完成”表示 5 题均已作答，不要求全部正确；关闭或未完成的轮次不产生新的达标结论。

状态与完成时间的 `CHECK` 约束同第 4.1 节。小题必建索引：

```sql
CREATE UNIQUE INDEX uq_knowledge_drill_active
    ON knowledge_drill_attempts (user_id, node_id)
    WHERE status = 'in_progress';
CREATE INDEX ix_knowledge_drill_latest_completed
    ON knowledge_drill_attempts (user_id, node_id, completed_at DESC, id DESC)
    WHERE status = 'completed';
```

重复创建遇唯一冲突时返回已有轮次；明确重开时锁定并核对旧 attempt，在同一事务中关闭旧轮次、创建新轮次及 5 条作答记录。旧轮次关闭后不得再接收新答案。

### 5.3 本轮题目与首答：`knowledge_drill_answers`

每条记录属于一轮 attempt，先固定本轮题目，再保存该题的首次正式作答及结果。开练时与 attempt 一起插入 5 条记录，填写 `attempt_id / position / item_id`，`selected / is_correct / answered_at` 初始均为 `NULL`。首次作答只更新已有记录，不再插入新行；不使用整题的事件、步骤汇总或对话记录表。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `attempt_id` | `uuid` 外键 | 所属轮次 |
| `position` | `integer` | 本轮顺序 1–5，与 `attempt_id` 组成主键 |
| `item_id` | `text` | 固定的小题 ID；结合本轮 `node_id` 定位小题 |
| `selected` | `jsonb`，可空 | 首答选项 ID 数组：单选／判断如 `["A"]`，多选如 `["A", "C"]`；未提交或非选择题为空 |
| `is_correct` | `boolean`，可空 | 首次正式作答是否正确；未提交时为空 |
| `answered_at` | `timestamptz`，可空 | 服务端判分时间；与首答及正误同时写入 |

数据库设置 `item_id NOT NULL`、`UNIQUE (attempt_id, item_id)`、`CHECK (position BETWEEN 1 AND 5)`、`CHECK ((answered_at IS NULL) = (is_correct IS NULL))`、`CHECK (answered_at IS NOT NULL OR selected IS NULL)`、`CHECK (selected IS NULL OR jsonb_typeof(selected) = 'array')`。主键与唯一约束已覆盖按轮次读取，无需再建相同索引；恰好 5 条、选项 ID 合法及题目属于该节点由服务端事务校验，不能仅靠位置范围约束。

- `(attempt_id, item_id)` 唯一；创建时服务端校验每题属于本轮节点且可练习，之后不能替换题目或改变顺序。小题身份与正文须保留供历史记录引用。
- 首次正式提交由服务端判分，按 `(attempt_id, position)` 定位已有记录，以 `answered_at IS NULL` 为条件原子更新首答选项、正误与时间；记录不存在时拒绝提交，不补插题目。未提交不记错，同一首答重试返回已存结果，不同答案不能覆盖首答。
- 选择类提交须校验选项 ID 属于该小题；单选／判断保存一个 ID，多选按集合归一为稳定顺序。`selected` 只存 ID，不复制选项文本或反馈；通过小题关联还原学生选择及对应的干扰项反馈，用于后续诊断。是否已提交以 `answered_at` 判断，填空题不使用 `selected`。
- 看反馈后改对不改变首答成绩；重新刷题创建新 attempt，不把不同轮次的正确答案拼成一次通过。
- 每次首答提交先锁定所属 attempt；已有首答时，相同输入的重试直接返回已存结果，不因本轮已完成或关闭而拒绝。尚未作答时才检查本轮仍在进行中，条件写入首答并检查完成情况；最后一道未作答题的首答落库与本轮完成标记在同一短事务中处理，确认 5 题均已作答。题数、作答数和正确数可直接查询，不重复存汇总字段。
- 不记录提交前的点选、看反馈后的纠错过程或 LLM 总结；首答作为正式评测证据保留，小题结果不修改整题的练习标记或学生自评。

### 5.4 首期判分规则

**小题全部由服务端按规则判定，不调用 LLM。** 客户端提交答案，不能自行声明是否正确；反馈使用预先编写的解析。

| 题型 | 规则 |
| --- | --- |
| 单选 | 选项 ID 与正确选项 ID 一致 |
| 多选 | 所选集合与正确集合完全一致，缺选或多选均为错误 |
| 判断 | 与标准答案一致 |
| 填空 | 仅支持数值或预设可接受答案；允许的格式归一与数值容差在配置中明确，不做任意表达式等价判定 |

标准答案与解析在本题首次提交后才展示。即时判分与本轮达标判定均采用固定规则，无需 LLM；后续综合评估可以使用这些轮次及首答记录。

### 5.5 节点小题达标规则

**同一次 attempt 内，5 道题均已作答且每题首答正确，本轮才通过。** “一次性做对”指首答正确，允许中途退出再继续；完成与通过分别判断。

首期以最近一次完成的 attempt 更新节点状态：限定 `user_id / node_id` 与 `status = 'completed'`，按 `completed_at DESC, id DESC` 取第一条，使用第 5.2 节的部分索引；`id` 仅用于完成时间相同时稳定排序。未完成或已关闭的轮次不覆盖既有结论。已掌握后新一轮出现错题，也等待本轮五题全部完成后再改为待巩固。

| 情况 | 状态 |
| --- | --- |
| 最近完成轮次为 5/5 | 已掌握 `mastered` |
| 最近完成轮次不足 5/5 | 待巩固 `needs_review` |
| 新一轮进行中 | 保留上次结论，附加“练习中” |
| 尚无完成轮次 | 未评估 `unassessed`；有进行中轮次时另显示“练习中” |

该状态作为首期系统掌握标记，注明来源“节点小题固定规则”及对应 attempt。状态从记录推导，不再复制一套成绩表；它表示最近一轮检测结果，不认定永久掌握。结合整题表现的综合掌握评估属于第 7 章。

## 6. 个人图谱与访问范围

```text
整题：学生 → 尝试 → 步骤事件／汇总 → 步骤—节点关联
小题：学生 → 节点练习 attempt → 5 条首答记录 → 小题 → 节点
                              ↓
                   个人节点状态叠加在公共图谱上
```

- 现有 `student_learning_marks` 保留 `practiced` 与学生自评，不从旧标记补造逐步作答历史。
- 整题只统计实际走过的路线；一步通过不等于全部关联节点掌握，同一步关联多个节点不算多份独立证据。
- 无记录表示尚未观察。反复刷同一题、同题更换 ID、提示后完成，不自动视为多道独立题的成功证据。
- 新增公共关系或题目不改写学生历史；不能因答对后续知识自动认定全部前置知识已掌握。
- 学生只能访问自己的记录，复用现有登录校验；匿名练习不生成带学生身份的记录。内容下架不得级联删除学生记录。
- 首期不实现自动跳步、完整网页回放或跨设备恢复未提交输入。未来简化已掌握步骤时仍需保留必要数学结论，系统代做不计学生答对。

## 7. 综合学习效果评估（待讨论）

节点小题按第 5.5 节执行固定规则。本章仅讨论如何结合整题应用与多轮小题表现形成综合评估；数据采集和首期规则可先实施，后续评估器独立增加或替换。

| 讨论项 | 保留方向 |
| --- | --- |
| 不同节点的掌握标准 | 公共评估框架加节点差异，考虑独立完成、提示、重试、跨题应用、证据数量及时间 |
| 思路总结与上下文 | 按节点组织整题背景和相关步骤原始问答，结合小题轮次、首答选项及对应反馈；可生成引用原记录的步骤总结 |
| 评估方式 | 比较简单规则、LLM 与知识追踪算法，评分定义和掌握阈值尚未确定 |
| 更新时机 | 候选为定时处理新增证据＋学生主动触发；页面读取上次结果，无新证据且策略未变时复用 |
| 结果与验证 | 保存状态、可空分数、依据、评估时间与策略标识；用教师审阅和学生后续新题的独立表现验证 |

综合评估结果表预留 `student_node_assessments`，以 `(user_id, node_id)` 为键，与小题固定规则的来源区分。结果需标明所用记录范围与是否有新证据待评估；旧任务不能覆盖基于更新证据的结果，失败时保留上次结果。记录保存及小题达标判定不等待总结或综合评估。

LLM 上下文使用节点详细说明、整题练习快照、相关原始事件及小题首答记录，不重复拼入无关历史。总结只作辅助，不能将老师的答案归为学生独立思路；转写歧义和证据缺失需保留不确定性。LLM 给出 80 分不代表 80% 的掌握概率，证据不足时可以不给分。

可比较的算法：

| 算法 | 用途 |
| --- | --- |
| [BKT：贝叶斯知识追踪](https://arxiv.org/abs/2105.00385) | 根据连续作答更新潜在掌握状态，考虑学习、猜对与失误 |
| [PFA：表现因素分析](https://pact.cs.cmu.edu/pubs/AIED%202009%20final%20Pavlik%20Cen%20Keodinger%20corrected.pdf) | 根据知识点上的成功、失败次数预测后续表现 |
| [教育场景的 Elo](https://is.muni.cz/publication/1376317/cs/Applications-of-the-Elo-rating-system-in-adaptive-educational-systems/Pelanek) | 联合估计学生能力与题目难度，辅助推荐 |

不同模型输出不能直接互换成掌握百分比。先用可解释规则作比较基线，通过真实后续表现检验；可以算法给分、LLM 解释。轻量算法可逐次更新，异步调用只是 LLM 方案的成本与等待时间选择。
