import os
os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "bos")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from pathlib import Path
from paddleocr import PaddleOCR

image = Path("/opt/shuxueshuo/internal/source-images/tj-2026-hexi-yimo-25/source-page-01.png")
assert image.is_file(), image

ocr = PaddleOCR(
    text_detection_model_name="PP-OCRv6_medium_det",
    text_recognition_model_name="PP-OCRv6_medium_rec",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    enable_mkldnn=False,
)
results = list(ocr.predict(str(image)))
assert results, "text OCR returned no result"
print("text OCR smoke OK; pages=", len(results))
