# 七题集成测试图片（2026-09-16）

本目录是七题批测的选定图片输入。所有图片均经逐张视觉检查；只做原像素裁剪或字节复制，没有重绘、生成式修补或从金标渲染题目。原始试卷、历史请求和测试结果保持原样。

| 题目 | 选定图片 | 处理及预期 |
| --- | --- | --- |
| 和平一模第25题 | [图片](tj-2026-heping-yimo-25.png) | 裁掉题干下方的手写解答与辅助图；保留少量不含答案的浅色笔迹 |
| 和平二模第25题 | [图片](tj-2026-heping-ermo-25.png) | 裁掉第24题及其图形、页侧信息 |
| 河西一模第25题 | [图片](tj-2026-hexi-yimo-25.png) | 裁掉第24题及其图形 |
| 南开一模第25题 | [图片](tj-2026-nankai-yimo-25.png) | 裁掉第24题、手机界面和页脚；保留原扫描透印，JPEG 解码后无损保存为 PNG |
| 西青一模第25题 | [图片](tj-2026-xiqing-yimo-25.png) | 使用用户新提供的无手写题图，逐字核对关键条件和小问；原文件已归档为 `internal/source-images/tj-2026-xiqing-yimo-25/source-user-clean-20260916.png` |
| k 倍四边形 | [图片](k-quad.png) | 原图字节不变；**用户故意不提供图1～4，测试模型能否发现缺图并触发后续阻断**，无需补图 |
| 函数与量词 | [图片](function-quantifiers.png) | 原图字节不变；没有缺图预期 |

[manifest.json](manifest.json) 记录来源路径、原图及选定图 SHA-256、尺寸、裁剪框和测试意图。裁剪框采用原图像素坐标 `[left, top, right, bottom]`，右、下边界不包含在内。

## 测试入口

`problem_understanding.batch_smoke.prepare_fixture()` 已切换到本目录，七题统一采用 **image-only，无 OCR 辅助**。旧整页 OCR 不再附入请求，避免裁剪后仍混入第24题或手写答案。生成的 `observation.json` 明确标为 `image_only_no_ocr`，只含图片尺寸与来源哈希，不冒充 OCR 结果，也不从 gold 复制题目文字。

缺图预期只存在于测试元数据与金标中，不发送给 LLM；新契约金标已迁移 K 题原有的局部 `k≥1` 遗漏 policy，缺图属于预期成功识别的输入缺陷。离线回放验证请求装配与阻断逻辑，不代表真实模型已识别成功。

当前七题入口默认使用 `problem-math-notation/v1` 数学字符串契约；旧版通过 `--contract problem-domain/v2` 显式回放，其他历史调用保留原契约。第一轮 DeepSeek 实测及原始响应见[验证报告](../../../../../../docs/validation/math-notation-deepseek-20260916/README.md)。图片与辅助文本输入均已变化，新旧通过率不能直接归因于模型或 prompt 改进。

在 `server` 目录执行以下命令可复现图片和运行离线检查：

```sh
uv run python ../tools/prepare_understanding_test_images.py
uv run pytest -q tests/solver/test_understanding_seven_live.py -m 'not live_llm'
```

准备图片不调用模型或 OCR 服务。真实集成测试仍由已有 `RUN_LLM_INTEGRATION=1` 开关控制，应使用新的输出目录，避免覆盖历史记录。
