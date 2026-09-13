"""Image-led source review. OCR discrepancies request review, never rewrite facts."""
from __future__ import annotations

from dataclasses import replace
import fcntl
import json
import os
import re
import unicodedata
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic

from jsonschema import Draft202012Validator

from .context import ExtractionArtifactRef
from .multimodal_provider import MultimodalExtractionPrompt, build_multimodal_provider_request
from .problem_domain import ProblemValidationIssue
from .problem_domain_validation import _normalize_text, _question_header_is_covered
from .source_identity import stable_hash

CONTRACT = "problem-source-review/v1"


def _object(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


REGION_SCHEMA = _object({
    "region_id": {"type": ["string", "null"]},
    "page_id": {"type": "string"},
    "bbox": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1},
             "minItems": 4, "maxItems": 4},
})
SCHEMA = _object({
    "schema_version": {"const": CONTRACT, "type": "string"},
    "binding": {"type": "string"},
    "status": {"type": "string", "enum": ["confirmed", "correction_required", "uncertain"]},
    "findings": {"type": "array", "minItems": 1, "items": _object({
        "unit_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "source_text": {"type": "string"},
        "message": {"type": "string", "minLength": 1},
        "regions": {"type": "array", "minItems": 1, "items": REGION_SCHEMA},
    })},
})


def _auxiliary_text_key(text):
    # Similarity thresholds hide one-digit/sign errors inside otherwise identical
    # lines. Normalize typography only, preserving case and mathematical symbols.
    text = unicodedata.normalize('NFKC', text).replace('−', '-').replace('≤', '<=').replace('≥', '>=')
    return re.sub(r'[\s,，。;；、:：]+', '', text)


def source_differences(draft, pack):
    """A separate advisory report; these findings are not validation failures."""
    candidate = _auxiliary_text_key("".join(draft.graph.original_text_lines))
    differences = []
    for item in pack.printed_text:
        text = _auxiliary_text_key(item.text)
        if text and not _question_header_is_covered(item.text, draft) and text not in candidate:
            differences.append({"code": "ocr_transcription_difference", "text": item.text,
                                "region_refs": [item.observation_id]})
    from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
    family = next((f for f in DEFAULT_FAMILY_REGISTRY.families if f.family_id == draft.graph.family_id), None)
    observed = _normalize_text("".join(t.text for t in pack.printed_text))
    if family:
        for requirement in family.required_source_requirements:
            if requirement.source_authority == "printed_source" and not any(
                _normalize_text(m) in observed for m in requirement.printed_source_markers
            ):
                differences.append({"code": "mechanism_not_covered_by_ocr",
                                    "markers": list(requirement.printed_source_markers), "region_refs": []})
    for item in pack.unresolved_items:
        differences.append({"code": item.code, "text": item.hint,
                            "region_refs": list(item.region_refs)})
    return {"schema_version": "problem-source-differences/v1", "differences": differences}


def binding_for(draft, pack):
    return stable_hash({"contract": CONTRACT, "revision": draft.revision_id,
                        "source": pack.source_revision_hash,
                        "images": [(i.page_id, i.artifact.sha256) for i in pack.images]})


def build_review_request(draft, pack, reader, differences, response_format_mode):
    request = build_multimodal_provider_request(
        pack, artifact_reader=reader, expected_problem_id=draft.graph.problem_id,
        include_images=True, response_format_mode=response_format_mode,
    )
    schema_format = {"type": "json_schema", "json_schema": {
        "name": "problem_source_review", "strict": True, "schema": SCHEMA}}
    data = {"binding": binding_for(draft, pack), "draft": draft.graph.wire_payload(),
            "units": {k: {"kind": v.unit_kind, "scope_path": v.scope_path}
                      for k, v in draft.unit_registry.items()},
            "auxiliary_differences": differences,
            "observations": pack.prompt_payload(), "schema": SCHEMA,
            "representation_rules": "当前候选已经经过代码规范化；复核对象是数学题意，非生成格式或冗余表达。"
                "symbol.role是内部用途标签：quadratic_coefficient、primary_parameter、parameter均表示函数系数或参数，"
                "quadratic_coefficient在本系统不专指x²项；实际函数系数以function_expression为准。"
                "minimum_value_given和minimum_target同时出现合法：代码从前者自动物化后者，禁止把它当成题意错误。"
                "代码也会为多个子问共享的最值表达式在共同父scope物化minimum_target，这不扩大局部条件作用域。"
                "minimum_target声明待求的表达式，并非题面给定的数值条件；共享表达式可位于父scope，"
                "各子问的minimum_value_given与其他局部数值仍只在子scope生效。"
                "同样，根据原文已给出的x_range展开符号范围、规范化坐标原点，以及由square_center展开对角线成员关系，"
                "属于表示等价展开，不应仅因原图没有逐字写出这些内部primitive而要求删除。"}
    return replace(request, contract_version=CONTRACT, contract_schema=SCHEMA,
        response_format=schema_format if response_format_mode == "json_schema" else {"type": "json_object"},
        prompt=MultimodalExtractionPrompt(
            system="独立核对原图与候选题意。原图是依据，OCR与候选均可能出错。忽略手写答案、批注和推导。"
                   "检查完整题干和所有小问，不只检查OCR差异。逐项核对原图函数、完整点坐标、范围、几何关系和目标是否进入entities/facts/goals。"
                   "source_text转录正确不代表结构化条件完整；原文存在但facts遗漏的条件必须报correction_required。"
                   "例如point_on_curve_with_x仅记录横坐标和曲线归属，不能替代题目另外给定的纵坐标。只报告改变题意的实际差异；空格、标点、罗马数字的等价写法和scope展示标签不构成题意错误。"
                   "指出候选错误前逐字核对draft中是否真的存在该错误，禁止根据OCR或想象编造候选写法。原图支持候选时返回confirmed；"
                   "有具体转录、条件或题型错误时返回correction_required；无法看清或区分来源时返回uncertain。"
                   "禁止解题或修改草稿。findings只记录本次结论依据，correction_required时仅列需要修复的差异，"
                   "unit_ids使用提供的单元（缺少内容时引用其所属scope），source_text忠实转录原图。"
                   "每项必须定位原图区域：bbox为归一化[x0,y0,x1,y1]，已有区域用region_id，否则null。"
                   "unit_ids和page_id只能逐字复制输入中已有的ID；region_id不确定时用null和有效bbox，禁止编造ID。"
                   "逐字复制binding，只输出符合schema的JSON。",
            user_prefix="请独立阅读完整原图，再与候选比较。以下差异未预判哪一方正确。",
            user_suffix=json.dumps(data, ensure_ascii=False), includes_images=True))


def validate_review(value, draft, pack):
    Draft202012Validator(SCHEMA).validate(value)
    if value["binding"] != binding_for(draft, pack):
        raise ValueError("source review binding does not match image and revision")
    pages = {i.page_id for i in pack.images}
    for finding in value["findings"]:
        if not set(finding["unit_ids"]) <= set(draft.unit_registry):
            raise ValueError("source review refers to an unknown unit")
        for r in finding["regions"]:
            x0, y0, x1, y1 = r["bbox"]
            if r["page_id"] not in pages or x0 >= x1 or y0 >= y1:
                raise ValueError("invalid source review region")
            if r["region_id"] is not None:
                known = pack.region_by_id.get(r["region_id"])
                if known is None or known.page_id != r["page_id"]:
                    raise ValueError("source review region identity mismatch")
    return value


def review_issues(review, draft):
    if review["status"] == "confirmed":
        return ()
    correction = review["status"] == "correction_required"
    findings = review.get("findings") or [{"unit_ids": [draft.graph.root_scope.unit_id],
                                           "message": review.get("error", "image source remains uncertain"),
                                           "source_text": "", "regions": []}]
    return tuple(ProblemValidationIssue(
        code="extraction.problem_source_correction_required" if correction else "extraction.problem_source_uncertain",
        unit_ids=tuple(f["unit_ids"]), dependency_unit_ids=(),
        message=f["message"] + " Source: " + f["source_text"],
        repair_action="repair only the image-confirmed discrepancy" if correction else "inspect the original image region",
        region_refs=tuple(r["region_id"] or "source-review-bbox:" + json.dumps({
            "page_id": r["page_id"], "bbox": r["bbox"]}, sort_keys=True, separators=(",", ":"))
            for r in f["regions"]), retryable=correction,
    ) for f in findings)


class SourceReviewer:
    """Durable at-most-once review reservation, including unknown crash outcomes.

    The product audit additionally fences total semantic/network budgets across
    worker executions. A reserved but unfinished review is never silently retried.
    """
    def __init__(self, store):
        self.store = store

    def review(self, *, context_id, draft, pack, reader, provider, differences):
        directory = self.store.root / "_authority" / "source-reviews"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (stable_hash(context_id) + ".json")
        key = binding_for(draft, pack)
        artifacts = []
        with path.with_suffix(".lock").open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state = json.loads(path.read_text()) if path.exists() else {}
            recovering = key in state
            if key in state:
                if state[key].get("artifact"):
                    ref = ExtractionArtifactRef.from_payload(state[key]["artifact"])
                    return json.loads(self.store.read_bytes(ref)), (ref,)
                if not callable(getattr(provider, "restore_source_review", None)):
                    return {"schema_version": CONTRACT, "status": "uncertain", "binding": key, "error": "previous review outcome is unknown"}, ()
            if not recovering and len(state) >= 3:
                return {"schema_version": CONTRACT, "status": "uncertain", "binding": key, "error": "source review budget exhausted"}, ()
            if not recovering:
                state[key] = {"status": "started"}
                self._save(path, state)
            started = monotonic()
            review = {"schema_version": CONTRACT, "status": "uncertain", "binding": key}
            try:
                if not provider.supports_images:
                    raise ValueError("source review requires an image-capable provider")
                request = build_review_request(draft, pack, reader, differences, provider.response_format_mode)
                artifacts.append(self.store.put_json(kind="problem_source_review_request", payload=request.redacted_payload()))
                # The product journal may have completed before this file was
                # committed. Recovery is read-only; never reissue a paid call.
                response = provider.restore_source_review(request) if recovering else provider.complete(request)
                if response is None:
                    raise ValueError("previous review outcome is unknown")
                artifacts.append(self.store.put_json(kind="problem_source_review_provider_response", payload=dict(response.raw_payload)))
                artifacts.append(self.store.put_bytes(kind="problem_source_review_raw_response", content=response.text.encode(), media_type="text/plain", suffix=".txt"))
                review["usage"] = response.metadata_payload()
                if response.finish_reason == "length":
                    raise ValueError("source review response truncated")
                parsed = validate_review(json.loads(response.text), draft, pack)
                artifacts.append(self.store.put_json(kind="problem_source_review_result", payload=parsed))
                review.update(parsed)
            except Exception as exc:
                # SDK exception strings can contain sensitive request data.
                review["error"] = "source review failed: " + type(exc).__name__
                review["status"] = "uncertain"
            review["duration_ms"] = round((monotonic() - started) * 1000)
            review["differences"] = differences
            ref = self.store.put_json(kind="problem_source_review", payload=review)
            artifacts.append(ref)
            state[key] = {"artifact": ref.to_payload()}
            self._save(path, state)
            return review, tuple(artifacts)

    @staticmethod
    def _save(path: Path, value):
        with NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
            json.dump(value, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
            name = f.name
        os.replace(name, path)
