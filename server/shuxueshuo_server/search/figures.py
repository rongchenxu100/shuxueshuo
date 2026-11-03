"""Private question pictures. Display identity never admits mathematical identity.

The optional sidecar is an authored/reviewed asset manifest, not model output.
Absent a reviewed manifest, show the original crop as a single source picture.
All boxes refer to that immutable image; callers retain the ownership/read lease.
"""

import json
import math
from functools import cache
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from jsonschema import Draft202012Validator
from PIL import Image, UnidentifiedImageError

from .storage import SearchError

VERSION = "question-figures/v1"
MANIFEST = "question-figures.json"
SCHEMA = Path(__file__).resolve().parents[3] / "internal/schemas/question-figures-v1.schema.json"


@cache
def validator():
    return Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def pixel_box(box, size):
    """One coordinate system for both the manifest and the bytes being displayed."""
    if len(box) != 4 or not all(type(v) in (float, int) and math.isfinite(v) and 0 <= v <= 1 for v in box):
        raise SearchError("figure.invalid_box", 409)
    x0, y0, x1, y1 = box
    if x0 >= x1 or y0 >= y1:
        raise SearchError("figure.invalid_box", 409)
    result = tuple(round(v * size[i % 2]) for i, v in enumerate(box))
    if result[0] >= result[2] or result[1] >= result[3]:
        raise SearchError("figure.empty_crop", 409)
    return result


def validate_manifest(manifest, source):
    if not validator().is_valid(manifest):
        raise SearchError("figure.invalid_manifest", 409)
    if manifest["source"] != source:
        raise SearchError("figure.source_changed", 409)
    ids, options, labels = set(), set(), set()
    sources = []
    for figure in manifest["figures"]:
        identifier = figure["id"]
        if identifier in ids:
            raise SearchError("figure.duplicate_id", 409)
        ids.add(identifier)
        pixel_box(figure["box"], (source["width"], source["height"]))
        target = figure.get("target_ref")
        if target and target.rsplit("/goals/", 1)[0] != figure["scope_ref"]:
            raise SearchError("figure.wrong_target", 409)
        if figure["role"] == "option":
            key = (target, figure["option_id"])
            label = (target, figure["label"])
            if key in options or label in labels:
                raise SearchError("figure.duplicate_option", 409)
            options.add(key)
            labels.add(label)
        if figure["role"] == "source":
            sources.append(figure)
    if len(sources) != 1 or sources[0]["id"] != "original" or sources[0]["box"] != [0, 0, 1, 1] or sources[0]["scope_ref"] != "/root" or sources[0].get("target_ref"):
        raise SearchError("figure.invalid_source", 409)


def source_image(directory):
    directory = Path(directory)
    for filename, quality in (("original.png", "original"), ("question.png", "processed")):
        path = directory / filename
        if path.is_symlink():
            raise SearchError("storage.symlink", 400)
        if not path.is_file():
            continue
        content = path.read_bytes()
        try:
            with Image.open(BytesIO(content)) as picture:
                if picture.format != "PNG":
                    raise SearchError("figure.invalid_image", 409)
                source = {"sha256": sha256(content).hexdigest(), "width": picture.width,
                          "height": picture.height, "quality": quality}
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise SearchError("figure.invalid_image", 409) from exc
        return content, source
    raise SearchError("figure.unavailable", 410)


def manifest_for(directory):
    _, source = source_image(directory)
    path = Path(directory) / MANIFEST
    if path.is_symlink():
        raise SearchError("storage.symlink", 400)
    if path.is_file():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise SearchError("figure.invalid_manifest", 409) from exc
    else:
        manifest = {"schema_version": VERSION, "source": source, "figures": [
            {"id": "original", "role": "source", "scope_ref": "/root", "box": [0, 0, 1, 1]}]}
    validate_manifest(manifest, source)
    return manifest


def presentation_identity(manifest):
    """Conservative picture identity, never used for public problem deduplication."""
    return sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":")).encode()).hexdigest()


def present(directory, search_id):
    manifest = manifest_for(directory)
    digest = presentation_identity(manifest)
    return {**manifest, "content_id": digest, "figures": [
        {**figure, "image_url": f"/api/search/problems/{search_id}/figures/{figure['id']}?version={digest}"}
        for figure in manifest["figures"]]}


def image_bytes(directory, figure_id, version=None):
    manifest = manifest_for(directory)
    if version is not None and version != presentation_identity(manifest):
        raise SearchError("figure.version_changed", 409)
    figure = next((row for row in manifest["figures"] if row["id"] == figure_id), None)
    if figure is None:
        raise SearchError("figure.not_found", 404)
    content, source = source_image(directory)
    if source != manifest["source"]:
        raise SearchError("figure.source_changed", 409)
    if figure["role"] == "source":
        return content
    with Image.open(BytesIO(content)) as original:
        crop = original.crop(pixel_box(figure["box"], original.size))
        output = BytesIO()
        crop.save(output, format="PNG")
        return output.getvalue()
