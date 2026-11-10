# FM-T4：真实照片 OCR 与课程集成验收

日期：2026-11-10。承接 [T4 开发设计](function-monotonicity-parameter-problem-type-design.md)。**8 道题最终全部通过；首轮通过 4 道，修复代码后复测其余题。** 本轮没有修改 prompt，也没有提交、push 或部署生产环境。

## 1. 输入与验收范围

输入为[题源照片 1、2](../internal/senior-high/source-images/function-monotonicity-planning-20261104/manifest.json)，保留原始印刷题面和手写批注，独立按印刷条件计算金标。不是用人工题意 JSON 代替模型输入。

真实调用依次经过：鉴权上传 `POST /api/search/pages` → OCR、方向校正及分题 → `POST /api/search/problems` 提交核对后的裁框 → DeepSeek 提取／复核 → 题型判定、原文定位、数学求解与验证 → 课程 start／snapshot → 重开同一课程。验证了交互状态、精确答案及重开后的 stream、快照一致性。

两张整页照片均识别出 9 个区域，方向为正向；逐题采用人工核对的裁框，因此不声称自动分题已覆盖所有题目。三轮共 **6 次整页上传、15 次题目识别、31 次语义模型调用／31 次模型网络请求**，包含所有失败和复测。最终采用的 8 份成功记录均为 extract → review 两次调用。

“新照片验收”在本记录中指**归档开发题源原照片上的全新 OCR／模型调用与后端 API 验收**，不是旧模型响应回放，也不是新拍摄角度、光照或未见过的独立照片。本轮未操作浏览器上传和拖动裁框；课程快照恢复也不等于学生答题进度提交。

## 2. 逐题结果

时间从创建裁图题开始，不含整页上传／OCR。以下为每题最终成功调用的耗时。

| 题目 | 结构与易错点 | 独立金标 | 识别完成 | 课程就绪 |
| --- | --- | --- | ---: | ---: |
| A05 | 二次函数对称轴与区间 | $m\in(-\infty,2]$ | 36.7 秒 | 44.6 秒 |
| A06 | 一次／二次分段；原式为 $a/2$ | $a\in(-2,\frac45]$ | 52.3 秒 | 63.2 秒 |
| A08 | 差商负、分段函数、手写干扰 | $a\in(0,\frac53]$ | 73.0 秒 | 85.1 秒 |
| A09 | 半无限区间递减 | $a\in[5,+\infty)$ | 34.6 秒 | 45.1 秒 |
| A10 | 反比例／对勾分支及接缝 | $a\in[-1,-\frac12]$ | 49.8 秒 | 60.1 秒 |
| A11 | 二次项退化为一次，保留 $a=0$ | $a\in(-\infty,0]$ | 53.0 秒 | 61.7 秒 |
| A13 | 差商负，整段根式有定义 | $a\in[\frac12,1]$ | 65.6 秒 | 74.3 秒 |
| A17 | 差积负、一次／反比例分段 | $a\in[\frac16,\frac13)$ | 41.9 秒 | 51.3 秒 |

8 题均完成原文定位、课程执行、交互生成和重开恢复。课程就绪时间为 44.6–85.1 秒，中位数 60.9 秒；本轮不宣称速度问题已经解决。A10、A11、A13 的结果按印刷题意核对，没有照抄照片里的手写答案。

## 3. 发现的问题与代码修复

1. **完整量词条件的解析。** 支持同域双变量量词、不同点守卫和蕴含式；也支持内层变量域排除外层变量的写法。保留全称／存在量词和逻辑方向，不把守卫丢成无条件事实。缺少不同点要求、不同量词域、非严格符号、额外排除点等仍不误判为严格单调性。
2. **由代码理解差商／差积。** 模型只提供函数定义、原始量词条件和求参目标时，代码验证并推导增减要求；不要求模型额外填写特定题型 metadata，不修改原始候选，不丢弃附加参数条件。
3. **修复权限。** 对复核明确指出缺少量词的 `basis.statement`，允许在原关系完全不变的前提下补全全称量词和守卫；不能借此改不等号、目标、方向或相邻小问。
4. **课程展示衔接。** 读题卡和推导卡读取代码解析后的要求；展示差式前先解开量词外层。原文定位兼容题面 `y=…` 与内部 `f(x)=…`，以及 `x1`、`x_1`、`x_{1}` 的书写差异，避免误吞分式的右花括号。

这些修复均在代码中完成，本轮未向 prompt 添加 T4 题型解释、题号或答案。

## 4. 原始失败与证据保留

[录制目录](../server/tests/search/fixtures/function-monotonicity-parameter/)保存每次真实调用的源图摘要、裁框、原始 PNG、模型实际输入图、请求／响应、识别结果、API 状态和成功课程快照。`recording.json` 绑定文件及响应文本的 SHA-256；[整页上传证据](../server/tests/search/fixtures/function-monotonicity-parameter/uploads/)单独保留。

| 保留记录 | 当时结果 |
| --- | --- |
| `a08-initial` | 分组量词／蕴含式解析缺口，提取后失败 |
| `a11-initial` | 已复核，原题 `y=…` 未定位到内部函数定义，课程失败 |
| `a13-initial` | 补全量词的修复被旧权限规则拒绝，预算耗尽 |
| `a17-initial` | 已复核，缺少代码对原始量词事实的题型推导，报告未覆盖 |
| `a08-confirmation` | 手写批注引发需确认，且候选误读首项负号；未复核、未生成课程 |
| `a13-source-card` | 已复核，完整量词及下标写法在读题／推导卡报错 |
| `a17-card-error` | 已复核，课程状态 API 仍访问缺失的旧 metadata，抛出 KeyError |

A17 第二轮在读取状态时发生异常，保存的是 `api-error.json` 和已落盘识别记录，未伪造成功 HTTP 响应。A08 最后缩紧裁框以排除邻题批注，保留完整印刷题及其上的手写内容；没有修改像素或人工纠正候选后当作 OCR 成功。其两次失败均保留，不能从最后一次通过推断“带批注照片识别稳定”。

## 5. 必要回归与复现

- **241 项单元测试通过**：T4 数学与同结构变式、原始量词推导、共享记号解析、修复权限、根式／无穷端点。
- **22 项 T4 拍题测试通过**：8 题真实录制重放与独立金标、6 项鉴权课程 API 场景（含原先导致展示失败的两份候选）、7 份历史失败保留、整页上传证据检查。录制重放不再调用模型，不能与上述 31 次真实调用混计。
- **30 项既有 T1／T2／T3 照片录制回归通过**，包含历史失败和 T3 局部单调区间保护；本轮该组未重跑课程 API。
- **14 项 T4 前端课程测试通过**：八题逐步判分、公式渲染、恢复、差式卡和参数分类卡；仅刷新这 8 道 T4 生成物并逐一检查一致性，没有重建全站课程。
- 本轮修改的 12 个 Python 文件 Ruff 通过；`git diff --check` 通过。

共享 `test_math_notation.py::test_schema_documents_each_goal_and_uncertainty_kind` 有既存的 Schema 枚举／描述断言不适配（HEAD 已包含 `match_range`，测试期望未更新）。首次运行暴露后已确认不是本轮引入，定向回归排除此一项；不将本记录写成全库测试通过。

使用已安装、已迁移的隔离 PostgreSQL 实例 `fm-review-20261109`，端口 55439，目录 `/private/tmp/shuxueshuo-fm-review-20261109`。验收后已停止该实例；日常实例未迁移或重启。

```sh
# 在 server/ 目录执行；先启动既有隔离实例
./.venv/bin/python -m shuxueshuo_server.product.admin.cli \
  --mode local --data-dir /private/tmp/shuxueshuo-fm-review-20261109 \
  --instance fm-review-20261109 db-start

# 全新真实模型调用（有费用）；输出目录必须不存在
PRODUCT_TEST_DATA_DIR=/private/tmp/shuxueshuo-fm-review-20261109 \
PRODUCT_TEST_INSTANCE=fm-review-20261109 RUN_LLM_INTEGRATION=1 \
./.venv/bin/python -m tools.record_function_monotonicity_parameter_photos \
  --output /private/tmp/fm-t4-live-new-run

# 录制回归及真实本地课程 API，无新模型调用
PRODUCT_TEST_DATA_DIR=/private/tmp/shuxueshuo-fm-review-20261109 \
PRODUCT_TEST_INSTANCE=fm-review-20261109 \
./.venv/bin/python -m pytest -q \
  tests/search/test_function_monotonicity_parameter_photo.py --tb=line

./.venv/bin/python -m shuxueshuo_server.product.admin.cli \
  --mode local --data-dir /private/tmp/shuxueshuo-fm-review-20261109 \
  --instance fm-review-20261109 db-stop
```

真实调用脚本默认覆盖全部 8 题；可用 `--cases a08 a13 a17` 限定复测。图片、失败和响应录制属于本仓库开发验收数据，不包含测试数据库配置、登录凭证或模型密钥。
