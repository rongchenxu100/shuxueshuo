# FR-T1 A2 分式换元：开发与验收记录

日期：2026-11-01。复用换元法、五种方法的预连线选法图、四张推导卡与共同课程执行器。本批没有新增方法、技能或判断节点。

## 声明范围

- 已知 `f((ax+b)/(cx+d))=R(x)`；系数为固定有理数，`c≠0`、`ad−bc≠0`。
- 右式为有理式，约分后分子、分母次数均不超过 2。保留原始 AST 中每一个除法的限制，包括嵌套分式、约分消去的因子和零系数乘上的分式。
- 原除数的分子次数不超过 2，其实零点必须为有理数；原变量总禁取点不超过 4 个。无实零点的二次除数可用；实无理禁取点、高次分式、未知参数、附加区间约束和退化输入暂不准入。
- 沿用总 AST 128 节点、深度 16、系数分子／分母 64 位预算；中间分子、分母次数不超过 4，幂仅支持 1、2，以及已知非零常数的 0 次幂。
- 不扩大 A0/A1 的输入声明；一次式或根式输入中的额外变量分母仍按原边界拒绝。

设原关系禁取集合为 E，则源域为 `ℝ\E`。非退化一次分式在去掉极点后是一一对应：像集首先排除 `a/c`，再排除 E 中其余点对应的函数输入值。反解为 `x=(dt−b)/(a−ct)`。独立验证重新读取原始语法，核验恒等式、完整像集及反解覆盖；候选答案或反解新增禁取点均判失败。

即使右式约分后是常数，原关系没有给出的函数值仍不能任意补齐。若明确请求实数全域规则，报告范围外信息不足。

## 题源与课程

题目：已知 `f(x/(x+1))=x−1`，求 `f(x)` 的解析式。

原题对应用户图 3，第 91 页例 5 变式 1，解析续见第 92 页。独立答案：

`f(x)=(2x−1)/(1−x)，x≠1`。

- 题目 ID：`function-representations-b05-v1`。
- 页面：`/topics/function-representations/variant01/`。
- 题源记录：`internal/senior-high/authored-courses/function-formula-a2-20261101/b05-v1.json`。
- 执行记录：`internal/solver-runs/function-formula-a2-20261101/b05-v1/`。
- 运行 ID：`bf29aee60ef041d8a5332de2be732b86`。
- 证据：`site/data/graph-walk/function-representations-b05-v1.evidence.json`。

通过显式 `authored_topic` 入口构建，题意、原图及规范题源文件均绑定哈希；没有伪造学生上传、模型原图复核或未见照片验收。构建使用已有独立测试数据库；第一次因数据库未启动失败的记录保留在同级 `b05-v1-db-unavailable/`，恢复后完成新运行。

## 学生交互

1. 保留“已知复合函数的解析式 → 换元法／配凑法”的预连线图，点换元法继续。配凑路线仍显示适用但步骤暂未开放。
2. “换元后，哪些数不能取”：给出原式 `x≠−1` 与 `t=x/(x+1)`，学生选择 `t≠1`；解释 `t=1−1/(x+1)`。
3. “用新变量表示原变量”：选择 `x=t/(1−t)`，完整推导中列出乘分母、移项和反解。
4. 代入右式，选择 `f(t)=(2t−1)/(1−t)`。
5. “写出完整答案”：补选 `x≠1`；选项中的 `x≠−1` 对应混淆原变量限制。数轴随选择显示不同位置的空心点，确认后保留完整公式与绿色数轴。额外原分母产生多个禁取值时，每个点都保留。

## 必要验证

- 79 项 Python 单元测试通过，覆盖 A0/A1、A2 恒等与范围、零／常量右式、分数系数、约分及嵌套分母、拒绝越界输入、独立验证拒绝篡改、字母改名、原题绑定、卡片契约和评分。未运行数据库集成测试或全量测试。
- 13 项 Node 单元测试通过，覆盖新题及既有题的评分、回放、共同拍题投影、空心点草稿／完成态、独立专题及方法分组。
- 新题完成共同执行器、独立验证和课包导出。本地逐步作答完成 7 步，答案卡的数轴在 1 处为空心点；截图见 `internal/review-analysis/function-formula-a2-20261101/fractional-answer-completed.png`。
- 专题共 5 题，公共图谱仍为 111 节点、367 条边。旧题身份、旧证据与学习进度兼容保留。

真实照片与未见照片 S7 仍单独待补，本批不计作新的真实拍题模型验收。尚未部署。下一批为 A3 配凑法，代表题 B05-v3。

复现单元测试：

```sh
cd server
uv run pytest -q tests/solver/test_graph_function_formula.py tests/solver/test_graph_function_formula_affine.py tests/solver/test_graph_function_formula_rational.py -m 'not stage_three_db'
```

```sh
node --test tools/tests/graph-walk-function-formula.test.mjs tools/tests/function-representations-topic.test.mjs
```
