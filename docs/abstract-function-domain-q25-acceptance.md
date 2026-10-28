# T3 第25题：抽象函数定义域第一批验收

日期：2026-10-28。状态：**8 项复审问题及第一批数学、原图识别与求解链路已验收。本轮把常驻对照板改为逐步推导卡，改版验证单列于 §8；此前浏览器与生成物结论不自动代表新界面通过。**

遵循 [T3 设计](abstract-function-domain-problem-type-design.md) 与[专题与拍题开发流程](topic-and-photo-learning-development-workflow.md)。本批代表题为 Q25：已知 $f(x)$ 的定义域为 $[-3,2]$，求 $f(2x-1)$ 的定义域，答案 $[-1,\frac{3}{2}]$。

## 1. 本批范围

| 项 | 状态 |
| --- | --- |
| IR `find_abstract_domain`（identity 已知式 + exact 域 + 仿射目标） | 已实现 |
| 特征／识别／选法 → `method-input-domain-correspondence` | 已开放 |
| 仿射逆像（正负零斜率、单点、无界、外层交） | 定向测试通过 |
| 三步教学（输入范围／完整输入及条件／定义域） | 数学顺序不变；本轮逐步推导卡验证见 §8 |
| 独立验证 `abstract_domain_identity` | 定向测试通过 |
| Q25 原图归档与裁片 | 已完成（第84页例8） |
| 正式专题课包与页面 | 已纳入 `abstract-domain` |

## 2. 冻结候选与原图

构造候选见 [q25-candidate.json](../server/tests/solver/fixtures/abstract-function-domain/q25-candidate.json)。题面与原页裁片一致；来源登记见 [manifest.json](../internal/senior-high/source-images/function-concepts-q25/manifest.json)。

完整原页保留书中解析与答案。旧裁片 `crop.xyxy=[50,455,717,522]` 截断了倾斜题干，已保留为 `source-question-truncated.png` 并标记拒收。当前按 `[100,500,649,535]` 从完整原页一次矩形裁出全部题干与填空线（549×35），不含解析或答案。回归逐像素验证两份裁片来自登记原页，并校验全部 SHA-256。

## 3. 定向验证

```bash
cd server && uv run pytest \
  tests/solver/test_graph_abstract_function_domain_math.py \
  tests/solver/test_graph_abstract_function_domain_q25.py -q
```

```bash
node --test tools/tests/graph-walk-function-q25.test.mjs
```

覆盖：仿射逆像分支、Q25 编译／特征／识别／选法、完整 M2 执行、三张教学卡及端点复核、课包回放与专题登记。本节命令为复用入口，本轮视觉改版结果单列于 §8。

## 4. 课包与专题

| 产物 | 路径 |
| --- | --- |
| 证据 | `site/data/graph-walk/function-concepts-q25.evidence.json` |
| 课包／回放 | `site/data/graph-walk/function-concepts-q25.{json,replay}.json` |
| 页面 | `/topics/function-concepts/q25/` |
| 专题分组 | `function-concepts.json` → `abstract-domain` |

隔离实例录制：`PRODUCT_TEST_DATA_DIR=/private/tmp/sss-domain-first-20261028`，`PRODUCT_TEST_INSTANCE=domain-first`；最终原图 run_id `9f0a155cef7f4da784c51f10bc916c1e`。答案区间 `Interval(-1, 3/2)`。

## 5. 本轮复审修复及真实拍题

1. 独立验证直接解释原 AST，将实轴按原条件的临界点分区检验，不再重调求解器；端点检查代入原输入与外层范围。
2. 读题／对齐准确区分已知函数与目标式，不把正确的自变量解释判错。
3. 待答卡隐藏当前所求的完整输入和最终域；完成后才揭示。
4. 恒等／反射等情形按精确集合去重选项，所有干扰项必须数学上错误。
5. 边界卡绑定外层变量，避免 `None=…`。
6. `ℝ` 与无界区间同义处理。
7. `f(t)` 与 `f(2x-1)` 分别绑定已知哑变量和目标变量。
8. 拍题投影补 D1 读题卡，串联 D1→D2→D3；同时修复题意整理仅显示“求”。

两次实际浏览器相册上传使用同一修正原图；送模图 SHA-256 均为 `49e9facca18dc7a7d2b64005c339a50527d94ab32c9d7d8b2be8655de1ccdcc4`。

| 实际运行 | 结果 | 用途 |
| --- | --- | --- |
| `fac08a9f5cc1` | extract→review，14.098 秒 | 首次四卡版本检查；保留录制，不作为最终三步 UI 通过证据 |
| `3abfa72dc7c0` | extract→review，17.414 秒 | 最终三步版本的完整识别与求解验收 |

真实响应保存在 `server/tests/search/fixtures/abstract-function-domain/` 的两个录制目录。未改模型响应文本，仅脱敏供应商标识；离线重放验证所有调用及哈希，不把离线重放声称为新增模型验证。

### 改版前浏览器及自动回归

- 实际浏览器共 7 次确认：读题、认题型、选方法、三步对照教学、端点复核。终答为 $[-1,\frac32]$。
- 读题误选值域、误把 $x$ 当完整输入、误选已知区间均停在当前步骤并反馈；答对才推进。
- 完整输入／最终定义域在未作答时保留空位；刷新恢复到第 6 步，前 5 步保留。端点显示 $x=-1$ 与 $x=\frac32$。
- 学生完成 7/7；AI 回放完成 7/7；切回自己做保留原进度。另重开练习后切换 AI 再返回，自己做仍为 0 步，验证两种进度隔离。
- [实际完成截图](../internal/review-analysis/q25-fixes-20261028/photo-student-completed.png)；结构化记录见最终照片录制目录 `lesson-verification.json`。
- T3 数学／原文／教学及直接依赖回归 190 项通过；数据库完整链路与已有定义域回归 39 项通过；最终修改后定向重跑 30 项通过。以上有重叠，不简单相加。
- 两次真实照片重放、裁片溯源、鉴权 API 共 4 项通过；前端提取显示／入口 233 项、Q25/topic/state 29 项、DOM/build/replay 64 项通过。
- Ruff 与 `git diff --check` 通过；四项 builder `--check` 均 `changed=0`。demo 原 14 条动作经过官方重放与验证后更新，不直接替换版本号。

## 6. 留出与后续

至少一张未参与本批调试的留出真图验收（如变式 1）仍待补；失败转回归并补新留出样本。本批其余抽象域题型目标按设计台账继续推进。

当前仅开放“已知恒等写法的精确定义域 → 仿射目标”的首批范围；复合已知式反推、meaningful_only、多层嵌套、函数值条件等未开放。

## 7. 改版前本地交付

日常 `8779` 服务已重启（PID `16955`），Q25 页面 HTTP 200，专题 AI 回放 7/7，通过后切回自己做仍为 0 步。按用户约定直接清空本地学习测试数据并重新发布课程，不保留旧练习记录；本轮先前生成的临时数据库备份已删除。当前发布 48 题、59 条路线、366 个评分步骤，内容版本 `f7bbcfb08d8a77c65c0e84f54ae020cbcaebbe4b6f2c51b25a35fc25c2347708`。隔离服务与测试数据库已停止。

## 8. 逐步推导卡改版

本轮只调整教学投影与显示，不修改提取或数学能力。每步使用 `stem_board.layout=derivation`：两项内容经 `⇒` 连接，左侧为本步已知，右侧为本步产物。待答时右侧 `math=null`，完成后的数学高亮使用同一结构并填入答案；去掉常驻三行对照板。涉及目标时统一称“目标函数”并写明 $f(2x-1)$。

验证要求：三步各自聚焦、待答不提前显示本步答案、错误不推进、正确提交才揭示；专题与拍题两种模式、刷新恢复和窄屏保持一致。已有原图模型响应只作离线重放，不计为本轮新模型调用。

本轮照片回归 **4 项通过**（7.76 秒）：

```bash
cd server
PRODUCT_TEST_DATA_DIR=/private/tmp/sss-domain-first-20261028 \
PRODUCT_TEST_INSTANCE=domain-first \
.venv/bin/python -m pytest -q --tb=short tests/search/test_abstract_function_domain_photo.py
```

覆盖已有两次真实模型响应的完整离线重放、裁片像素与哈希、鉴权拍题 API、T3 读题与求解、三张推导卡及端点复核。逐卡断言待答右项为空、完成高亮填入本步答案、目标函数一致；最终答案仍为 `Interval(-1, 3/2)`。重复开始与刷新返回同一快照，禁止重新调用模型或求解器。

本轮重新投影已有照片识别结果，生成 run `5cacedbf7cfd454aac1025ede56503a5`，未再次调用模型。后端展示与契约回归 34 项、源级 UI 回归 175 项、新课包与 DOM 回归 69 项通过（范围有重叠，不相加）；真实 evidence 的完整交互脚本通过。四项 builder `--check` 全部 `changed=0`。

新版专题浏览器实测：

- 自己做完整完成 7/7；第一张推导卡误选“函数值范围”后停留，问号保留；正确提交后已完成卡原位显示输入范围。
- 三张卡仅包含本步已知与本步结果；未答时右侧问号，完成后为对应公式；重复答案摘要和成功反馈不再堆叠，完整推导默认收起。
- AI 回放完成 7/7，切回自己做仍为已完成状态。
- 桌面展示左右布局；展开图谱后的 280px 内容窄列自动改为上下布局，箭头转向，三张卡均无横向溢出。这是窄列验证，不冒充独立移动设备测试。

日常 `8779` 服务已重启（PID `20924`），页面 HTTP 200。发布与站点版本一致：`205e1f665231b6a8e49b895ca1fcec0fb68863830827ad8b2afbf61028f0b42b`。本地更新直接丢弃旧测试练习记录，不创建备份或迁移。
