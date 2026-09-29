# AM-GM 配对预算归属修正（2026-09-29）

上轮把最小值 effect 内部预算误认为调用方共享预算，测试也固定了错误行为。此次采用保留现有预算划分的修法：

- `verify_local_application` 仅读取调用方的 limits，模板预筛和关系证明分别使用配对私有预算。预筛预算耗尽时退出模板循环；外层配对循环允许尝试下一配对。
- `verify_upper_effect` 和成功 effect 之后的正性检查使用调用方预算。此处共享额度耗尽必须上报，不能因另一配对重新开始。
- 显式证书回放仍只检查所记录的配对，所有错误直接上报。

没有提高预算上限，也没有把所有配对改为共用一个总账。候选数仍受现有 128 对上限限制；配对私有工作不记为调用方总账的消耗，不能宣称已有跨配对统一运算上限。

## 真实预算复现

在 `a>0, b>0` 下，目标表达式为 `a+1/a`，候选下界为 `2`。提交关系中包含 `(a+b)^3+(a+2*b)^3>0`，使该复杂配对先于原目标配对进入检查。测试把 reductions 限额收紧到 16：

1. 直接检查第一配对，真实触发 `proof_limit: reductions budget exhausted`，调用方计数仍为空。
2. 修复前，同样输入的 `verify_application` 在第一配对报错，回归测试失败。
3. 修复后，继续检查并选中 `a` 与 `1/a`，证明目标下界为 2，生成证书且独立回放通过。

此用例不 mock 候选顺序、数学证明或预算异常。它是小额度下的确定性复现，不表示已经发现默认限额下的生产失败输入。

另用真实调用方预算耗尽测试最小值和最大值入口：只观察 effect 调用次数，不伪造证明或错误；两种路径都必须只尝试一次并上报 `proof_search_exhausted`。原配对 mock 测试纠正为私有额度耗尽允许继续，并保留证书回放失败不得跳过的断言。

## 验证

针对性测试：8 passed。回归命令（工作目录 `server/`）：

```sh
.venv/bin/python -m pytest -q tests/solver/test_scoped_proof_search_stage_f3.py tests/solver/test_basic_inequality_stage5c.py tests/solver/test_basic_inequality_stage5a.py tests/solver/test_scoped_proof_search_stage_e.py
```

首轮结果为 145 passed、1 failed（137.93 秒），保留在 `regression-initial.log`。失败的是阶段 E 的旧测试：它也在私有 effect 入口伪造“全局耗尽”。已改为完成真实 effect 后消耗调用方实际额度，由随后的正性请求触发真实 `proof_search_exhausted`，并断言不再尝试其他配对。

修正旧测试后，相关 9 项重点复验全部通过（1.10 秒），见 `focused-final.log`。生产代码在两轮之间未变化；只修正该测试，没有再次重复运行已通过的 145 项。两轮合计覆盖上述 146 项，重点复验有重叠。源码哈希见 `implementation-sha256.json`。不调用 LLM，不浏览页面，不提交代码。
