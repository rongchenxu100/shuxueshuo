# FM-T3：R0 实现范围与专题验收

日期：2026-11-06。承接 [FM-T3 开发设计](function-monotonicity-inequality-problem-type-design.md)。**R0–R2** 已落地：已知严格单调性、先证再比较、以及常值段分流到分段解不等式（B12）。B06 以显式定义域教学变式入库；原图题范围约定仍保留，生产发布仍未做。本记录不是整个 T3 或生产发布完成声明。

## 1. 本次入口与题源台账

[函数单调性专题](http://127.0.0.1:8779/topics/function-monotonicity/) 在 T1／T2 之外新增 T3 题。题源仍是[原照片及摘要](../internal/senior-high/source-images/function-monotonicity-planning-20261104/manifest.json)，只按印刷题意定标。

| 原题 | 方法与关键结构 | 数学结果 | 本次状态与入口 |
| --- | --- | --- | --- |
| B01 | M5；两输入合法 → 递增保序 → 求交 | $(0,1)$ | 规范题意、数学、教学通过；[Q05](http://127.0.0.1:8779/topics/function-monotonicity/q05/) |
| B02 | M5；有限域 $[-1,1]$、**增函数**保序 | $(\frac12,\frac23]$ | 原图核定为增函数；[Q02B](http://127.0.0.1:8779/topics/function-monotonicity/q02b/) |
| B03 | 段内增减（带图）→ 跨段合图 → M5 转化 | $(-\frac32,2)$ | 无剧透核对卡；嵌套 M3 压缩档；[Q03B](http://127.0.0.1:8779/topics/function-monotonicity/q03b/) |
| B04 | M5；全域递减 → 反序 → 二次不等式 | $(-1,3)$ | 规范题意、数学、教学通过；[Q06](http://127.0.0.1:8779/topics/function-monotonicity/q06/) |
| B05 | M5；常量输入、递减反序、半开区间 | $[\frac12,\frac23)$ | 规范题意、数学、教学通过；[Q09](http://127.0.0.1:8779/topics/function-monotonicity/q09/) |
| B06 | M5；教学变式显式 $D_f=(-1,1)$、递增保序 | $(0,\frac23)$ | 注明补充定义域，非 OCR 改写；[Q06B](http://127.0.0.1:8779/topics/function-monotonicity/q06b/) |
| B09 | ①求值；②段内图 → 跨段合图 → 转化（同 B03 压缩档） | $15$；$(1,4)$ | 双目标顺序完成态；不等式问无剧透核对卡；[Q09B](http://127.0.0.1:8779/topics/function-monotonicity/q09b/) |
| B12 | 常值段 → 不能去 $f$ → 分段解不等式双复合输入 | $(-1,-1+\sqrt2)$ | 四组合分类与课包通过；[Q12B](http://127.0.0.1:8779/topics/function-monotonicity/q12b/) |
| B13 | M5；与 B05 对照，递增保序 | $[\frac12,\frac23)$ | 规范题意、数学、教学通过；[Q13](http://127.0.0.1:8779/topics/function-monotonicity/q13/) |

人工审核题意记录见 [function-monotonicity-t3-20261106](../internal/senior-high/authored-courses/function-monotonicity-t3-20261106/)。2026-11-06 的实现轮未纳入拍题验收；2026-11-09 新增的真实图片验收见第 6 节，不以人工题意冒充识别结果。

## 2. 方法、技能与复用

| 对象 | 本次实现 | 复用关系与界限 |
| --- | --- | --- |
| M5 `method-monotonicity-inequality` | 单调性解不等式法 | 组织输入合法条件、单调性依据、等价转换、代数子问题与原目标验证 |
| `skill-monotonicity-order` | 利用单调性转化不等式 | 严格递增保序、严格递减反序；不负责解出变量范围，也不证明单调性 |
| `rule-monotonicity-inequality-method` | 本型选法规则 | 已知单调性路线 preferred；分段解不等式路线作为 unfit 对照线索 |

执行与独立验证位于 `graph_lesson/monotonicity_inequality_math.py`、`stage_three/monotonicity_inequality_runtime.py`；教学投影位于 `monotonicity_inequality_presentation.py`。新模块已纳入执行／教学指纹、方法准入、路由结果模式与交互协议。

R0 支持：抽象 $f$ 带题给严格单调区间，且已知条件能保证所有合法输入都落在该区间；固定有理系数、二次及以下的多项式／常量输入；$<,\le,>,\ge$。单调区间 `domain` 与完整定义域 `function_domain` 分开记录；后者只能来自题给条件。不能证明覆盖全部合法输入时，不输出全解。R1 支持：显式两段一次／二次分支、跨段像序合并、`basis_from_proof`、M5 守卫嵌套 `method-piecewise-monotonicity`、单调性不等式 D1 定位、B03／B09 课包。R2 支持：`method-piecewise-inequality` 双复合输入交叉分类、常值段适用性卡与 B12 课包。B06 教学变式已显式写出 $D_f=(-1,1)$；原图印刷题（未写完整定义域）仍不作为已确认全解发布。

## 3. 教学流程

- 选法：配对「同一个函数的两个函数值比大小」→ 单调性解不等式法；分段线索对本批题 unfit。
- 主线：核对比较对象与单调性 → 两个输入的合法条件 → 利用单调性转化比较（待答位置只放关系）→ 与合法域求交回到原目标。
- 待答结论在确认前隐藏；错误选项不推进。

## 4. 测试与未做事项

- 求解／独立验证／选法执行：`tests/solver/test_graph_monotonicity_inequality.py`
- 课包原生判定：`tests/auth/test_function_monotonicity_inequality_courses.py`
- 2026-11-06 尚未做：原图 B06 印刷题全解发布、真实照片识别链路、生产专题发布；后续拍题结果见第 6 节。

## 5. 2026-11-09 review 修复与回归

本轮修复上一轮 review 的五项问题：

1. 区分完整定义域与已知单调区间。原图 B06 条件不足时拒绝给出全解；显式补充定义域的教学变式正常求解。显式函数依据其实际定义检查覆盖范围。单调性、定义域及依据也进入题意等价比较，修改这些条件不能复用旧题意结论。
2. 求值只跳过同一作用域内、由另一求范围小问使用且与当前求值变量无关的函数值比较；当前小问依赖的限制条件不得被忽略。
3. 重新生成九道 T3 课包和公开知识图谱，修正课包版本与公开作答合同不一致。已有 T1／T2 课包及旧题公开作答合同与 HEAD 相同。
4. 分段适用性卡依据实际分支生成内容；没有常值段时不再误判“不严格单调”。图像按二次分支的顶点拆分增减区间，不再固定描述为左常值、右递增。
5. 分段函数保留原分支端点归属，但最终单调区间使用连接点的实际函数值判断能否补入端点；连续连接、跳跃与定义域缺口分别处理，相等常值段可合并。

| 检查范围 | 本轮结果 |
| --- | --- |
| 求解、独立验证、求值条件、文本与配图分流、T3 课包判分 | 238 项通过 |
| T1／T2 前端流程、共享课包身份、分段选择与倒数图像 | 53 项通过 |
| T1 拍题回归 | 六张历史真实题图的模型响应录制回放通过；三项课程 API 生成及恢复通过 |
| T2 拍题回归 | 14 项通过，包含八题录制回放、三项课程 API，以及历史识别失败记录的保留检查；不表示历史失败题重新识别成功 |
| 发布生成物 | 九道 T3 课包逐一 `--check`；公开图谱与专题概览 `--check` |
| 静态检查 | 本轮修改的九个 Python 文件 Ruff 通过；`git diff --check` 通过 |

API 使用新建的独立 PostgreSQL 实例 `fm-review-20261109`（端口 55439，数据目录 `/private/tmp/shuxueshuo-fm-review-20261109`）。安装、迁移后，指定 `PRODUCT_TEST_DATA_DIR` 与 `PRODUCT_TEST_INSTANCE` 执行测试；完成后已停止该实例。日常本地学习服务未部署或迁移。

```sh
# 在 server/ 下，先安装隔离数据库（需本机已安装 PostgreSQL 17）
./.venv/bin/python -m shuxueshuo_server.product.admin.cli \
  --mode local --data-dir /private/tmp/shuxueshuo-fm-review-20261109 \
  --instance fm-review-20261109 --port 55439 install

# 对已安装并启动的测试实例执行；重复使用时先运行同实例的 db-start
PRODUCT_TEST_DATA_DIR=/private/tmp/shuxueshuo-fm-review-20261109 \
PRODUCT_TEST_INSTANCE=fm-review-20261109 \
./.venv/bin/python -m pytest -q \
  tests/search/test_function_monotonicity_photo.py \
  tests/search/test_function_extremum_photo.py

./.venv/bin/python -m shuxueshuo_server.product.admin.cli \
  --mode local --data-dir /private/tmp/shuxueshuo-fm-review-20261109 \
  --instance fm-review-20261109 db-stop
```

范围说明：录制回放读取真实图片和已保存的模型响应；API 用例准备已有识别结果，验证课程生成、快照和恢复。这次没有重新上传图片、浏览器裁剪或实时调用模型，也没有做 T3 新照片识别验收。历史 T1 测试方式见 [T1 验收记录第 4、7 节](function-monotonicity-t1-acceptance.md)。上一轮 `config.not_installed` 是旧临时测试目录缺少可用配置，此轮通过重建隔离实例完成 API 回归。

复审未发现上述修复中的新增阻塞问题。未运行全库测试：`test_math_notation_state_scope.py` 的旧辅助代码仍假设所有目标 Schema 内联且必含 `expression/object/symbol`，HEAD 已有相同不适配；全历史课包的全局教学指纹检查限制沿用 T1 验收记录，不以本轮定向通过代替全库通过。本轮未提交、push 或发布。

## 6. 2026-11-09 新调用照片验收

结果：**8 道题的识别、数学结果、课程生成和重开恢复通过；B06 原图识别通过，但因缺少完整定义域，不发布全解。** 这不等于 9 道题全部可解。

### 6.1 输入与实际调用范围

使用原始归档照片 `source-image-03.jpg`、`source-image-04.jpg` 的印刷题面，保持手写内容原样，由识别忽略手写答案；没有用人工题意 JSON 替代模型输入。两张原图均为 1279×1706，原图 SHA-256、逐题像素裁框、实际上传图及发给模型的预处理图分别保存在每份录制中。

本轮经过真实鉴权的 `POST /api/search/pages` 上传原照片，执行 OCR、方向校正及分题，再通过 `POST /api/search/problems` 提交人工核对的裁框，重新调用 DeepSeek 完成提取／复核；随后运行判型、数学验证、交互课生成，并通过课程 start／snapshot 接口检查重开后 stream 与快照保持相同。照片 3 自动识别出 6 个区域，照片 4 为 8 个；本轮逐题使用核对后的裁框，不声称自动分题覆盖了全部题目。

这是**开发题源原照片上的全新模型调用和后端 API 验收**，不是旧响应回放，也不是未见过的新拍摄角度／光照样本。本轮没有通过浏览器手动操作上传和拖动裁框，也没有把课程快照重开等同于学生答题进度提交。

共创建 14 次题目识别，发生 29 次语义模型调用，包含失败和复测；最终每题采用的识别记录均为 extract → review 两次调用。原始失败单独归档，没有用成功输出覆盖：

- [录制目录](../server/tests/search/fixtures/function-monotonicity-inequality/)：`b01` 至 `b13` 中本批 9 题的最新真实调用；`b01-initial`、`b03-initial`、`b06-initial`、`b09-initial`、`b12-initial` 保留首轮问题。
- 每份 `recording.json` 记录文件摘要、调用阶段、真实 API 状态与时间；`workflow/calls/` 保留请求和响应，`result.json` 保留识别结果。
- [B05／B09 修复后 API 证据](../server/tests/search/fixtures/function-monotonicity-inequality/api-revalidation-20261109/)：使用同一份真实识别结果重新验证读题卡、课程和重开；该项没有再次调用模型，明确标记为 API 回归。

### 6.2 逐题结果

时间从创建裁图题开始计算，不包含整页上传／OCR。就绪时间取真实调用当次；B05／B09 最后补做的读题卡 API 回归耗时不混入此列。

| 题目 | 识别完成 | 课程就绪／拒绝 | 最终验收结果 |
| --- | ---: | ---: | --- |
| B01 | 63.4 秒 | 70.8 秒 | 通过；$(0,1)$；读取题给 `Dom(f)` |
| B02 | 73.9 秒 | 81.8 秒 | 通过；$(\frac12,\frac23]$；保留印刷的“增函数”与闭端点 |
| B03 | 20.5 秒 | 31.6 秒 | 通过；$(-\frac32,2)$；程序先证分段函数整体严格递增 |
| B04 | 27.1 秒 | 34.6 秒 | 通过；$m\in(-1,3)$；递减反序 |
| B05 | 78.1 秒 | 85.5 秒 | 通过；$[\frac12,\frac23)$；“x 值的取值范围”定位补做 API 验证 |
| B06 | 55.4 秒 | 57.6 秒（拒绝） | 识别通过、全解不发布；只保留 $(-1,1)$ 上严格递增，没有补造 `function_domain` |
| B09 | 34.7 秒 | 50.3 秒 | 通过；$f(f(1))=15$ 和 $(1,4)$ 两问；公式外填空横线定位补做 API 验证 |
| B12 | 39.7 秒 | 47.6 秒 | 通过；$(-1,-1+\sqrt2)$；有常值段，走双复合输入的分段解不等式路线 |
| B13 | 65.3 秒 | 72.4 秒 | 通过；$[\frac12,\frac23)$；与 B05 的增减方向、不等号分别保留 |

8 道可解题当次课程就绪耗时为 31.6–85.5 秒，中位数 60.6 秒；没有据此宣称处理速度问题已经解决。

### 6.3 验收发现并修复的问题

1. **题给定义域的两种表示衔接。** 实际模型会将完整定义域写为 facts 中的 `Dom(f)=I`；T3 原先只读取目标 metadata，导致 B01 被拒绝。现在读取并逐项定位该事实，正反等式均支持；矛盾定义域仍拒绝。
2. **显式分段函数不能依赖模型提前证明。** B03／B09 的真实候选只有原定义和不等式，这正是合法提取。程序现在从原定义验证整体严格单调，再调用已有 M3 → M5 教学路线。原候选不被添加推导条件；常值段、下降跳跃和断开的定义域不会误走严格单调路线。
3. **原文定位。** 支持“x 的解集”“该不等式的解集”“x 值的取值范围”，以及公式内／外的填空横线。只有明确空白可视为提问，`f(2)=3` 之类已给等式不能被当作求值问。
4. **提取、复核、修复的共用提示规则。** B12 首次复核错误地认为 `find_range.symbol` 加 facts 中原不等式不完整，触发不合法修复。共用规则现明确这种表示已经完整，不能要求补入求解析式的字段；题给单调性使用对应 metadata，不展开成当前语法不支持的两点蕴含式。局部单调区间仍不等于完整定义域，具体分段函数的单调性仍由程序证明。本轮确实修改了共用 prompt，不仅是代码。

首轮 B06 的量词表示编译失败、B12 的复核振荡均保留为失败记录。复测 B06 已完成正常提取和复核，最终是题意范围保护拒绝全解，不能把它记为“已成功生成课程”。

### 6.4 必要回归与复现

- 数学、原文定位、严格单调性保护及分段求解：123 项定向单元测试通过。
- 新录制回放、原图摘要与原始裁剪核对、独立数学结果、B06 拒绝和历史失败保留：13 项通过。
- B05／B09 读题卡修复后的鉴权课程 API、双目标、重开快照：2 项通过。
- 既有 T1／T2 真实题图的历史响应回放：17 项通过；不包含新模型调用。
- Ruff 与 `git diff --check`；同步九道 T3 课包，检查公开知识图谱和专题概览。既有 T1／T2 课包不随此次修改整体改版。

复现新的实时调用（会产生模型费用）使用 [录制脚本](../server/tools/record_function_monotonicity_inequality_photos.py)。隔离实例安装方式同第 5 节，以下命令在 `server/` 运行：

```sh
./.venv/bin/python -m shuxueshuo_server.product.admin.cli \
  --mode local --data-dir /private/tmp/shuxueshuo-fm-review-20261109 \
  --instance fm-review-20261109 db-start

# output 必须是尚不存在的新目录；可用 --cases b03 b09 只录指定题
RUN_LLM_INTEGRATION=1 \
PRODUCT_TEST_DATA_DIR=/private/tmp/shuxueshuo-fm-review-20261109 \
PRODUCT_TEST_INSTANCE=fm-review-20261109 \
./.venv/bin/python -m tools.record_function_monotonicity_inequality_photos \
  --output /private/tmp/fm-t3-new-live-recording

# 零模型调用的录制回放及课程 API 回归
PRODUCT_TEST_DATA_DIR=/private/tmp/shuxueshuo-fm-review-20261109 \
PRODUCT_TEST_INSTANCE=fm-review-20261109 \
./.venv/bin/python -m pytest -q tests/search/test_function_monotonicity_inequality_photo.py

./.venv/bin/python -m shuxueshuo_server.product.admin.cli \
  --mode local --data-dir /private/tmp/shuxueshuo-fm-review-20261109 \
  --instance fm-review-20261109 db-stop
```

本轮使用 55439 端口的独立测试库，验收结束停止实例；未迁移日常本地库，未提交、push 或发布。浏览器上传交互、新拍摄角度的独立样本、生产发布仍未验收。
