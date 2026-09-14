import os

os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "bos")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from pathlib import Path
from paddlex import create_model

image = Path("/opt/shuxueshuo/internal/source-images/tj-2026-hexi-yimo-25/source-page-01.png")
assert image.is_file(), image

model = create_model(
    model_name="PP-DocLayout-S",
    engine="paddle_static",
    engine_config={
        "run_mode": "paddle",
        "device_type": "cpu",
        "cpu_threads": 1,
        "enable_new_ir": False,
    },
)
print("create_model_ok run_mode=paddle enable_new_ir=False")

results = list(model.predict(str(image), batch_size=1, layout_nms=True))
assert results, "PP-DocLayout-S returned no page result"
print("PP-DocLayout-S smoke OK; page_results=", len(results))
