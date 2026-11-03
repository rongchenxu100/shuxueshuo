"""Turn a cropped question photo into the small, clean PNG sent to stage one.

Upload to the model's file API dominates stage-one latency and grows with
bytes, so the crop is reduced to what reading needs: grayscale, paper shading
flattened to white, 16 grey levels, long side capped.
"""

import re
from hashlib import sha256
from io import BytesIO

from PIL import Image, ImageChops, ImageFilter, ImageOps

MAX_SIDE = 1600
LEVELS = 16
PAPER = 232
IMAGE_INPUT_VERSION = "search-question-images/v1"
DETAIL_INPUT_VERSION = "search-question-images/v2"


def question_png(crop, *, max_side=MAX_SIDE):
    """PNG bytes for a PIL crop; deterministic for the same input.

    same-crop-normalized requires the entire crop in both processed/original.
    Only uniform resizing (with pixel rounding) and photometric changes are
    allowed here: no recropping, padding, rotation, warping or recomposition.
    Any such change needs an explicit coordinate mapping before boxes can be reused.
    """
    gray = ImageOps.grayscale(crop)
    scale = min(1.0, max_side / max(crop.size))
    expected_size = tuple(round(side * scale) for side in crop.size)
    if scale < 1:
        gray = gray.resize(expected_size, Image.LANCZOS)
    ink = ImageChops.subtract(_background(gray), gray)
    flat = ImageOps.invert(ink)
    flat = ImageOps.autocontrast(flat, cutoff=(1, 0))
    step = 256 // LEVELS
    flat = flat.point(lambda v: 255 if v >= PAPER else v // step * step)
    if flat.size != expected_size:
        raise ValueError('image_input.geometry_mismatch')
    buffer = BytesIO()
    flat.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _background(gray):
    """Paper brightness: strokes removed by a max filter at low resolution, then smoothed."""
    factor = 8
    small = gray.resize((max(1, gray.width // factor), max(1, gray.height // factor)), Image.BOX)
    small = small.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(2))
    return small.resize(gray.size, Image.BILINEAR)


def image_inputs(processed, original, *, detail_regions=()):
    """Bind two renditions of one crop; no guessed region or geometric remapping.

    Recompute preprocessing before allowing any model call. Normalized boxes
    describe the same full crop even when the processed rendition was reduced.
    The original bytes are sent unchanged, preserving faint dots and dashes.
    """
    with Image.open(BytesIO(original)) as picture:
        if picture.format != "PNG":
            raise ValueError("image_input.original_not_png")
        if question_png(picture) != processed:
            raise ValueError("image_input.crop_mismatch")
    views = []
    for image_id, kind, content in (("primary", "processed", processed), ("original", "original", original)):
        with Image.open(BytesIO(content)) as picture:
            views.append({"image_id": image_id, "kind": kind, "sha256": sha256(content).hexdigest(),
                          "width": picture.width, "height": picture.height, "box": [0, 0, 1, 1]})
    if detail_regions:
        from .graph_details import detail_crops
        views.extend(view for view, _ in detail_crops(original, detail_regions))
    return {"schema_version": DETAIL_INPUT_VERSION if detail_regions else IMAGE_INPUT_VERSION,
            "coordinate_space": "same-crop-normalized", "views": views}


def expected_image_hashes(result):
    """Legacy runs keep their one-image contract; new runs bind both views."""
    inputs = result.get("image_inputs")
    if inputs is None:
        return [result["question_sha256"]]
    if not isinstance(inputs, dict) or inputs.get("schema_version") not in (IMAGE_INPUT_VERSION, DETAIL_INPUT_VERSION):
        return []
    views = inputs.get("views")
    count = (2,) if inputs['schema_version'] == IMAGE_INPUT_VERSION else range(3, 11)
    if (inputs.get("coordinate_space") != "same-crop-normalized" or not isinstance(views, list) or len(views) not in count or
            any(not isinstance(view, dict) for view in views) or
            [(v.get("image_id"), v.get("kind")) for v in views[:2]] != [("primary", "processed"), ("original", "original")] or
            any(v.get("box") != [0, 0, 1, 1] for v in views[:2]) or
            any(not isinstance(v.get("sha256"), str) or not re.fullmatch('[0-9a-f]{64}', v['sha256']) or
                any(type(v.get(k)) is not int or v[k] <= 0 for k in ('width', 'height')) for v in views) or
            views[0]["sha256"] != result["question_sha256"]):
        return []
    if len(views) > 2:
        from .figures import pixel_box
        from .storage import SearchError
        refs = set()
        for i, view in enumerate(views[2:]):
            if (view.get('image_id') != f'detail-{i+1}' or view.get('kind') != 'detail' or
                    view.get('source_image_id') != 'original' or view.get('source_sha256') != views[1]['sha256'] or
                    not isinstance(view.get('region_ref'), str) or not re.fullmatch(
                        r'/public_content/(?:statement_figure_regions|figure_regions)/\d+', view['region_ref']) or
                    view['region_ref'] in refs):
                return []
            refs.add(view['region_ref'])
            try:
                box = pixel_box(view.get('box'), (views[1]['width'], views[1]['height']))
            except (SearchError, TypeError):
                return []
            if (list(box) != view.get('pixel_box') or view['width'] != box[2]-box[0] or
                    view['height'] != box[3]-box[1] or min(view['width'], view['height']) < 32):
                return []
    return [view["sha256"] for view in views]
