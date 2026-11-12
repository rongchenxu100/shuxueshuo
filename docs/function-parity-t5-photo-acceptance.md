# FP-T5：原照片 OCR、模型与课程集成验收

日期：2026-11-12。重新上传用户提供的《奇偶性 1.jpg》《奇偶性 2.jpg》，调用真实 OCR、DeepSeek 提取及原图复核。范围为 A10、A14，共两道完整题、三个目标；两题本次首次调用均通过。原照片已参与开发，**不属于独立留出新照片**。

## 1. 结果

| 原题 | 核对结果 | 运行标识 | 课程检查 |
| --- | --- | --- | --- |
| A10 | 第一问 $0$，第二问 $1$ | `2203e185315d` | 两问均保留；13 个答题步骤，138 个数学字段 |
| A14 | $0$ | `9a70b0745ffe` | 7 个答题步骤，68 个数学字段 |

两题都完整经过提取、原图复核、原文来源绑定、T5 识别、数学执行、独立验证和课程生成；再次打开保持相同 stream 与 snapshot。实际运行产物经正式课程编译器检查，共 **20 个答题步骤、206 个数学字段、26 处数轴 SVG 渲染**通过。检查正确答案推进、错误选项不推进、后退与回放恢复；A10 的课包必须含两个目标及各自答案。

A10 的真实模型将四项显式和提取为 `finite_sum`，将第二问提取为两项显式项加索引 $3$ 至 $54$ 的和，代码直接消费这份结果，未改写成人工候选。A14 提取为 `find_value`，结果只证明所求整数点之和为零，不把函数当作恒零函数。定义域、奇性、对称轴及 A10 的已知函数值均与印刷题干相符，手写答案没有变成已知条件。

本轮共 **2 次整页上传、4 次模型语义调用、4 次网络尝试**：每题各一次提取和一次复核，没有修复调用、失败重试或候选替换。机器结果、完整目标、来源哈希、调用计数、导出身份及编译检查见 [summary.json](validation/function-parity-t5-20261112/summary.json)。

## 2. 真实调用与不可变证据

入口为 [record_function_symmetry_photos.py](../server/tools/record_function_symmetry_photos.py)。通过认证后的正常上传／选框／课程 API，先上传完整原页做方向识别、OCR 和分题，再框选完整印刷题。两页分别得到 11、8 个编号区域；本轮使用核对后的坐标选择 A10、A14，不把结果解释为自动分题已覆盖所有原题。

裁片保留手写痕迹，未重绘、擦除或向模型提供金标／authored candidate；数学金标仅用于调用结束后的校验。短信登录使用测试实现，搜索与课程记录使用隔离 PostgreSQL；OCR、模型提取和复核没有 mock。

完整录制位于 [function-symmetry/initial](../server/tests/search/fixtures/function-symmetry/initial/)，保留整页 OCR／分题、原裁片、模型输入图片、请求、原始响应、调用账本、API 结果和 snapshot，并登记逐文件 SHA-256。回归逐字回放这些模型响应并核对输入图片哈希，回放不计作新的真实调用。

真实运行目录为 `/private/tmp/fp-t5-live-20261112-initial`；实际运行证据与编译输入导出到 `/private/tmp/fp-t5-live-course-exports-20261112`。录制和机器摘要已保存到工作区。

## 3. 必要回归与验收边界

[test_function_symmetry_photo.py](../server/tests/search/test_function_symmetry_photo.py) **3 项通过，17.05 秒**：原图与全部调用的不可变性，以及两道完整题从真实转写回放至执行、独立验证、恢复、导出、课程判分和渲染。测试禁止调用实时模型，不能用新响应替换历史结果。

```sh
cd server
env PRODUCT_TEST_DATA_DIR=/private/tmp/shuxueshuo-fm-review-20261109 \
  PRODUCT_TEST_INSTANCE=fm-review-20261109 \
  .venv/bin/python -m pytest -q tests/search/test_function_symmetry_photo.py --tb=short
```

本次照片验收没有发现产品代码问题，仅新增验收入口、回归及证据；没有进一步修改 prompt 或记法目录。此前实现轮的 419 项回归见[实现记录](function-parity-t5-implementation-acceptance.md)，本轮没有无关地重跑全量测试。新增 Python 文件 Ruff 和 `git diff --check` 通过。

本轮覆盖真实拍题 API 与生产课程编译／作答状态机，未执行浏览器视觉检查、真实账号作答保存或部署。原两图没有独立的一般中心、两中心或局部关系题，这些分支仍只有代码机制测试，不能据此宣称已完成独立照片泛化验收。公开课程仍按约定等待 T2–T5 统一重建；本轮未重建、未提交、未 push。
