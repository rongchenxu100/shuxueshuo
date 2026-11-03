"""Long-lived page OCR worker for question segmentation, run by the isolated OCR interpreter.

Protocol: one JSON object per stdin line ``{"image": "/abs/path", "auto_orient": true}``; one JSON
object per stdout line. Models load once, so only the first request pays the
start-up cost.

Segmentation only needs where each text line is and whether it starts with a
question number, so the page is detected at reduced resolution and only the
head of each row-leading line is recognised. Full-page recognition took
15–20 s per page; this takes about 1.5–2.5 s on a laptop CPU.
"""

import json
import logging
import os
import sys
from time import monotonic

import numpy as np
from PIL import Image, ImageOps

from shuxueshuo_server.search.ocr_crops import head_crop
from shuxueshuo_server.search.ocr_protocol import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES
from shuxueshuo_server.search.page_orientation import (
    orientation_from_prediction,
    rotate_clockwise,
    uncertain_orientation,
)
from shuxueshuo_server.search.segmentation import page_head_candidates
from shuxueshuo_server.search.segmentation_labels import incomplete_heading

MAX_SIDE = 1600
DETECT_SIDE = 736
# One thread measured fastest on the 2-vCPU (one physical core) server: 8.9 s vs 12.9 s with 8.
# oneDNN (run_mode=mkldnn) hangs there, so it stays off.
ENGINE = {"run_mode": "paddle", "device_type": "cpu",
          "cpu_threads": int(os.environ.get("SEARCH_OCR_CPU_THREADS", "1")), "enable_new_ir": False}


def load_models(*, require_orientation=False):
    from paddlex import create_model

    # Heads only need question numbers: small_rec kept every number on real phone photos at 1.8x
    # the speed. Detection must stay medium at DETECT_SIDE; lower sides or smaller det dropped heads.
    models = {name: create_model(model, engine="paddle_static", engine_config=ENGINE)
              for name, model in (("layout", "PP-DocLayout-S"), ("det", "PP-OCRv6_medium_det"),
                                  ("rec", "PP-OCRv6_small_rec"))}
    try:
        models["orientation"] = create_model("PP-LCNet_x1_0_doc_ori", engine="paddle_static", engine_config=ENGINE)
    except Exception as exc:
        if require_orientation:
            raise
        print(f"Page orientation unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
        models["orientation"] = None
    if require_orientation and any(model is None for model in models.values()):
        raise RuntimeError("ocr.models_unavailable")
    return models


def _bounds(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def observe(models, path, *, auto_orient=True):
    if type(auto_orient) is not bool:
        raise ValueError("orientation.invalid_auto_orient")
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    scale = min(1.0, MAX_SIDE / max(image.size))
    if scale < 1:
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    timings = {}

    started = monotonic()
    orientation = {"status": "manual", "rotation_degrees": 0, "predicted_degrees": None, "confidence": None}
    if auto_orient:
        orientation = uncertain_orientation("model_unavailable")
        if models.get("orientation") is not None:
            try:
                prediction = next(iter(models["orientation"].predict(np.asarray(image)))).json["res"]
                orientation = orientation_from_prediction(prediction)
            except Exception as exc:  # noqa: BLE001 - third-party inference failure falls back to manual rotation
                print(f"Page orientation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                orientation = uncertain_orientation("prediction_failed")
        image = rotate_clockwise(image, orientation["rotation_degrees"])
    timings["orientation"] = round((monotonic() - started) * 1000)
    pixels = np.asarray(image)
    w, h = image.size

    started = monotonic()
    layout = next(iter(models["layout"].predict(pixels))).json["res"]
    timings["layout"] = round((monotonic() - started) * 1000)

    started = monotonic()
    detected = next(iter(models["det"].predict(pixels, limit_side_len=DETECT_SIDE, limit_type="max"))).json["res"]
    timings["detect"] = round((monotonic() - started) * 1000)

    polys = [[(float(x), float(y)) for x, y in poly] for poly in detected.get("dt_polys", ())]
    boxes = [_bounds(poly) for poly in polys]
    lines = [{"box": [x0 / w, y0 / h, x1 / w, y1 / h], "poly": [[x / w, y / h] for x, y in poly]}
             for (x0, y0, x1, y1), poly in zip(boxes, polys, strict=True)]
    regions = [{"label": str(item.get("label")), "confidence": float(item.get("score", 0.0)),
                "box": [item["coordinate"][0] / w, item["coordinate"][1] / h,
                        item["coordinate"][2] / w, item["coordinate"][3] / h]}
               for item in layout.get("boxes", ())]
    # Per-line recognition costs ~40 ms on CPU and batching does not help, so only
    # row-leading lines (the only ones that can start a question) are recognised.
    wanted = page_head_candidates(lines, regions, w, h)
    crops = [np.asarray(head_crop(image, polys[i])) for i in wanted]
    started = monotonic()
    heads = dict(zip(wanted, (r.json["res"] for r in models["rec"].predict(crops)), strict=True)) if crops else {}
    # Worksheet numbers keep the short fast path. Only a visibly clipped
    # textbook heading is re-read once, far enough to include its closing
    # bracket and full number. This never re-recognises the whole page.
    extended = [i for i in wanted if incomplete_heading(heads[i].get("rec_text", ""))]
    if extended:
        wider = [np.asarray(head_crop(image, polys[i], head_heights=8)) for i in extended]
        for i, result in zip(extended, models["rec"].predict(wider), strict=True):
            if result.json["res"].get("rec_text"):
                heads[i] = result.json["res"]
    timings["recognize_heads"] = round((monotonic() - started) * 1000)

    return {
        "width": w,
        "height": h,
        "orientation": orientation,
        "lines": [
            {**line,
             "head": heads.get(i, {}).get("rec_text", ""),
             "confidence": float(heads.get(i, {}).get("rec_score", 0.0))}
            for i, line in enumerate(lines)
        ],
        "layout": regions,
        "latency_ms": timings,
    }


def main():
    # Paddle logs to stdout; keep it for protocol replies only.
    replies, sys.stdout = sys.stdout, sys.stderr
    models = load_models()
    print(json.dumps({"ready": True}), file=replies, flush=True)
    while line := sys.stdin.readline(MAX_REQUEST_BYTES + 1):
        if not line.strip():
            continue
        try:
            if len(line.encode()) > MAX_REQUEST_BYTES or not line.endswith("\n"):
                raise ValueError("ocr.invalid_request")
            request = json.loads(line)
            reply = {"ok": True, **observe(models, request["image"], auto_orient=request.get("auto_orient", True))}
            encoded = json.dumps(reply, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode()) > MAX_RESPONSE_BYTES:
                raise ValueError("ocr.invalid_response")
        except Exception:
            logging.getLogger(__name__).exception("Search OCR request failed")
            encoded = json.dumps({"ok": False, "error": "ocr.failed"})
        print(encoded, file=replies, flush=True)


if __name__ == "__main__":
    main()
