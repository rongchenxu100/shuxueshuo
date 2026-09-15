"""Image-led source review. OCR discrepancies request review, never rewrite facts."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import fcntl
import json
import os
import re
import unicodedata
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic

from jsonschema import Draft202012Validator, ValidationError

from .context import ExtractionArtifactRef
from .multimodal_provider import MultimodalExtractionPrompt, build_multimodal_provider_request
from .problem_domain import ProblemValidationIssue
from .problem_domain_validation import _normalize_text, _question_header_is_covered
from .source_identity import stable_hash

CONTRACT = "problem-source-review/v1"
REVIEW_INVALID = "extraction.problem_source_review_invalid"
REVIEW_FAILED = "extraction.problem_source_review_failed"
SOURCE_REVIEW_BLOCKING_CODES = frozenset({
    "extraction.problem_source_uncertain", REVIEW_INVALID, REVIEW_FAILED,
})


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
                "属于表示等价展开，不应仅因原图没有逐字写出这些内部primitive而要求删除。"
                "对于题面M(f(t), y_M)在曲线上，若y_M只是未再使用的纵坐标占位记号，curve_at_x已完整表达其题意，"
                "不应要求增加y_M Symbol或重复point_coordinate；source_text仍保留原文记号。"
                "这与题面另行给定具体纵坐标数值或含其他变量的限制不同：后者必须保留，不能以占位符为由省略。"
                "point_coordinate只给坐标，不声明曲线归属；题面另说该点在曲线上时须保留point_on_curve或其自身的曲线构造。"
                "另一个交点的exclude_point引用不替被排除点声明曲线归属。公共题干按左右次序定义两个交点时，"
                "分别用side=left/right；不能用相互循环exclude_point代替左右次序。"
                "候选不得把自行计算或手写演算的坐标当成原题条件。比如只说与y轴交于C时，"
                "y_axis_intercept足够，不应额外写从函数计算的C(0,c)；除非印刷原文明确给出了该坐标。"}
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
                   "unit_ids和page_id只能逐字复制输入中已有的ID；region_id不确定时用JSON null（不是字符串\"null\"）和有效bbox，禁止编造ID。"
                   "逐字复制binding，只输出符合schema的JSON。",
            user_prefix="请独立阅读完整原图，再与候选比较。以下差异未预判哪一方正确。",
            user_suffix=json.dumps(data, ensure_ascii=False), includes_images=True))


class ReviewValidationError(ValueError):
    """Safe diagnostics without echoing arbitrary provider content."""

    def __init__(self, reason, path):
        super().__init__(reason)
        self.reason = reason
        self.path = path


def normalize_review(value):
    """One wire-format compatibility rule; never infer or repair evidence IDs."""
    normalized = deepcopy(value)
    changes = []
    findings = normalized.get("findings") if isinstance(normalized, dict) else None
    for i, finding in enumerate(findings if isinstance(findings, list) else []):
        regions = finding.get("regions") if isinstance(finding, dict) else None
        for j, region in enumerate(regions if isinstance(regions, list) else []):
            if isinstance(region, dict) and region.get("region_id") == "null":
                region["region_id"] = None
                changes.append({"path": f"/findings/{i}/regions/{j}/region_id",
                                "rule": "region_id_string_null", "before": "null", "after": None})
    return normalized, changes


def validate_review(value, draft, pack):
    Draft202012Validator(SCHEMA).validate(value)
    if value["binding"] != binding_for(draft, pack):
        raise ReviewValidationError("binding_mismatch", "/binding")
    pages = {i.page_id for i in pack.images}
    for i, finding in enumerate(value["findings"]):
        if not set(finding["unit_ids"]) <= set(draft.unit_registry):
            raise ReviewValidationError("unknown_unit", f"/findings/{i}/unit_ids")
        for j, r in enumerate(finding["regions"]):
            path = f"/findings/{i}/regions/{j}"
            x0, y0, x1, y1 = r["bbox"]
            if r["page_id"] not in pages:
                raise ReviewValidationError("unknown_page", path + "/page_id")
            if x0 >= x1 or y0 >= y1:
                raise ReviewValidationError("invalid_bbox", path + "/bbox")
            if r["region_id"] is not None:
                known = pack.region_by_id.get(r["region_id"])
                if known is None or known.page_id != r["page_id"]:
                    raise ReviewValidationError("region_identity_mismatch", path + "/region_id")
    return value


def review_issues(review, draft):
    # Old reports used uncertain for every exception. They remain readable, but
    # an operational failure must never be described as the model's judgement.
    if review.get("error") or review.get("status") == "failed":
        return (ProblemValidationIssue(
            code=review.get("error_code", REVIEW_FAILED),
            unit_ids=(draft.graph.root_scope.unit_id,), dependency_unit_ids=(),
            message=review.get("error", "source review processing failed"),
            repair_action="inspect source review diagnostics and submit a new build",
            region_refs=(), retryable=False,
        ),)
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
                    return {"schema_version": CONTRACT, "status": "failed", "binding": key,
                            "error_code": REVIEW_FAILED, "error": "previous review outcome is unknown"}, ()
            if not recovering and len(state) >= 3:
                return {"schema_version": CONTRACT, "status": "failed", "binding": key,
                        "error_code": REVIEW_FAILED, "error": "source review budget exhausted"}, ()
            if not recovering:
                state[key] = {"status": "started"}
                self._save(path, state)
            started = monotonic()
            # Audit status may be failed; the model contract still has exactly
            # three semantic outcomes. model_status preserves its raw decision.
            review = {"schema_version": CONTRACT, "status": "failed", "binding": key}
            phase = "request"
            invoked = False
            try:
                if not provider.supports_images:
                    raise ValueError("source review requires an image-capable provider")
                request = build_review_request(draft, pack, reader, differences, provider.response_format_mode)
                from .multimodal_provider import prepare_provider_request
                request = prepare_provider_request(provider, request)
                artifacts.append(self.store.put_json(kind="problem_source_review_request", payload=request.redacted_payload()))
                # The product journal may have completed before this file was
                # committed. Recovery is read-only; never reissue a paid call.
                invoked = True
                response = provider.restore_source_review(request) if recovering else provider.complete(request)
                if response is None:
                    raise ValueError("previous review outcome is unknown")
                artifacts.append(self.store.put_json(kind="problem_source_review_provider_response", payload=dict(response.raw_payload)))
                artifacts.append(self.store.put_bytes(kind="problem_source_review_raw_response", content=response.text.encode(), media_type="text/plain", suffix=".txt"))
                review["usage"] = response.metadata_payload()
                phase = "validation"
                if response.finish_reason == "length":
                    raise ReviewValidationError("response_truncated", "")
                value = json.loads(response.text)
                if isinstance(value, dict) and value.get("status") in ("confirmed", "correction_required", "uncertain"):
                    review["model_status"] = value["status"]
                normalized, changes = normalize_review(value)
                review["normalizations"] = changes
                parsed = validate_review(normalized, draft, pack)
                phase = "persist_result"
                artifacts.append(self.store.put_json(kind="problem_source_review_result", payload=parsed))
                review.update(parsed)
            except Exception as exc:
                if invoked and phase == "request":
                    review["usage"] = {"provider": getattr(provider, "provider_name", None),
                        "request_model": getattr(provider, "model", None),
                        "response_model": getattr(provider, "last_response_model", None),
                        "provider_attempts": list(getattr(provider, "last_provider_attempts", ())),
                        "usage": getattr(provider, "last_usage", None),
                        "thinking_mode": request.thinking_mode, "reasoning_effort": request.reasoning_effort}
                # SDK exception strings can contain sensitive request data.
                review["error"] = "source review failed: " + type(exc).__name__
                review["status"] = "failed"
                invalid = phase == "validation" and isinstance(exc, (json.JSONDecodeError, ValidationError, ReviewValidationError))
                review["error_code"] = REVIEW_INVALID if invalid else REVIEW_FAILED
                details = {"phase": phase, "exception_type": type(exc).__name__}
                if isinstance(exc, ReviewValidationError):
                    details.update(reason=exc.reason, path=exc.path)
                elif isinstance(exc, json.JSONDecodeError):
                    details.update(reason="invalid_json", line=exc.lineno, column=exc.colno)
                elif isinstance(exc, ValidationError):
                    # Paths may contain arbitrary extra keys supplied by the
                    # model. Only expose schema-defined fields and array indexes.
                    fields = {"schema_version", "binding", "status", "findings", "unit_ids", "source_text", "message", "regions", "region_id", "page_id", "bbox"}
                    details.update(reason="schema_violation", validator=exc.validator,
                        path="/" + "/".join(str(p) if isinstance(p, int) or p in fields else "?" for p in exc.absolute_path))
                review["error_details"] = details
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
