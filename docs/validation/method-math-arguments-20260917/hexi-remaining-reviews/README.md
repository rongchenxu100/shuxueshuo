# 河西一模 sample 2、3 故障审查索引

按[《LLM Sample 故障审查指南》](../../../llm-sample-failure-review-guide.md)完成其余两组数学参数样本的逐轮审查。每份报告包含三轮实际输入上下文、完整 Prompt 与 step JSON、所有步骤的 Scope/Goal 图、实际反馈、Plan 差异、retry 权限、错误代码来源及离线对照。原始失败证据保持不变。

| 样本 | 真实三轮首个阻断 | 修正表达后确认的情况 | 完整报告 |
|---|---|---|---|
| sample 2 | 逗号条件 → 逗号条件 → Point 坐标等式 | 三轮只修错误表达均可通过；第三轮还有 `∠CAD∈90°` 误改 | [逐轮分析](../hexi-sample-02-review/README.md) |
| sample 3 | 逗号条件 → Point 坐标等式 → 逗号条件 | 第一轮缺 C 的坐标状态；第二轮表达修正即通过；第三轮暴露模板物化的状态版本配置错误 | [逐轮分析](../hexi-sample-03-review/README.md) |

原始 6 轮共 **58 个 step 全部未执行**，没有规范计划、事务或 checkpoint。每轮仅一次 provider 调用，均正常返回完整 JSON。没有传输重试，也没有输出截断。

两个样本均未得到复合条件的 `∧` 表达样例；实际反馈只含当前首个错误，没有前次 Plan 或累计问题。sample 2 的 S2/S3 整份输入甚至逐字相同。`expected ∈, got =` 来自逗号误入多对象成员关系的解析分支，sample 2 S3 据此将角度等式改成成员关系，使表达进一步偏离。

sample 3 S3 的问题必须单独处理：实际能力目录允许直接引用能够由可见系数确定性物化的 Function 模板，但最终 BindingContext 在 `force_exact_source_versions=true` 时拒绝其缺失的 StateVersionId。旧对象引用与数学表达得到**完全相同的规范计划、异常和失败现场**，见[双编码对照](../hexi-sample-03-review/encoding-controls.json)。该结论限定于本次冻结输入与绑定目录；不能推广为所有历史旧入口都存在相同故障。显式增加 I 问曲线生成步骤能够绕过此路径，并未修复模板直读契约。

不能误判为错误的写法也已核实：sample 2 S1 的四处具名结果引用可由原规则安全归一；自由参数 c、可唯一确定时省略 `symbol_constraint`、sample 3 S2 的单值 many 参数均沿用既有规则通过。

## 离线验证与复现

共 14 组离线反事实运行：sample 2 为 5 组，sample 3 为 9 组；合计 6 次 accepted、6 次 blocked、2 次配置异常。accepted 运行同时检查预期答案并保存完整执行审计。另有参数解析探针及双编码规范计划比较。**新增模型调用为 0，未改生产代码，未改变原始真实成功率。**

- [sample 2 全部离线改动与结果](../hexi-sample-02-review/counterfactual-results.json)
- [sample 3 全部离线改动与结果](../hexi-sample-03-review/counterfactual-results.json)
- [证据、图示与交互核验记录](verification.json)
- [此前 sample 1 报告](../hexi-sample-01-review/README.md)

[analyze.py](analyze.py)复用 sample 1 的只读证据检查器，核对哈希、实际 provider messages、逐参数绑定与原诊断；[counterfactual.py](counterfactual.py)只向原编译/执行入口提供明确修改过的录制响应副本；[verify_controls.py](verify_controls.py)比较修表达后的数学计划与对象引用计划。录制器仅适配两种编码的文件加载入口，不修改编译、状态、retry 或执行规则。

在 `server` 目录运行，以下命令不请求模型：

```sh
uv run python ../docs/validation/method-math-arguments-20260917/hexi-remaining-reviews/analyze.py
uv run python ../docs/validation/method-math-arguments-20260917/hexi-remaining-reviews/counterfactual.py --sample 3 --attempt 3 --mode expression-only
uv run python ../docs/validation/method-math-arguments-20260917/hexi-remaining-reviews/counterfactual.py --sample 3 --attempt 3 --mode source-ref
uv run python ../docs/validation/method-math-arguments-20260917/hexi-remaining-reviews/verify_controls.py
```

上例复现第三轮配置错误的双编码对照；其他实验的 sample、attempt、mode 均保存在各自 result.json。首次旧编码离线驱动的录制文件名不匹配已保留为 `setup-error.initial.*`，修正加载器后重新得到有效对照；该驱动错误不计入产品失败。
