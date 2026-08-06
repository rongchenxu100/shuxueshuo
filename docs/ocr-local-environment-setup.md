# OCR 本地环境安装

## 1. 目的

Track F2 会接入本地版面检测、印刷文字 OCR 和公式识别。正式开发前需要准备一套可重复的
CPU 推理环境，但不应把 Paddle 依赖直接装进当前 solver 的 `server/.venv`。

本地采用两套环境：

```text
server/.venv       solver 开发、普通 pytest、recorded provider
server/.venv-ocr   PaddleX / PaddleOCR 真实本地推理与 smoke
```

这样做有三个原因：

- Paddle wheel 和模型依赖较大，并且具有平台差异；
- F2 离线测试必须能在不下载模型、不调用真实 OCR 的环境中运行；
- OCR 环境损坏时可以整体重建，不影响现有 solver 环境。

F2 的开发顺序固定为：

```text
默认 .venv 中用 recorded response 完成 adapter 和 SourceObservation 测试
→ .venv-ocr 中运行五题真实 provider smoke
→ 固化 provider/model/version 与 recorded artifact
```

## 2. 当前本地基线

本文档基于 2026-08-05 的本地开发机：

```text
OS              macOS
CPU             Apple Silicon / arm64
Python          3.11
Package manager uv
Inference       CPU
PaddlePaddle    3.3.0
PaddleOCR       3.7.0 + doc-parser extra
Layout model    PP-DocLayout-S
```

PaddleOCR 3.x 要求 PaddlePaddle 3.0 或更高版本。当前 macOS 官方安装页只提供 CPU 路径，
并支持 Apple Silicon arm64。参考：

- [PaddlePaddle macOS PIP 安装](https://www.paddlepaddle.org.cn/documentation/docs/en/install/pip/macos-pip_en.html)
- [PaddleOCR 安装](https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/installation.html)
- [PaddleOCR 快速开始](https://paddlepaddle.github.io/PaddleOCR/main/en/quick_start.html)
- [PP-DocLayout 模型说明](https://paddlepaddle.github.io/PaddleX/latest/en/module_usage/tutorials/ocr_modules/layout_detection.html)
- [uv 独立环境](https://docs.astral.sh/uv/pip/environments/)

不要在 Intel `x86_64` Mac 上照搬本文档。先改用受支持的 Linux CPU 环境，或者等后续
CentOS 部署文档，不要在本地自行编译 Paddle。

## 3. 安装前检查

从仓库根目录执行：

```bash
uname -m
uv --version
cd server
uv run python -c "import platform,sys; print(sys.version); print(platform.machine()); print(platform.architecture()[0])"
```

预期满足：

```text
machine      arm64
Python       3.11.x
architecture 64bit
```

确认磁盘至少预留 8 GB。Python 包本身不会全部占满这些空间，但首次运行 layout、OCR 和公式模型时
会下载权重并写入 PaddleX 用户缓存。

## 4. 创建独立 uv 环境

以下命令均从 `server/` 执行；后续章节如无特别说明，也保持在这个目录：

```bash
uv venv --python 3.11 .venv-ocr
uv pip install \
  --python .venv-ocr/bin/python \
  -e . \
  "pytest>=8" \
  "setuptools==83.0.0"
```

不要激活环境也可以继续安装；`--python` 明确指定目标解释器，避免误装进 `server/.venv`。
Paddle 3.3.0 会在 import 阶段加载 `setuptools`；uv 创建的最小 venv 不保证预装它，因此这里将其
作为运行时依赖显式固定。缺少时会报 `ModuleNotFoundError: No module named 'setuptools'`。

## 5. 安装 PaddlePaddle CPU

PaddlePaddle 的 macOS CPU wheel 使用官方稳定索引：

```bash
uv pip install \
  --python .venv-ocr/bin/python \
  --index https://www.paddlepaddle.org.cn/packages/stable/cpu/ \
  "paddlepaddle==3.3.0"
```

这里的 `--index` 是附加索引，PyPI 仍用于解析普通依赖。不要安装 `paddlepaddle-gpu`；macOS
本地路径只使用 CPU。

验证框架：

```bash
.venv-ocr/bin/python -c "import paddle; print(paddle.__version__); paddle.utils.run_check()"
```

预期包含：

```text
3.3.0
PaddlePaddle is installed successfully!
```

## 6. 安装 PaddleOCR 文档解析依赖

F2 不只需要普通文字 OCR，还需要 layout 和公式模块，因此安装 `doc-parser` extra，而不是
仅安装最小 `paddleocr`：

```bash
uv pip install \
  --python .venv-ocr/bin/python \
  "paddleocr[doc-parser]==3.7.0"
```

验证包和入口：

```bash
.venv-ocr/bin/python -c "from importlib.metadata import version; print('paddleocr', version('paddleocr')); print('paddlex', version('paddlex'))"
.venv-ocr/bin/python -c "from paddleocr import PaddleOCR, FormulaRecognition; from paddlex import create_model; print('OCR imports OK')"
.venv-ocr/bin/paddleocr --help
```

此时只验证 Python 环境，不要求模型已经下载。

## 7. 首次模型下载与 layout smoke

PaddleX 默认从 Hugging Face 下载官方模型。国内网络访问不稳定时，显式使用 BOS：

```bash
export PADDLE_PDX_MODEL_SOURCE=bos
```

先只预热 F2 默认的轻量版面模型 `PP-DocLayout-S`：

```bash
PADDLE_PDX_MODEL_SOURCE=bos .venv-ocr/bin/python - <<'PY'
from pathlib import Path

from paddlex import create_model

image = Path(
    "../internal/source-images/tj-2026-hexi-yimo-25/source-page-01.png"
)
assert image.is_file(), image

model = create_model(model_name="PP-DocLayout-S")
results = list(model.predict(str(image), batch_size=1, layout_nms=True))
assert results, "PP-DocLayout-S returned no page result"
print("PP-DocLayout-S smoke OK; page_results=", len(results))
PY
```

第一次运行会下载模型，耗时明显高于后续运行。模型通常缓存在用户目录下的 `.paddlex` 中；
该目录属于本机运行时缓存，不进入 Git，也不能作为 F2 source authority。

## 8. OCR smoke

模型预热完成后，对同一张五题 corpus 图片运行普通 OCR：

```bash
PADDLE_PDX_MODEL_SOURCE=bos .venv-ocr/bin/paddleocr ocr \
  -i ../internal/source-images/tj-2026-hexi-yimo-25/source-page-01.png \
  --device cpu \
  --use_doc_orientation_classify False \
  --use_doc_unwarping False \
  --use_textline_orientation False
```

这一步只确认检测和识别模型可以执行，不把终端输出直接当作 F2 的 `SourceObservation`。
F2 adapter 必须把厂商结果归一化后再写 recorded artifact。

公式模型由 F2 worker 对 layout/OCR 选出的公式 crop 批量调用。当前本地已缓存
`PP-FormulaNet_plus-M`；不要把整张题目页直接送入单公式识别模型来判断环境是否正常。

完整五题 smoke 会同时验证 layout、普通 OCR、公式 OCR、模型复用、recorded replay 和 review pack：

```bash
PADDLE_PDX_MODEL_SOURCE=bos \
.venv-ocr/bin/python -m shuxueshuo_server.solver.extraction.f2_smoke \
  --case all \
  --output-dir ../internal/solver-runs/problem-extraction/f2-smoke
```

不加载 Paddle 的确定性重放：

```bash
uv run python -m shuxueshuo_server.solver.extraction.f2_smoke \
  --case all \
  --replay-provider-records ../internal/solver-runs/problem-extraction/f2-smoke \
  --output-dir ../internal/solver-runs/problem-extraction/f2-replay
```

## 9. 本地验收清单

开始 F2 真实 provider 接线前应满足：

```text
[ ] uname -m 为 arm64
[ ] .venv-ocr 使用 Python 3.11
[ ] paddle.__version__ 为 3.3.0
[ ] paddle.utils.run_check() 成功
[ ] paddleocr 为 3.7.0
[ ] PaddleOCR、FormulaRecognition 和 paddlex.create_model 可导入
[ ] PP-DocLayout-S 在河西图片上返回至少一个 page result
[ ] 普通 OCR 命令成功结束
[ ] PP-FormulaNet_plus-M 由公式 crop smoke 成功调用
[ ] 五题 smoke 中 layout/text/formula 初始化计数均为 1
[ ] 五题 SourceObservation、recorded replay 和 review pack 均成功
[ ] 默认 server/.venv 的 solver 测试未因 OCR 环境改变
```

最后执行普通环境回归，确认环境隔离：

```bash
uv run pytest \
  tests/solver/test_problem_extraction_observations.py \
  tests/solver/test_problem_region_proposals.py \
  tests/solver/test_problem_extraction_formula.py \
  tests/solver/test_problem_extraction_handwriting.py \
  tests/solver/test_problem_extraction_observation_context.py \
  tests/solver/test_problem_extraction_review_pack.py \
  tests/solver/test_problem_extraction_source_fingerprint.py \
  tests/solver/test_problem_extraction_context.py \
  tests/solver/test_problem_extraction_gold_corpus.py -q
```

## 10. 常见问题

### 找不到适用于当前平台的 Paddle wheel

重新确认：

```bash
uname -m
.venv-ocr/bin/python -c "import platform; print(platform.machine())"
```

两者都应为 `arm64`。不要用 Rosetta 下的 x86 Python。删除错误环境后，用 `uv venv --python 3.11`
重新创建。

### `Library not loaded: libomp.dylib`

只在实际出现该错误时安装 OpenMP runtime：

```bash
brew install libomp
```

不要通过设置 `KMP_DUPLICATE_LIB_OK=TRUE` 长期绕过动态库冲突；这会掩盖环境中重复 OpenMP runtime。

### `No ccache found`

这是 Paddle 检查 C++ extension 工具链时产生的 warning。F2 只加载官方推理 wheel，不编译自定义
C++ extension，因此无需为该 warning 安装 `ccache`，也不影响 `paddle.utils.run_check()`。

### Hugging Face 下载失败

切换官方 BOS 模型源后重试：

```bash
export PADDLE_PDX_MODEL_SOURCE=bos
```

该变量只决定模型下载源，不改变模型身份。F2 recorded artifact仍必须记录准确的 model name、
PaddleOCR/PaddleX版本和权重摘要。

### 第一次运行很慢

首次运行包含模型下载和初始化，不能用于稳定 latency 基线。至少运行两次；F2 只记录第二次起的
warm latency，同时单独记录 cold-start latency。

### 内存或 CPU 占用过高

F2 本地基线先使用 `PP-DocLayout-S`，一次处理一页，`batch_size=1`。不要为了本地 smoke 直接切换
`PP-DocLayout-L` 或完整 PP-StructureV3 全模块流水线。

## 11. 重建与升级规则

OCR 环境可以整体删除后重建：

```bash
rm -rf .venv-ocr
```

升级 PaddlePaddle、PaddleOCR、PaddleX 或模型时，不允许只改本机环境。必须同时：

1. 更新本文档的固定版本；
2. 重新运行五题真实 OCR smoke；
3. 重新生成对应 recorded provider artifacts；
4. 比较 SourceObservation semantic diff；
5. 更新 extraction dependency/provider fingerprint。

PaddlePaddle、PaddleOCR 与 PaddleX 继续固定在独立 `.venv-ocr`，不写入默认 solver
`pyproject.toml`。默认环境只安装 F2 的非 Paddle 边界依赖；PDF rasterizer 使用 `pypdfium2`。

## 12. CentOS CPU 服务器

服务器同样使用 CPU，但其 wheel、系统库、OpenMP/MKL、进程模型和缓存目录与 macOS 不同。
本阶段不在本文档中给出未经验证的服务器命令。完成本地 F2 adapter 与五题 smoke 后，再补充独立的
CentOS CPU 部署文档，包括：

- CentOS/AlmaLinux版本和 glibc 基线；
- x86_64 CPU 指令集检查；
- Paddle CPU wheel 与系统依赖；
- 模型缓存预热和只读部署；
- worker数量、线程数、内存和超时；
- systemd/容器启动与健康检查。
