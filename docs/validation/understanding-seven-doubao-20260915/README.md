# 七题豆包对照批次（2026-09-15）

按用户要求，将上次七题改用豆包进行一次完整对照。仍为独立简洁 IR 抽取测试，不进入旧生产抽取协调器或 Solver。

## 固定边界

- Provider：豆包；型号 `doubao-seed-2-1-turbo-260628`，端点 `https://ark.cn-beijing.volces.com/api/v3`。
- 与 DeepSeek 批次相同：图片字节、OCR/人工文字辅助、系统提示、few-shot、schema、registry、金标和允许遗漏政策。
- enabled/low、JSON object、非流式、16,384 tokens、300 秒、SDK 自动重试关闭。每题一次语义调用，最多两次受控网络尝试，并发 3。
- 显式 `--provider doubao`；不修改生产 Provider，不做自动供应商 fallback，不增加自动语义修复轮。
- 豆包适配器复用已有完整图片校验和非流式 Chat Completions 传输，审计中的 Provider、请求/响应 model 均记录实际值。避免复用旧豆包的流式首个 JSON 截取行为影响对照。

```sh
cd server
RUN_LLM_INTEGRATION=1 .venv/bin/python -m shuxueshuo_server.problem_understanding.batch_smoke \
  --provider doubao --case all --concurrency 3 \
  --output ../internal/solver-runs/understanding-seven-doubao-20260915
```

离线适配与七题回放检查：29 passed，7 个实时用例在离线命令中未开启。CLI 真实批次单独执行，不能用离线结果替代模型验收。Ruff 通过。

本批次已完成：**1/7 通过严格验收**；7 次语义调用、7 次网络尝试、117,177 tokens。七题都返回完整 JSON，全部以 stop 结束，七题声明的 matched/unmatched 与 family 均符合金标。题型声明正确并不替代 IR 校验或 Solver 就绪证明。

逐题核对确认：发送的 messages（含图片引用与文字）、schema、金标哈希、原图哈希、registry 及允许遗漏政策均与上次 DeepSeek 批次一致。执行期间实现哈希未变。原始调用和产物保存在 `internal/solver-runs/understanding-seven-doubao-20260915/`；此前 DeepSeek 批次保持不变。

## 逐题结果

|题目|豆包耗时（秒）|豆包结果|直接原因／边界|
|---|---:|---|---|
|和平一模|116.140|未通过|曲线 x 未声明、O 引用缺失、普通数字与长度的量纲关系不匹配。|
|和平二模|142.487|未通过|O'、A'、命名直线 l 不符合当前命名/几何字段格式；还填写了 schema 不允许的空 in_terms_of。|
|河西一模|169.896|未通过|C'、O'、D' 原名及含撇号线段/多边形写法不符合当前 schema。|
|南开一模|71.946|未通过|曲线 x 未声明，最值条件的量纲不匹配。|
|西青一模|107.877|未通过|x、m 未声明，最值条件的量纲不匹配。|
|k 倍四边形|137.412|**通过**|严格语义比较通过，未使用允许遗漏政策；四幅缺图全部保留，后续依然阻断等待用户确认。|
|新函数题|38.973|未通过|与 DeepSeek 同类问题：曲线 x/y 未显式声明，解析器不支持 f(x)、g(x) 的已定义函数引用。|

这列出的是校验器已发现的直接阻断，不是完整数学差异清单。六题 IR 未通过时没有跳过校验进入语义通过判定。

## 与上次 DeepSeek 的对照

|指标|DeepSeek|豆包|
|---|---:|---:|
|七题严格验收通过|0/7|1/7|
|完整 JSON|5/7|7/7|
|语义调用|7|7|
|网络尝试|8|7|
|累计 tokens|195,944|117,177|

豆包在本批次消除了输出截断，k 倍四边形从缺少 M 声明变为严格通过。新函数题两家都完整保留量词、[1,3] 闭区间、比较方向和所求，并正确 unmatched；两家都使用自然的函数引用写法，被当前转换器拒绝。

因此，下一项可验证的改进是受控函数引用展开、曲线自变量局部绑定、原名带撇号/命名直线支持，以及量纲常量和可选空数组的统一转换规则。不能把全部校验失败归因于图像识别，也不能因题型声明正确就宣称数学语义通过。本轮仅完成供应商对照，没有根据结果改动提示词、数学校验或金标，没有追加重跑。

机器可读逐题报告及输入一致性核对见 [results.json](results.json)。未执行独立原图复核、Solver 投影、求解或部署。
