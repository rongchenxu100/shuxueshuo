# FP-T2 R0：实现与开发验收

日期：2026-11-11；实现基线：`c990af90`。本批从设计 §9 的恒等式探针和 A17 开始，已接通题给奇偶性 → 求参数 → 独立验证 → 共同课程。范围限于一个实参数、全实数域、关于输入至多二次且系数关于参数至多二次的多项式。T2 整型尚未收尾：含参域、高次、根式、分段、两参数以及 A15／A20 父任务不在本次交付内。

## 1. 已实现的合同

- 公共方法 `method-parity-parameter`，名称「奇偶性条件求参法」；比较系数实际调用已有 `skill-polynomial-coefficient-comparison`／`compare_polynomial_coefficients`。没有放宽旧能力的二次、全实数域或等式输入检查。
- 题给性质写作 `parity(f,odd|even|both|odd_only|even_only)`；声明次数写作 `degree(f)=2`。编译后按函数引用与词法作用域绑定，原参数和函数形参不会按字母名称猜测。T1 的待判断目标保持原义。
- 恒等式采用 `sp.Eq(..., evaluate=False)`；相同两边仍产生完整系数行和空方程组。普通奇／偶允许零函数；排他性质剔除全部系数同时为零的参数集合；明确声明次数时才加入对应首项非零条件。
- 参数数学保留原 AST、全部可见条件、完整参数集合和来源。独立验证以二次多项式唯一插值重建系数，再按所有精确根及开区间验证整个参数轴；不调用生产参数求解器或比较系数技能，不用有限参数抽样冒充证明。
- 原始 `find_value` 保留，新增 `parameter_value` 答案分支；唯一值同时返回数值和集合，多解、全体或空集完整返回集合。`find_range` 沿用集合答案。父目标 `f(m)` 不被改写为单独求参数。
- 题意整理保留原函数、已知奇偶性、完整域、参数限制及所求。已识别原文条件被删、性质被改、次数声明遗漏、额外添加原文没有的参数限制或存在未解决题意疑点时，不准入求参路线。超预算、含参分母、非实数全域等超范围结构返回能力缺口，不能输出“无解”。
- 保留单一方法的选法卡、5 张方法卡及完整推导。原式从源 AST 排版；集合干扰项去掉与正确答案相同者。结果发布核对目标类型和答案绑定，不能把求参结果当成函数值或其他任务。

核心代码：[参数数学](../server/shuxueshuo_server/graph_lesson/parity_parameter_math.py)、[运行与独立回验](../server/shuxueshuo_server/graph_lesson/stage_three/parity_parameter_runtime.py)、[教学投影](../server/shuxueshuo_server/graph_lesson/stage_three/parity_parameter_presentation.py)。

## 2. Prompt 改动

仅在共享受控数学记法目录 [problem-math-notation-expressions.json](../internal/llm-prompts/problem-math-notation-expressions.json) 增加一条 `function_property`：说明 `parity`、`degree` 的语法和普通奇／偶允许零函数的语义。没有修改系统、提取、复核或修复 prompt 的题型规则，没有加入 A17、答案、恒等式展开或系数求解流程。具体算法全部在代码中。

## 3. A17 真实照片验收

题源为用户《奇偶性 2.jpg》第 17 题，仓库[原样归档](../internal/senior-high/source-images/function-parity-planning-20261110/source-image-02.jpg)。整页上传后选框 `[110,630,1060,715]`，保留手写答案，不擦除笔迹、不重绘公式。独立金标来自印刷题干：

$$f(x)=x^2+(2-m)x+m^2+12\text{ 为偶函数},\qquad 2-m=0\Rightarrow m=2.$$

代回为 $f(x)=x^2+16$，满足原域与偶性。金标、人工候选和答案不传给 OCR、提取或复核服务。

通过带认证 Cookie 的 FastAPI TestClient 实际调用已配置的 Paddle OCR、DeepSeek 和隔离 PostgreSQL；登录短信使用测试实现。两次均为新上传及新的模型调用，非录制回放。

| 运行 | 搜题记录 | 结果 |
| --- | --- | --- |
| `initial` | `d5c8391e1fc2` | OCR、提取／复核和数学结果正确；题意整理投影缺失，最后一张卡因多元多项式误用 `all_coeffs` 编译失败。按失败保留 |
| `fixed` | `6e4c3857a6bd` | 提取与复核各 1 次、共 2 次网络尝试；题型为 `type-parity-parameter`，原题定位成功，独立结论 $m=2$，5 张卡全部 `interactive`；重新打开保持同一流和快照 |

首次验收期间补充了系数预算检查，其中误用只适用于一元多项式的 `all_coeffs`。改为多元支持的 `coeffs`，补齐读题投影，并在固定代码版本后重跑真实服务。没有放宽交互编译预算或把只读降级记作通过。

最终一次从选框提交到课程就绪约 30.156 秒，模型提取／复核流程约 17.967 秒，不含整页 OCR。仅记录此次耗时，不作性能保证。模型正确保留 `parity(f,even)`，未把手写的 `2` 写成已知条件。

全部原图裁片、整页 OCR、分题、模型请求与响应、调用账本、API 结果和文件哈希见[录制目录](../server/tests/search/fixtures/function-parity-parameter/)。初次失败没有被后续成功覆盖。

**实际限制：** 这是原开发照片验收，不是未见过的新照片留出。已验证课程 API、全部卡片可交互及重新打开；没有在浏览器逐步提交答案或验证账号学习进度保存，不能称为浏览器端完整学习流程验收。

## 4. 必要回归

本批按机制覆盖 A17、全部实数参数、奇／偶／两者兼有／排他性质、常数零函数、无解、多根、非有理二次根、原不等式／集合限制、次数退化和明确次数。另验证漏根证书被拒绝、禁用生产求解器仍可独立回验、源条件遗漏拒绝、同名兄弟作用域隔离、父目标不被替换、超预算与超范围拒绝。

| 检查 | 已记录结果 |
| --- | --- |
| 参数数学、源文准入、课程生成／导出／恢复、真实调用证据与离线回放 | 最终 53 项通过，包含空解／全解／零函数课程、作用域与疑点保护、原文条件双向核对 |
| 受影响旧能力：比较系数、定义域多项式、T1 数学与识别／执行、单调性求参、阶段三结果合同、记法及作用域 | 487 项通过（包含当时的 9 项 T2 识别检查） |
| 参数答案发布边界与阶段三结果合同 | 38 项通过，与前项有重叠，不重复累加 |
| 阶段二输入合同与函数求值运行合同 | 116 项通过；与当轮 51 项 T2 检查合跑，共 167 项通过。最后的双向来源核对另在上述 53 项中复验 |
| 新参数答案及共享记法展示 | 45 项 JavaScript 定向测试通过 |
| A17 静态作答／后退／恢复、数学排版、公开导出及知识图谱 | 最终 34 项通过；每个方法卡提交正确答案可继续，错误选项不推进，后退及录制恢复保持步骤，源式与代回公式可排版 |

照片离线回放明确禁止真实模型请求，不能代替第 3 节的真实调用。现有测试样例及 A17 都是开发／回归材料，未计作独立留出。本次没有运行整站测试。新增 Python 模块、录制工具及测试的 Ruff 检查通过；全改动文件检查的 6 条告警与 `c990af90` 基线一致（导入排序及一个已有未使用导入），无本批新增告警。

## 5. 专题与后续验收

A17 人工核对题源位于 [authoring record](../internal/senior-high/authored-courses/function-parity-t2-20261111/a17.json)，沿共同识别、执行、独立验证与导出流程构建；专题入口为 `/topics/function-parity/q17/`。最后一次来源核对修复后，39 道当前 authored 课程已全量重建，旧课程的身份兼容检查通过。课程、公开知识图谱和专题总览的 `--check` 均返回 `changed: 0`；公开导出共 160 个节点、137 道题、157 条路线、1310 个作答步骤，其中 A17 新增 8 步。此处的兼容检查不代替真实账号历史进度恢复验收。

仍待补：独立来源的系数退化／多解照片留出，以及浏览器逐步作答、后退、刷新和账号学习记录保存。未见材料不由开发样例换系数冒充。A15、A20 整题随 T3、T4 推进；本批不声称含参域或组合任务已完成。

从 `server/` 复现真实调用（输出目录必须全新，需有效 OCR／模型及隔离数据库配置）：

```sh
RUN_LLM_INTEGRATION=1 \
PRODUCT_TEST_DATA_DIR=/private/tmp/shuxueshuo-fm-review-20261109 \
PRODUCT_TEST_INSTANCE=fm-review-20261109 \
uv run python -m tools.record_function_parity_parameter_photos \
  --output /private/tmp/fp-t2-live-new-run
```

检查 `summary.json` 的来源定位、独立答案、交互状态与重新打开结果；进程退出码为零不等于验收通过。

定向回归：

```sh
PRODUCT_TEST_DATA_DIR=/private/tmp/shuxueshuo-fm-review-20261109 \
PRODUCT_TEST_INSTANCE=fm-review-20261109 \
uv run pytest -q tests/solver/test_graph_parity_parameter.py \
  tests/solver/test_graph_parity_parameter_recognition.py \
  tests/solver/test_graph_stage_three_parity_parameter.py \
  tests/search/test_function_parity_parameter_photo.py
```

本轮未提交、push 或部署；用户原有 `.gitignore` 改动保留。
