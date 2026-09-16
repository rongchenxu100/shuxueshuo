# 简洁整题 IR：第二步验收（2026-09-15）

## 当前版本

独立 `problem_understanding` 包输出 `problem-domain/v2` 整题 root/children，直接携带匹配声明；不切换生产入口。已删除当前源码中的三对象首包、模型定义模板、来源覆盖和前缀命名要求。

代码只负责通用基础关系和名称/量纲解析，不按 KQuad、题名或 case ID 分派。人工金标中的本题具体展开只在测试夹具内。

## 原图证据与金标

来源构建：`6de57b87-fcd6-4977-8e99-2d3c4d7db01b`。

原图 SHA256：`7986e2751c53a4097599eb448623a9c87456179b2c0ce7e678f15623502d1038`。

- [原图](../../../server/tests/solver/fixtures/understanding-v2/k-quad/source.png)、实际 layout/text/formula/observation、三轮诊断返回及其 provenance 未重写。
- [evidence-freeze.json](evidence-freeze.json) 冻结修改前证据和两个旧真实实验。旧 gold 的哈希对应归档内容；当前 gold 是重新核对后的人工表达，不冒充原始证据。
- [previous-step2.zip](previous-step2.zip) 保存被替换的旧第二步包、测试、金标与 schema；[historical-designs.zip](historical-designs.zip) 保存旧设计全文。
- [新人工金标](../../../server/tests/solver/fixtures/understanding-v2/k-quad/gold.json) 与 [构造脚本](../../../server/tests/solver/fixtures/understanding-v2/author_gold.py) 可逐条核对。四图独立、图1 AECD 辅助交点独立、比例分支保留。
- 修正了旧 gold 的额外 `interior=true` 假设。没有把 □ 认定为平行四边形/正方形，没有补出四幅缺图，没有填写数学答案。

## 静态产物与尺寸

[canonical schema](schema.json)、[实际模型 schema](model-schema.json)、[操作表](operations.md)、[可执行 few-shot](example.json)、[人工候选渲染](gold-candidate.html)。所有 schema 来自 `contracts.py`，模型版仅损失为零的重复定义提取。

|项目|字符数|
|---|---:|
|模型 schema|15,039|
|完整 canonical schema|21,118|
|OCR 辅助|955|
|原始完整观察|29,629|
|few-shot|558|
|system|926|
|registry|2,455|
|完整文字提示|20,036|
|人工金标输出|4,380|

统计为 Unicode 字符，JSON 使用 ensure_ascii=False、紧凑分隔符，不包含图片 base64；实际图片字节与哈希另存。原图和完整观察没有为压缩而删除。

与 18,599 / 32,838 / 21,389 历史模型 schema 相比，当前分别缩小 19.14% / 54.20% / 29.69%。可运行 `python -m shuxueshuo_server.problem_understanding.measure` 重算，明细见 [measurements.json](measurements.json)。

## 离线结果

[offline-tests.txt](offline-tests.txt)：**149 passed, 6 skipped**。6 项为旧 suite 中未启用的真实模型测试，不计入本次真实验收。

执行套件：test_understanding_v2、test_understanding_authoring、test_problem_domain_recorded、test_problem_source_review、test_deepseek_vision。

覆盖新契约与六题人工表达、父子/兄弟名称边界、关系/分支/目标/量纲、修订与 patch、不可变产物、安全渲染、完整原图请求、实际 OCR 适配链、孤立分母、公式候选、单次调用审计和恢复去重。原有五题固定哈希、默认生产校验和投影回归保持原金标。

独立临时定义测试使用非 prompt 示例的人工变体，只证明编码/比较能力；不是额外真实 LLM 泛化验收。没有运行新契约五题真实投影，也没有启动九阶段构建。

## 唯一一次真实验收

运行目录：`internal/solver-runs/understanding-simplified-single-20260915`。

使用 deepseek-flash、enabled/low、json_object、非流式、16,384 tokens、300 秒，SDK 重试为 0。一次语义调用，最多两次受控网络尝试。开始前独占预留语义调用，并冻结请求、图片、schema、提示词、所有实现文件、金标和 registry。

不自动修复、不复核、不回退、不重跑直到成功。结果总是候选，source_reviewed=false、solver_ready=false。实际结果见本目录随后登记的 live-summary 和审计；离线通过不替代此真实门槛。

### 实际结论：未通过

[真实结果](live-summary.json)：一次语义/一次网络，75.477 秒。finish_reason=length；16,384 个 completion tokens 中 14,399 用于 reasoning，最终 JSON 在第（3）问 source_text 开头截断。解析失败，未运行金标对比，也未保存合法 IR 或 Solver 就绪证明。

可见片段还写入未经金标授权的 parallelogram 和 interior=true，不能通过补齐尾部就宣布成功。详情见 [失败诊断](live-diagnosis.md) 和 [完整审计](live-audit.zip)。

**本步代码和离线交付完成，单次真实抽取验收未通过，因此本步整体完成标准尚未满足。** 按明确预算停止，没有重跑或放宽金标。下一步不能把此结果当作已通过的新契约生产验收。
