# 图谱交互课程阶段①实现计划：题意与数学特征

阶段①负责题图提取、原图复核、受控修复与确定性特征计算。当前使用 `graph-problem-extraction/v2` 和小问树；学生拍题的公共身份封装见 `search-problem-extraction/v1`。来源共用规则见[专题开发流程](topic-and-photo-learning-development-workflow.md)。阶段完成以当前契约下的逐题验证为准。

## 1. 目标与交付边界

实现独立的阶段①入口，完成以下链路：

```text
仅含题面的图片
→ LLM 转录原题、提取数学题意
→ 程序校验记法与作用域
→ 原图复核及必要修复
→ 程序计算数学特征
→ 阶段①产物 + 人可调试报告 + 阶段②可重放输入
```

交付范围：

- Q01–Q11 的题源清单、题意金标和特征金标；每题均有独立测试 ID。
- 不含 family 判断的 LLM 契约、提取入口、原图复核与有限修复流程。
- 按目标计算的特征注册表及其中的**结构特征**，输出数学表达式、枚举、布尔值和带原因的未知；每个特征登记关联的公共知识点或条目。
- 每题真实调用、失败留档、单题重跑、无网络回放、耗时统计和 HTML 调试报告。
- 可供阶段②直接读取、受版本管理的录制产物。

本阶段不实现题型识别、方法选择、最终参数范围求解、D1–D4、课程编排或产品 WebSocket 接线。已有合格题意的程序入口也要支持，但真实集成验收必须从图片起步。

注册表中的**方法前提检查**（能否分离参数、除式符号、首项系数为零的逐级降次分支）属于阶段③，本阶段只确定注册表格式，不实现这些检查，见设计文档第 4.2 节。

## 2. 复用能力

| 原有入口 | 复用内容 | 本次调整 |
| --- | --- | --- |
| `problem_understanding/notation_parser.py`、`algebra.py` | 受控数学记法、量词、区间、有界代数解析 | 沿用表达语言；补齐半无限区间 |
| `notation_compile.py`、`notation_normalization.py`、`notation_semantics.py` | 对象绑定、作用域、规范化与语义比较 | 抽出与顶层响应 Schema 无关的 root 编译及比较入口 |
| `workflow.py`、`workflow_ledger.py`、`workflow_storage.py` | extract/review/repair、预算、调用预约、哈希绑定、恢复 | 提取契约适配接口；新阶段使用无 family 的适配器，保留共用调度与账本 |
| `solver/extraction/multimodal_provider.py`、`problem_understanding/batch_smoke.py` | 图片传输、真实 provider 工厂与调用审计 | 注册新契约名 |
| `server/tools/report_math_notation_workflow.py` | 原图、候选、调用过程、差异的 HTML 展示 | 复用组织方式，补上特征链及无效 JSON、截断、超时的展示 |

上述 `problem_understanding/` 位于 `server/shuxueshuo_server/`，测试位于 `server/tests/solver/`。

**去除 family 是契约调整，不是把字段设为 null。** 新入口通过 `NotationValidator.validate_root()` 复用数学核心，由 `GraphStageOneContract` 接入共享工作流，不给候选补 `unmatched/null`。旧提取链保留原契约。

Q07 的集合描述 $\{x\mid2\le x\le3\}$ 不扩展解析器：表达目录要求 LLM 在题意中写成等价区间 `x∈[2,3]`。

## 3. 题源与金标

### 3.1 输入来源

Q01–Q09 的题干取自 `site/2/q01/index.html` 至 `site/2/q09/index.html` 的 `.problem-card > p[data-math-text]`。后面的“题意整理”、教学步骤、脚本配置含额外解释或答案，不能进入模型输入。

首批采用从**原题段**渲染的图片：固定每题 `problem.md`，以固定字体、公式渲染器、宽度和缩放生成 `source.png`，manifest 标记 `source_kind=synthetic-rendered` 并保存来源 HTML、选择器、渲染配置和哈希。合成题图不能据此宣称已覆盖真实扫描识图质量。图片集成测试只发送图片及通用表达规范。

站点没有第 2 章的多问题，Q10、Q11 为按教材常见题型编写的多问题：`problem.md` 即题源，用同一渲染流程生成题图，manifest 标记 `source_kind=authored-rendered`，小问分行排版。

### 3.2 逐题验收矩阵

下表为题意与结构特征检查点，不是发给 LLM 的 few-shot 或解题提示。

| 题号 | 量词关系 | 目标 | 必须核对的结构特征 |
| --- | --- | --- | --- |
| Q01 | $\forall x\in\mathbb R:\ -x^2+2x+3\le a^2-3a$ | $a$ | 非严格关系；关于 $x$ 为二次，首项系数不含参 |
| Q02 | $\forall x\in\mathbb R:\ kx^2+2kx-(k+2)<0$ | $k$ | 严格关系；量词变量与实数域按补全规则得到；关于 $x$ 至多二次，首项系数 $k$ 含参 |
| Q03 | $\forall x\in\mathbb R:\ (a^2-1)x^2-(a-1)x-1<0$ | $a$ | 量词变量与实数域按补全规则得到；首项系数 $a^2-1$ 含参 |
| Q04 | $\forall x\in[1,2]:\ x^2+mx+4<0$ | $m$ | 闭区间与严格关系 |
| Q05 | $\exists x\in(1,2):\ x^2+mx+4>0$ | $m$ | “有解”是 $\exists$；开区间；严格关系 |
| Q06 | $\forall x\in(-\infty,0):\ x^2+ax+2\ge0$ | $a$ | 半无限开区间，无穷端点不可取；非严格关系 |
| Q07 | $\forall x\in[2,3]:\ mx^2-mx-1<0$ | $m$ | 集合描述写成闭区间；首项系数 $m$ 含参 |
| Q08 | $\forall m\in[1,3]:\ mx^2-mx-6+m<0$ | $x$ | 量词变量是 $m$；关于 $m$ 一次、关于 $x$ 二次；给出范围的变量不是主元；$y$ 展开在量词内 |
| Q09 | $\forall a\in[-1,1]:\ ax^2-(a+1)x+1>0$ | $x$ | 量词变量是 $a$；关于 $a$ 一次、关于 $x$ 二次；$y$ 展开在量词内 |
| Q10（1） | $\forall x\in\mathbb R:\ f(x)\ge0$，$f(x)=x^2-2ax+3$ 在根节点 | $a$ | $f$ 定义在根节点、量词在小问；展开后关于 $x$ 二次 |
| Q10（2） | $\exists x\in[1,2]:\ f(x)<0$ | $a$ | 与（1）量词、量词域都不同，两问互不可见 |
| Q11（1） | 小问内 $m=1$、$f(x)<0$，$f(x)=mx^2-mx-1$ 在根节点 | $x$ | 解不等式写成对 $x$ 的范围目标；无量词，结构特征为 `unknown` |
| Q11（2） | $\forall x\in[1,3]:\ f(x)<-m+5$ | $m$ | $m=1$ 不得泄漏到本问；首项系数 $-m$ 含参 |

两条补全规则（写在提示词与表达目录中）：未限定自变量范围的实系数多项式不等式按实数域理解；原题只说“恒成立”而未指明变量时，取除待求量以外唯一的自由变量为量词变量，不唯一时报告待确认。目标变量的 `c∈ℝ` 事实写或不写都语义等价，验收不作要求。

### 3.3 金标目录

`server/tests/solver/fixtures/graph-guided-stage-one/quadratic-always/`：

```text
manifest.json
q01/ ... q11/
  problem.md
  source.png
  source-manifest.json   # 来源（站点题段或自编）、渲染配置、题文与图片哈希
  notation.gold.json     # original_text + root（多问题含 children）
  features.gold.json     # graph-stage-one-feature-expectations/v2，每行带 target_ref
  acceptance.json        # graph-stage-one-acceptance/v4，按目标列出
```

金标依据题源独立编写，不从模型响应复制后标为正确。`acceptance.json` 按目标声明所求、量词与量词变量、量词域和必需特征；金标文件随仓库版本管理，不再另设哈希修订链。

## 4. 输入输出契约

### 4.1 LLM 响应 `graph-problem-extraction/v2`

| 字段 | 要求 |
| --- | --- |
| `original_text` | 转录原题，供展示；保留文字、公式、量词措辞；标点与排版差异不影响验收 |
| `root` | 沿用 `definitions/facts/goals/children/uncertainties`；小问按题面顺序放在 `children`，局部条件只写在所属小问 |

响应不含 `family_id/match_status/match_reason`、出处、约定、题型候选、方法、答案、特征结论或 AST。

### 4.2 程序产物 `graph-stage-one-result/v2`

与同目录的 `frozen.json`、`validation.json`、`evaluation.json` 和账本共同提供：

- 题目、来源版本、候选版本、契约版本和运行 ID；
- 最终候选及其校验结果（记法、`scope_policy`）；
- `features`：特征值、条件分支、计算依据、依赖、`source_refs` 及诊断；
- 独立状态：原图复核、特征计算、独立验收、人工核对。

LLM 成功返回、题意数学合法、原图复核通过是不同状态。只有通过题意校验与原图复核的版本才能作为阶段②正常输入；允许携带已明确原因的 unknown 特征，但验收矩阵中的必需特征不能靠 unknown 通过。

## 5. 特征提取函数注册表

注册表的每个条目声明特征 ID、类别（结构特征或方法前提检查）、版本、输入依赖、输出类型、支持的数学结构、计算边界、学生措辞模板和关联知识。执行顺序由依赖决定；不得按题号写分支。本阶段只实现结构特征。

| 首批结构特征 | 程序计算与输出 | 关联知识示例 |
| --- | --- | --- |
| `quantifier`、`bound_vars`、`free_vars`、`goal` | 从绑定后的题意读取量词、变量身份，以及单一标量的 `find_range`、`find_minimum`、`find_maximum` 目标；保留原目标类型，不按字母名猜角色 | `quantifiers#universal`、`quantifiers#existential` |
| `domain`、`domain_kind` | 数学域、开闭端点、是否有界 | `quantifiers#domain` |
| `relation`、`normal_form` | 原关系与规范关系、严格性及变换记录；严格题使用 $>0$，不一律写成 $\ge0$ | `quadratic-inequality#definition` |
| `degree_in_bound`、`degree_in_goal` | 关于指定变量的次数；非多项式和缺少能力分别报告 | `quadratic-function-properties#definition` |
| `leading_coeff_in_bound`、`coefficients` | 关于指定变量的系数及是否含参；符号与零点分析属于阶段③ | — |
| `range_var_is_principal` | 由量词变量与各变量次数计算 | — |

特征记录包含 `feature_id/scope/target_ref/status/value/conditions/dependencies/source_refs/calculation/diagnostics/extractor_version`。`status` 区分 `known`、`conditional`、`unknown`；不能将 SymPy 的“不确定”转为 `false`。约分保留非零前提；首项系数含参时只标记“可能为零”。所有变形都经受限 AST，不把模型文本交给 `eval` 或 `sympify`。

## 6. 提取、复核与修复

1. 校验题源 manifest 与图片哈希，冻结契约、prompt、代码及 provider 配置。
2. 真实视觉 provider 提取题意；输入为题图、契约与通用表达规范，不发送金标、题意整理或解法。
3. 程序完成 JSON/Schema、数学记法和 `scope_policy` 检查；失败保留原始响应和诊断。
4. 原图 review 核对数学题意与转录遗漏；不能只读转录，也不能读取金标。
5. 必要时按诊断授权范围 repair，保存修复前后候选与采用事件。
6. 题意通过后执行特征注册表；特征缺口由程序修复或保留 unknown，不要求模型改写正确题意。
7. 无论成功失败都生成报告。

复用现有 `Budget`：内容调用最多 3 次、review 最多 3 次、总语义调用最多 6 次、网络尝试最多 12 次。记录每次调用的耗时、用量与网络尝试，报告汇总 P50 与最大值，用于决定产品模式下是否跳过或并行原图复核。

## 7. 测试与真实 LLM 验收

| 类型 | 输入与验证 | 网络要求 |
| --- | --- | --- |
| 确定性测试 | 人工题意及金标；校验记法、变量绑定、规范化、特征、转录比较和工作流机制 | 0 次调用 |
| 逐题真实集成 | 图片 → 真实提取及 review/repair → 特征 → 独立金标验收 | 每题均有本批次新发出的真实调用 |
| 录制回放 | 冻结的原始响应经当前代码重新解析、算特征和比较 | 禁止创建网络 provider |

`test_graph_stage_one_live.py` 按语料 manifest 为每题生成独立 pytest case（当前 Q01–Q11），每题 2 个独立样本。默认未设置 `RUN_LLM_INTEGRATION=1` 时跳过；明确启用后缺配置、缺图或没有新真实调用均失败。正式批次要求每个样本最终通过原图复核、题意语义、转录比较和必需特征检查；首轮结果与修复次数单独公开。失败后修复代码或 prompt 并新建批次，不从多个批次拼凑通过结果。

确定性回归覆盖：量词、开闭端点、严格性不被规范化吞掉；变量改名后的等价例；含参首项系数、零多项式、不同变量的次数和分母非零前提；`c∈ℝ` 写与不写的等价；转录忽略标点和排版、但拒绝改字改式；无效 JSON（修复请求带上解析错误与转义要求）、截断、超时、review 未确认、预算耗尽时报告仍能打开。多问另覆盖：兄弟小问互不可见、函数定义展开、同文条件各自定位、小问被压平或局部条件泄漏时语义失败、交换小问顺序时逐目标验收失败、验收必须覆盖全部目标。

## 8. 人可 debug 的产物

运行目录 `internal/solver-runs/graph-guided-stage-one/<run-id>/`（被 gitignore）：

```text
batch-manifest.json / batch-summary.json
index.html / sample-001.html / ... / _assets/
q05/sample-01/
  source.png / fixture/ / inputs/
  frozen.json / preflight.json
  workflow/ledger.json / workflow/calls/... / workflow/workflow-result.json
  candidates/
  candidate.json / validation.json
  features.json / feature-trace.json / feature-registry.json
  first-evaluation.json / evaluation.json
  stage-one-result.json / summary.json
  failure.json
```

`record` 导出的最小材料放在 `server/tests/solver/fixtures/graph-guided-stage-one/recorded/<run-id>/`，纳入版本管理，供录制测试和阶段②使用；不复制图片和 HTML。验收说明与人工核对记录随运行产物保存，稳定回放输入放入测试 fixture。

HTML 报告离线可开，单题页提供：题图与转录对照、题意条目、特征计算链及 unknown 原因、与金标的并排差异、逐次调用的完整请求和原始响应、失败定位与复现命令。

## 9. 文件落点

| 位置 | 内容 |
| --- | --- |
| `internal/schemas/graph-problem-extraction-v2.schema.json`、`graph-problem-review-v2.schema.json`、`graph-stage-one-result-v2.schema.json` | 模型响应、原图 review 与程序产物契约 |
| `internal/llm-prompts/graph-stage-one-*.md`、`graph-stage-one-expressions.json` | extract、review、repair 提示词与表达目录增补 |
| `server/shuxueshuo_server/graph_lesson/stage_one/` | `contracts.py`、`extraction.py`、`features.py`、`evaluation.py`、`runner.py`、`report.py`、`cli.py` |
| `server/tests/solver/fixtures/graph-guided-stage-one/` | Q01–Q11 题源、金标、manifest；`recorded/live-v2-20261017-02/` 为支持小问后真实批次的最小录制 |
| `server/tools/prepare_graph_stage_one_corpus.py` | 从原题段或自编题文准备合成题图，`--cases` 只渲染指定题，`--check` 校验来源与哈希 |
| `server/tests/solver/test_graph_stage_one_*.py` | `contracts`、`features`、`evaluation`、`workflow`、`batch`、`live`、`recorded`、`report` |

## 10. 运行命令

全部从 `server/` 运行；输出目录须为新目录。

```bash
# 全量真实批次（manifest 中全部题 × 2 样本）
RUN_LLM_INTEGRATION=1 uv run python -m shuxueshuo_server.graph_lesson.stage_one.cli run --case all --samples 2 --workers 3 --provider deepseek --output ../internal/solver-runs/graph-guided-stage-one/<run-id>

# 逐题独立 pytest case 的真实集成入口
RUN_LLM_INTEGRATION=1 GRAPH_STAGE_ONE_RUN_DIR=../internal/solver-runs/graph-guided-stage-one/<run-id> uv run pytest -n 3 -q tests/solver/test_graph_stage_one_live.py -m live_llm

# 导出最小录制、零网络回放、报告
uv run python -m shuxueshuo_server.graph_lesson.stage_one.cli record --batch ../internal/solver-runs/graph-guided-stage-one/<run-id> --output tests/solver/fixtures/graph-guided-stage-one/recorded/<run-id>
uv run python -m shuxueshuo_server.graph_lesson.stage_one.cli replay --batch tests/solver/fixtures/graph-guided-stage-one/recorded/<run-id> --case all --output ../internal/solver-runs/graph-guided-stage-one/<replay-id>
uv run python -m shuxueshuo_server.graph_lesson.stage_one.cli report --batch ../internal/solver-runs/graph-guided-stage-one/<run-id> --output ../internal/solver-runs/graph-guided-stage-one/<report-id>

# 语料检查与离线测试
uv run python tools/prepare_graph_stage_one_corpus.py --check
uv run pytest -q tests/solver/test_graph_stage_one_contracts.py tests/solver/test_graph_stage_one_features.py tests/solver/test_graph_stage_one_evaluation.py tests/solver/test_graph_stage_one_workflow.py tests/solver/test_graph_stage_one_batch.py tests/solver/test_graph_stage_one_report.py
uv run pytest -q tests/solver/test_graph_stage_one_recorded.py
```

录制测试禁止网络，逐份回放录制样本，并要求存在“单一冻结版本、覆盖 manifest 全部题目、每题 2 样本的完整成功批次”。失败样本的回放由工作流与批次测试用构造数据覆盖，不要求录制目录必须含真实失败。

## 11. 验收范围

契约、数学特征、真实提取／复核、录制回放及人工图文核对分别验收。合成题图只能验证对应输入，不代表真实扫描质量；阶段二至四和方法前提不由阶段一验收替代。录制哈希与原始失败保留在运行资产中，修改契约后重新核验。
