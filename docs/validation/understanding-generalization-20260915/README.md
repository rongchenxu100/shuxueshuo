# 等价表达、提示词与独立测试：2026-09-15

本轮把算式的安全拼写规范化移到代码，移除按样本字母、坐标及措辞编写的提示示例，并新增独立于原五题的合成题图集。本轮不扩大几何 schema，不部署服务，不清空数据。

## 规范化边界

`expression-spelling/v1` 使用 Python AST，只统一冗余括号、空白和数学幂记号。领域语义哈希和 Solver 投影比较共用该函数；原始 wire payload、source_text、revision_id、patch 基准及原图复核绑定保持精确。

- `(7*sqrt(13))/3` 与 `7*sqrt(13)/3` 相同；`x^3` 与 `x**3` 相同。
- 不约分、展开、交换操作数或计算根式，不把 `p/p` 当作 `1`，不把 `sqrt(p**2)` 当作 `p`。
- 保留分母分组、运算符、符号、作用域与边界。浮点字面量不经过浮点数往返转换，避免精度合并。
- 解析器有长度和节点上限，不求值、不执行代码；不支持的语法保持原样交给原校验器。
- 投影比较不再删除所有 `*`，因此能区分乘法、幂和名称拼接。仅旧路径字段的数字权重连写有局部适配，例如 `3PQ` → `3*PQ`。
- 不把数学表达式规范化用于转录文本；不自动认定近义改写或条件删除等价。

原五题金标文件没有修改，原有五题 revision/hash 固定值测试仍通过。

## 提示词与试验纪律

抽取／修复的 `DOMAIN_RULES` 与复核的 `REPRESENTATION_RULES` 放在同一模块。规则解释既有 schema，明示适用前提不能证明候选正确。没有题目 ID、图片哈希或金标分支，也没有把期望答案注入真实请求。

首个候选把 21 条压缩为 10 条，五题真实回归只有 1/5 完整通过，因此未采用这种压缩。第二个候选恢复通用契约说明的完整力度，只删除具体字母、坐标、字词改写及最少括号要求。五题作为开发回归集；新题的首次结果不用于调提示词。

## 独立集

位置：`server/tests/solver/fixtures/understanding-holdout-v1/`。

- `open-boundary` 与 `closed-boundary`：新编二次函数和普通距离和题，仅改变 `t>0` / `t>=0`。
- `sibling-local`：不同函数、字母和坐标，两个小问分别引入同名动点及参数，约束为 `r>0` / `r<4`。
- 题图为新排版的 PNG；观察数据是对应的人工合成转录，不冒充实际 OCR 服务输出。使用生产观察适配器、证据包、校验器、抽取服务和投影器，不使用 `_SourceIndependentValidator`。
- manifest 固定题图、观察和金标 SHA-256；`frozen-protocol.json` 保存首次真实调用前的实现快照。后续每个真实批次在调用前记录独立 protocol，输出目录不可重用。
- 正负对照覆盖冗余括号、幂／乘法、分母、根式、精度、坐标、边界、曲线归属、目标、作用域，以及 correction_required / uncertain 阻断。

最终五题真实批次 `deepseek-generalized-20260915-02`：**5/5 严格通过**，每题 1 次抽取 + 1 次 confirmed 复核。最终提示词相关离线复验 **206 项通过**；更广的抽取与 Context 回归 270 项通过。产品相关总回归曾为 324 通过、76 跳过；跳过的依赖环境测试未计为产品集成通过。

首次真实新题结果：**2/3 严格通过，3/3 抽取 accepted，3/3 投影通过**。失败的 open-boundary 输出 `T(t,0)`，省略单独的 `point_on_axis`；复核 confirmed，投影等价，但领域金标要求该原文关系显式存在，因此领域哈希不通过。保留失败，不放松门槛，也不补一条针对该题的提示。

最终版本新题复验 `understanding-holdout-20260915-02` 为 **3/3 严格通过**；首次和复验成绩分开报告，未拼接通过项。

这说明算式拼写规范化尚不涵盖等价事实表示。后续若规范化坐标与轴归属，需要独立契约、反例和新的未曝光测试集。本次三题已曝光，后续可作回归集，不能重复称作全新的独立验收。

## 测试发现的代码缺陷

- Context 将 `>=0` 切成 `>` 和 `=0`：改为最长运算符优先，覆盖全部六种关系运算符；参数下界读取同步处理 `>=`。
- 共享最值目标仅按局部拼写判断，错误提升兄弟小问的局部点：现要求端点与权重符号均在目标父作用域可见，才允许提升。
- 现有投影比较忽略部分目标内容和作用域差异；测试保持领域哈希与投影双门槛，不能只凭投影通过宣称题意一致。本轮没有扩大投影比较器的作用域语义改造。

## 重跑

离线：

```bash
cd server
uv run pytest -q tests/solver/test_expression_normalization.py tests/solver/test_understanding_holdout.py -m 'not live_llm' --tb=short
```

真实新题（使用新目录；开启开关后缺少密钥、题图或观察数据会失败）：

```bash
cd server
RUN_LLM_INTEGRATION=1 UNDERSTANDING_HOLDOUT_OUTPUT=/absolute/new-output \
  uv run pytest -q tests/solver/test_understanding_holdout.py -m live_llm --tb=short
```

真实模型只运行抽取和投影，没有调用下游求解、讲解或编译。数据库产品测试跳过不计作产品集成通过。完整成绩及归档见同目录 summary.json；旧的第一步 5/5 记录保留为历史基线，不能冒充本轮成绩。


## 归档核验

`evidence.tar.gz`（**不入库**，本地或带外保存；Git 忽略 `docs/validation/**/evidence.tar.gz`）包含两轮五题与两轮新题的请求、原始响应、复核产物、草稿、投影和差异报告；图片按 SHA-256 去重。`summary.json` 汇总各批次成绩并可入库。图片和 JSON 产物不改写，内容寻址引用保持原始审计含义；本归档不作为可恢复的业务 checkpoint。

本地已有归档时：

```bash
python3 docs/validation/understanding-generalization-20260915/verify.py
```

该命令核验归档及每个文件哈希、图片哈希、预算、批次成绩与最终抽取源码指纹，不调用模型或数据库。
