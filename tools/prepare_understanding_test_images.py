"""Reproduce the seven reviewed test images using only lossless crops/copies.

Run from server: uv run python ../tools/prepare_understanding_test_images.py
The user-supplied clean Xiqing source must already be archived in the repository.
"""

import json
import shutil
from hashlib import sha256
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "server/tests/solver/fixtures/math-notation-v1/integration-images-20260916"
SOURCE = "internal/source-images/"
SELECTIONS = (
    ("tj-2026-heping-yimo-25", SOURCE + "tj-2026-heping-yimo-25/source-page-01.png", (0, 0, 1458, 650), "crop_question_25"),
    ("tj-2026-heping-ermo-25", SOURCE + "tj-2026-heping-ermo-25/source-page-01.png", (0, 1065, 1180, 1680), "crop_question_25"),
    ("tj-2026-hexi-yimo-25", SOURCE + "tj-2026-hexi-yimo-25/source-page-01.png", (0, 1235, 1752, 1580), "crop_question_25"),
    ("tj-2026-nankai-yimo-25", SOURCE + "tj-2026-nankai-yimo-25/source-page-01.jpg", (0, 1700, 1180, 2340), "crop_question_25"),
    ("tj-2026-xiqing-yimo-25", SOURCE + "tj-2026-xiqing-yimo-25/source-user-clean-20260916.png", None, "user_clean_replacement"),
    ("k-quad", "server/tests/solver/fixtures/understanding-v2/k-quad/source.png", None, "intentional_missing_figures_1_to_4"),
    ("function-quantifiers", "server/tests/solver/fixtures/understanding-v2/function-quantifiers/source.png", None, "unchanged"),
)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records = {}
    for case, source, box, purpose in SELECTIONS:
        original = REPO / source
        target = OUTPUT / f"{case}.png"
        with Image.open(original) as image:
            original_size = list(image.size)
            if box:
                left, top, right, bottom = box
                assert 0 <= left < right <= image.width
                assert 0 <= top < bottom <= image.height
                image.crop(box).save(target, format="PNG")
            else:
                shutil.copyfile(original, target)
        with Image.open(target) as image:
            selected_size = list(image.size)
        records[case] = {
            "file": target.name,
            "sha256": sha256(target.read_bytes()).hexdigest(),
            "size": selected_size,
            "source": source,
            "source_sha256": sha256(original.read_bytes()).hexdigest(),
            "source_size": original_size,
            "crop_box": list(box) if box else None,
            "purpose": purpose,
            "expected_missing_figures": ["图1", "图2", "图3", "图4"] if case == "k-quad" else [],
        }
    manifest = {
        "schema_version": "understanding-test-images/v1",
        "date": "2026-09-16",
        "processing": "deterministic_pixel_crop_or_byte_copy_no_redraw",
        "auxiliary_text": "image_only_no_ocr",
        "cases": records,
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    print(f"Prepared {len(records)} images in {OUTPUT}")


if __name__ == "__main__":
    main()
