import os
os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "bos")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from pathlib import Path
from paddlex import create_model
from paddleocr import PaddleOCR

image = Path("/opt/shuxueshuo/internal/source-images/tj-2026-hexi-yimo-25/source-page-01.png")
assert image.is_file(), image

print("1/3 layout PP-DocLayout-S")
layout = create_model(
    model_name="PP-DocLayout-S",
    engine="paddle_static",
    engine_config={
        "run_mode": "paddle",
        "device_type": "cpu",
        "cpu_threads": 1,
        "enable_new_ir": False,
    },
)
list(layout.predict(str(image), batch_size=1, layout_nms=True))
print("layout OK")

print("2/3 text OCR PP-OCRv6_medium_det/rec")
ocr = PaddleOCR(
    text_detection_model_name="PP-OCRv6_medium_det",
    text_recognition_model_name="PP-OCRv6_medium_rec",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    enable_mkldnn=False,
)
list(ocr.predict(str(image)))
print("text OCR OK")

print("3/3 formula PP-FormulaNet_plus-M")
formula = create_model(
    model_name="PP-FormulaNet_plus-M",
    engine="paddle_static",
    engine_config={
        "run_mode": "paddle",
        "device_type": "cpu",
        "cpu_threads": 1,
        "enable_new_ir": False,
    },
)
# 用整页做一次初始化即可；正式链路会送 crop
list(formula.predict(str(image)))
print("formula OK")

root = Path("/root/.paddlex/official_models")
needed = [
    "PP-DocLayout-S",
    "PP-OCRv6_medium_det",
    "PP-OCRv6_medium_rec",
    "PP-FormulaNet_plus-M",
]
for name in needed:
    path = root / name
    print(name, "OK" if path.is_dir() else "MISSING", path)
print("PREHEAT_OK")
