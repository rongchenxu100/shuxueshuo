# 函数量词条件题

原图为用户本轮上传的 1164×230 PNG，原始字节保存在 `source.png`，哈希见 `provenance.json`。

题意金标由图片人工核对后编写，不包含求解答案或模型返回。文字辅助 `observation.json` 是**人工转录夹具，不是真实 OCR 输出**；来源标注为 `human_transcription_not_ocr`，不伪造置信度或版面坐标。实际请求仍发送完整原图。

- 共用题设：`f(x)=x²+bx+c`、`g(x)=2x−1`。
- 第（1）问：对所有实数 x，f(x)≥g(x)；求 b²+c² 最小值。
- 第（2）问：存在 x₀∈[1,3]，f(x₀)≤g(x₀)；求实数 b 的范围，以 c 表示。
- 图片没有“如图”引用或缺图，本题不应新增 `missing_figure`。
- 当前 Solver registry 未覆盖这两个量词条件及含参范围目标，预期 `unmatched`，但完整保留 IR。

新增通用 `quantified_relation` 和 `find_range`；量词变量只在该 fact 内绑定，代码接受改名等价，不能泄露为另一小问的自由变量。现有 `curve_equation` 保存两个函数式，不新增题目专用 kind。

离线用例：`test_understanding_function_quantifiers.py`。真实用例：`test_understanding_seven_live.py::test_deepseek_seven_compact_ir_extraction[function-quantifiers]`。七题 CLI 与 pytest 共用 `smoke.run` 验收；开启 `RUN_LLM_INTEGRATION=1` 后缺依赖直接失败。
