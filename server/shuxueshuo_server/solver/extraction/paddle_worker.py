"""Paddle-backed F2 provider worker, imported only by the OCR environment."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from time import monotonic
from typing import Any, Mapping, Sequence

from PIL import Image, ImageOps

from shuxueshuo_server.solver.extraction.observations import (
    FormulaCropRequest,
    PaddleProviderRecord,
    ProviderManifest,
)


@dataclass(frozen=True)
class PaddleProviderRun:
    record: PaddleProviderRecord
    raw_payloads: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class FormulaWorkerInput:
    request: FormulaCropRequest
    crop_bytes: bytes
    crop_artifact_id: str


class PaddleF2ProviderWorker:
    """Reuse one layout, OCR, and formula model for an entire F2 batch."""

    _MODEL_NAMES = {
        "layout": "PP-DocLayout-S",
        "text_ocr": ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"),
        "formula_ocr": "PP-FormulaNet_plus-M",
    }

    def __init__(self, *, model_root: str | Path | None = None) -> None:
        self.model_root = Path(model_root or Path.home() / ".paddlex" / "official_models")
        self._models: dict[str, object] = {}
        self._manifests: dict[str, ProviderManifest] = {}
        self._initialization_counts = {"layout": 0, "text_ocr": 0, "formula_ocr": 0}

    @property
    def initialization_counts(self) -> Mapping[str, int]:
        return dict(self._initialization_counts)

    def manifests(self) -> tuple[ProviderManifest, ...]:
        return tuple(self._manifest(component) for component in ("layout", "text_ocr", "formula_ocr"))

    def layout(
        self,
        *,
        source_revision_hash: str,
        page_id: str,
        image_bytes: bytes,
    ) -> PaddleProviderRun:
        image, width, height = _decode_image(image_bytes)
        model = self._model("layout")
        started = monotonic()
        raw = tuple(_result_payload(item) for item in model.predict(image))  # type: ignore[attr-defined]
        latency_ms = round((monotonic() - started) * 1000)
        items = tuple(item for payload in raw for item in layout_items_from_paddle(payload))
        return PaddleProviderRun(
            PaddleProviderRecord.create(
                component="layout",
                provider=self._manifest("layout"),
                source_revision_hash=source_revision_hash,
                page_id=page_id,
                width=width,
                height=height,
                items=items,
                latency_ms=latency_ms,
            ),
            raw,
        )

    def text(
        self,
        *,
        source_revision_hash: str,
        page_id: str,
        image_bytes: bytes,
    ) -> PaddleProviderRun:
        image, width, height = _decode_image(image_bytes)
        model = self._model("text_ocr")
        started = monotonic()
        raw = tuple(_result_payload(item) for item in model.predict(image))  # type: ignore[attr-defined]
        latency_ms = round((monotonic() - started) * 1000)
        items = tuple(item for payload in raw for item in text_items_from_paddle(payload))
        return PaddleProviderRun(
            PaddleProviderRecord.create(
                component="text_ocr",
                provider=self._manifest("text_ocr"),
                source_revision_hash=source_revision_hash,
                page_id=page_id,
                width=width,
                height=height,
                items=items,
                latency_ms=latency_ms,
            ),
            raw,
        )

    def formulas(
        self,
        *,
        source_revision_hash: str,
        page_id: str,
        page_width: int,
        page_height: int,
        inputs: Sequence[FormulaWorkerInput],
    ) -> PaddleProviderRun:
        model = self._model("formula_ocr") if inputs else None
        started = monotonic()
        items: list[dict[str, Any]] = []
        raw_payloads: list[Mapping[str, Any]] = []
        images = [_decode_image(item.crop_bytes)[0] for item in inputs]
        payloads = tuple(
            _result_payload(result)
            for result in (model.predict(images) if model is not None else ())  # type: ignore[union-attr]
        )
        if len(payloads) != len(inputs):
            raise RuntimeError(
                "formula provider returned a different number of results than requested crops"
            )
        for item, payload in zip(inputs, payloads, strict=True):
            raw_payloads.append(payload)
            latex = formula_text_from_paddle(payload)
            items.append(
                {
                    "polygon": [
                        [round(x * page_width, 6), round(y * page_height, 6)]
                        for x, y in item.request.polygon
                    ],
                    "confidence": (
                        formula_confidence_from_paddle(payload) if latex else 0.0
                    ),
                    "latex": latex,
                    "source_observation_ids": list(item.request.source_observation_ids),
                    "formula_request_id": item.request.request_id,
                    "source_text_hint": item.request.source_text_hint,
                    "crop_artifact_id": item.crop_artifact_id,
                }
            )
        latency_ms = round((monotonic() - started) * 1000)
        return PaddleProviderRun(
            PaddleProviderRecord.create(
                component="formula_ocr",
                provider=self._manifest("formula_ocr"),
                source_revision_hash=source_revision_hash,
                page_id=page_id,
                width=page_width,
                height=page_height,
                items=items,
                latency_ms=latency_ms,
            ),
            tuple(raw_payloads),
        )

    def _model(self, component: str) -> object:
        existing = self._models.get(component)
        if existing is not None:
            return existing
        if component == "text_ocr":
            from paddleocr import PaddleOCR

            detection, recognition = self._MODEL_NAMES[component]
            model = PaddleOCR(
                text_detection_model_name=detection,
                text_recognition_model_name=recognition,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        else:
            from paddlex import create_model

            model = create_model(self._MODEL_NAMES[component])
        self._models[component] = model
        self._initialization_counts[component] += 1
        return model

    def _manifest(self, component: str) -> ProviderManifest:
        existing = self._manifests.get(component)
        if existing is not None:
            return existing
        names = self._MODEL_NAMES[component]
        name_items = (names,) if isinstance(names, str) else names
        revision = sha256()
        for name in name_items:
            revision.update(name.encode("utf-8"))
            revision.update(_model_directory_digest(self.model_root / name).encode("ascii"))
        manifest = ProviderManifest.create(
            provider="paddle_local_cpu",
            component=component,  # type: ignore[arg-type]
            model_name="+".join(name_items),
            model_revision=f"sha256:{revision.hexdigest()}",
            software_versions={
                "paddlepaddle": version("paddlepaddle"),
                "paddleocr": version("paddleocr"),
                "paddlex": version("paddlex"),
            },
            config={
                "device": "cpu",
                "model_source": "bos",
                "canonical_input": "exif_transposed_rgb",
                "formula_confidence": "provider_score_or_fixed_0.5",
            },
        )
        self._manifests[component] = manifest
        return manifest


def layout_items_from_paddle(payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    result = _result_body(payload)
    items = []
    for box in result.get("boxes", ()):
        if not isinstance(box, Mapping):
            continue
        coordinate = box.get("coordinate")
        if not isinstance(coordinate, Sequence) or len(coordinate) != 4:
            continue
        left, top, right, bottom = (float(value) for value in coordinate)
        items.append(
            {
                "label": str(box.get("label", "unknown")),
                "confidence": float(box.get("score", 0.0)),
                "polygon": [[left, top], [right, top], [right, bottom], [left, bottom]],
            }
        )
    return tuple(items)


def text_items_from_paddle(payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    result = _result_body(payload)
    polygons = result.get("rec_polys") or result.get("dt_polys") or ()
    texts = result.get("rec_texts") or ()
    scores = result.get("rec_scores") or ()
    count = min(len(polygons), len(texts), len(scores))
    return tuple(
        {
            "text": str(texts[index]),
            "confidence": float(scores[index]),
            "polygon": _json_compatible(polygons[index]),
        }
        for index in range(count)
    )


def formula_text_from_paddle(payload: Mapping[str, Any]) -> str:
    return str(_result_body(payload).get("rec_formula") or "").strip()


def formula_confidence_from_paddle(payload: Mapping[str, Any]) -> float:
    body = _result_body(payload)
    for key in ("rec_score", "confidence", "score"):
        value = body.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            value = value[0] if value else None
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            continue
        if 0 <= confidence <= 1:
            return confidence
    return 0.5


def _result_payload(value: object) -> Mapping[str, Any]:
    payload = getattr(value, "json", value)
    if callable(payload):
        payload = payload()
    if not isinstance(payload, Mapping):
        raise ValueError(f"Paddle result is not a mapping: {type(payload).__name__}")
    return _json_compatible(payload)


def _result_body(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    body = payload.get("res", payload)
    return body if isinstance(body, Mapping) else {}


def _json_compatible(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    if hasattr(value, "tolist"):
        return _json_compatible(value.tolist())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _decode_image(content: bytes) -> tuple[object, int, int]:
    import numpy as np

    image = ImageOps.exif_transpose(Image.open(BytesIO(content))).convert("RGB")
    return np.asarray(image), image.width, image.height


def _model_directory_digest(path: Path) -> str:
    if not path.is_dir():
        raise FileNotFoundError(f"required Paddle model is not installed: {path}")
    digest = sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file())
    if not files:
        raise FileNotFoundError(f"Paddle model directory is empty: {path}")
    for item in files:
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(item.stat().st_size.to_bytes(8, "big"))
        with item.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()
