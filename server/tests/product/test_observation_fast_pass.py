from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest

from shuxueshuo_server.product.observation_fast_pass import run
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import ProblemExtractionContext
from shuxueshuo_server.solver.extraction.multimodal_evidence import (
    MultimodalEvidencePackBuilder,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ProblemExtractionContextError,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig


class _FakeExecution:
    def __init__(self, tmp_path: Path) -> None:
        self.work = tmp_path
        self.build = {"id": "build-fast-pass", "problem_id": "problem-fast-pass"}
        self.values: dict[tuple[str, str], object] = {}

    def bytes(self, stage: str, name: str) -> bytes:
        value = self.values[(stage, name)]
        assert isinstance(value, bytes)
        return value

    def read(self, stage: str, name: str) -> object:
        return self.values[(stage, name)]

    def add(self, name: str, value: object, role: str = "output", **_: object) -> None:
        if hasattr(value, "to_payload"):
            value = value.to_payload()  # type: ignore[union-attr]
        stage = "source" if name.startswith("Source /") or name == "Observation mode" else "observation"
        self.values[(stage, name)] = value


def test_production_config_pins_math_expression_encoding() -> None:
    assert SolverRuntimeConfig.from_sources().argument_encoding == "math-expression/v1"
    assert SolverRuntimeConfig(argument_encoding="source-ref").argument_encoding == "source-ref"


def test_fast_pass_writes_valid_observation_context_without_ocr_text(tmp_path: Path) -> None:
    image = BytesIO()
    Image.new("RGB", (80, 60), "white").save(image, format="PNG")
    execution = _FakeExecution(tmp_path)
    execution.values[("source", "规范化图片")] = image.getvalue()

    run(execution, "source")
    run(execution, "observation")

    context = execution.read("observation", "Observation Context")
    assert context["quality"]["observation_mode"] == "fast-pass"
    assert context["quality"]["ocr_status"] == "skipped_fast_pass"
    assert context["quality"]["text_span_count"] == 0
    assert any(item["kind"] == "selection_crop" for item in context["state"]["artifacts"])
    assert context["state"]["artifacts"]
    validation = execution.read("observation", "观察校验")
    assert validation["ok"] is True
    assert validation["mode"] == "fast-pass"


def test_fast_pass_selection_crop_builds_image_only_evidence_pack(tmp_path: Path) -> None:
    image = BytesIO()
    Image.new("RGB", (80, 60), "white").save(image, format="PNG")
    execution = _FakeExecution(tmp_path)
    execution.values[("source", "规范化图片")] = image.getvalue()

    run(execution, "source")
    run(execution, "observation")

    initial = ProblemExtractionContext.from_payload(
        execution.read("source", "Source / selection / initial Context")
    )
    context = ProblemExtractionContext.from_payload(
        execution.read("observation", "Observation Context"),
        ancestor_contexts=(initial,),
    )
    store = ExtractionArtifactStore(tmp_path / "extraction-artifacts")
    pack = MultimodalEvidencePackBuilder().build(context, artifact_reader=store)

    assert len(pack.images) == 1
    assert pack.images[0].artifact.kind == "selection_crop"
    assert pack.printed_text == ()
    assert pack.recognized_formulas == ()
    assert len(pack.region_index) == 1
    assert pack.region_index[0].kind == "selection"
    assert pack.region_index[0].origin == "unknown"

    stripped_quality = dict(context.to_payload()["quality"])
    stripped_quality.pop("ocr_status", None)
    with pytest.raises(ProblemExtractionContextError) as error:
        MultimodalEvidencePackBuilder().build(
            replace(context, quality=stripped_quality),
            artifact_reader=store,
        )
    assert error.value.code == "extraction.multimodal_evidence_pack_invalid"


def test_fast_pass_mode_is_authoritative_even_when_ocr_url_is_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from shuxueshuo_server.product.application import dependencies
    from shuxueshuo_server.product.pipelines import V2

    discovered = {
        "stages": {
            stage["stage_key"]: {
                "resources": {},
                "config": {"max_attempts": 3} if stage["stage_key"] == "solver" else {},
            }
            for stage in V2["stages"]
        }
    }
    monkeypatch.setattr(
        "shuxueshuo_server.product.dependency_cache.release_dependencies",
        lambda: discovered,
    )
    monkeypatch.setattr(
        "shuxueshuo_server.product.application.deployment_version",
        lambda _discovered=None: "test-deployment",
    )
    monkeypatch.setenv("PRODUCT_OBSERVATION_MODE", "fast-pass")
    monkeypatch.setenv("PRODUCT_OCR_URL", "http://ocr:8080")

    target = dependencies({"sha256": "source"}, None, V2)
    assert target["config"]["observation"] == {
        "mode": "fast-pass",
        "provider": "none",
        "provider_version": "fast-pass/v1",
    }


def test_runner_uses_frozen_fast_pass_mode_even_when_ocr_url_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from shuxueshuo_server.product.runner import StageRunner

    calls: list[tuple[object, str]] = []
    monkeypatch.setattr(
        "shuxueshuo_server.product.observation_fast_pass.run",
        lambda execution, phase: calls.append((execution, phase)),
    )
    execution = type(
        "Execution",
        (),
        {"build": {"effective_config": {"observation": {"mode": "fast-pass"}}}},
    )()
    monkeypatch.setenv("PRODUCT_OCR_URL", "http://ocr:8080")
    runner = StageRunner.__new__(StageRunner)
    runner.x = execution

    runner.ocr("source")

    assert calls == [(execution, "source")]
