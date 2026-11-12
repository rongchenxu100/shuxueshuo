"""Student extraction adds public-content review without changing graph contracts."""

import json
import re
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.stage_one import contracts
from shuxueshuo_server.graph_lesson.stage_one.extraction import (
    GraphStageOneContract,
    changed_paths,
    validate_candidate,
)
from shuxueshuo_server.graph_lesson.stage_one.runner import build_image_request
from shuxueshuo_server.problem_understanding.candidate_common import strict_json
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.review_contract import pointer
from shuxueshuo_server.problem_understanding.workflow_ledger import WorkflowStop
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    MultimodalExtractionPrompt,
    MultimodalProviderImage,
)

from .identity import (
    EXTRACTION_CONTRACT,
    PUBLIC_SCHEMA_PATH,
    candidate_schema,
    mathematical_candidate,
    public_structure_errors,
)
from .question_image import image_inputs

PUBLIC_PROMPT_PATH = contracts.ROOT / "internal/llm-prompts/search-stage-one-public.md"
REVIEW_CONTRACT = "search-problem-review/v1"
IMAGE_VIEWS_PROMPT = """前两张图片是同一道题、同一裁剪框的两个版本，不是两页或两道题。
第 1 张 primary 是便于读文字的预处理图；第 2 张 original 是保留颜色、淡线、虚线及空实点的原裁图。
逐项对照第 2 张核对图形和细小标记；预处理造成的缺失不代表原题不存在。
所有 figure_regions 与 statement_figure_regions 使用同一裁图的归一化坐标，两图位置一一对应。
原裁图仍不清楚或被遮挡时必须保留不确定性，不能根据题干、答案或解析补造图形事实。"""
DETAIL_VIEWS_PROMPT = """第 3 张起是 original 的局部裁片，来源和裁框见 image_inputs.views；不是额外题目，也不是参考答案。
裁框由上一轮未确认的识别提出，只是定位提示；必须回到完整原图确认图号、坐标轴、数字刻度及裁框是否完整。
逐幅读取曲线穿过横轴的位置与该处刻度，核对原点、正负号和重合关系，不要求交点旁另写坐标对。
重新独立提取整道题；所有公开区域坐标仍以 original 整图为准，不能填局部裁片坐标。
如果细节仍不清楚或裁错图，保留具体不确定性。复核时同时检查整图和局部图，不按所求变换倒推选项事实。"""


def review_schema():
    schema = contracts.review_schema()
    schema["properties"]["findings"]["items"]["properties"]["kind"]["enum"].append("wrong_public_content")
    return schema


def build_search_request(content, store, *, original_png=None, detail_plan=None):
    if detail_plan and (original_png is None or detail_plan['source_sha256'] != sha256(original_png).hexdigest()):
        raise ValueError('image_input.detail_source_mismatch')
    regions = detail_plan['regions'] if detail_plan else ()
    inputs = image_inputs(content, original_png, detail_regions=regions) if original_png is not None else None
    base = build_image_request(content, store, original_content=original_png)
    if regions:
        from .graph_details import detail_crops
        images = list(base.images)
        for view, pixels in detail_crops(original_png, regions):
            artifact = store.put_bytes(kind='search_graph_detail', content=pixels, media_type='image/png', suffix='.png')
            images.append(MultimodalProviderImage(view['image_id'], 'page-1', 'zoom', artifact, pixels,
                                                   view['width'], view['height']))
        base = replace(base, images=tuple(images))
    payload = {"response_schema": candidate_schema(), "math_expression_catalog": contracts.expression_catalog()}
    if inputs:
        payload["image_inputs"] = inputs
    if detail_plan:
        payload['detail_reading'] = detail_plan
    return replace(
        base,
        contract_version=EXTRACTION_CONTRACT,
        contract_schema=candidate_schema(),
        prompt=MultimodalExtractionPrompt(
            contracts.SYSTEM + "\n\n" + PUBLIC_PROMPT_PATH.read_text(encoding="utf-8") +
            ("\n\n" + IMAGE_VIEWS_PROMPT if inputs else "") + ("\n\n" + DETAIL_VIEWS_PROMPT if detail_plan else ""),
            json.dumps(payload, ensure_ascii=False),
            "对照完整题图，提取数学题意和可公开的完整题目内容。只返回指定 JSON。",
        ),
    )


class SearchStageOneContract(GraphStageOneContract):
    def validate_request(self, request, registry, mode):
        if registry or request.contract_version != EXTRACTION_CONTRACT or request.contract_schema != candidate_schema():
            raise WorkflowStop("workflow.unsupported_or_stale_contract")

    def schema(self):
        return candidate_schema()

    def frozen_files(self):
        files = super().frozen_files()
        for path in (PUBLIC_SCHEMA_PATH, PUBLIC_PROMPT_PATH, Path(__file__).with_name("identity.py"),
                     Path(__file__).with_name('reviewed_figures.py'), Path(__file__).with_name('figures.py'),
                     Path(__file__).with_name('question_image.py'),
                     Path(__file__).with_name('graph_details.py'),
                     Path(__file__).with_name("stage_one.py"), __file__):
            path = Path(path)
            files[str(path.relative_to(contracts.ROOT))] = sha256(path.read_bytes()).hexdigest()
        return files

    def parse(self, raw, *, problem_id, source_hash, registry, store):
        try:
            candidate = strict_json(raw)
        except (ValueError, RecursionError) as exc:
            return {"contract": EXTRACTION_CONTRACT, "contract_valid": False,
                    "reports": {"json": {"ok": False, "issues": [str(exc)]}}}
        parsed = validate_candidate(mathematical_candidate(candidate))
        parsed.update(contract=EXTRACTION_CONTRACT, revision=revision(candidate),
                      binding={"problem_id": problem_id, "source_sha256": source_hash})
        errors = list(Draft202012Validator(candidate_schema()).iter_errors(candidate))
        issues = [{"path": "/" + "/".join(map(str, error.absolute_path)), "code": "schema.invalid", "message": error.message}
                  for error in errors[:32]]
        if not errors:
            issues.extend({"path": path, "code": "schema.invalid", "message": message}
                          for path, message in public_structure_errors(candidate))
        if issues:
            parsed["contract_valid"] = False
            parsed["reports"]["ir"]["ok"] = False
            parsed["reports"]["ir"].setdefault("issues", []).extend(issues)
        if store:
            store.put_bytes(kind="search_stage_one_raw", content=raw.encode("utf-8"), media_type="text/plain", suffix=".txt")
            store.put_json(kind="search_stage_one_validation", payload=parsed)
        return parsed

    def request_for(self, base, stage, candidate, registry, diagnostics=(), feedback=(), *, validation=None):
        outgoing = super().request_for(base, stage, candidate, registry, diagnostics, feedback, validation=validation)
        schema = review_schema() if stage == "review" else candidate_schema()
        payload = json.loads(outgoing.prompt.user_prefix)
        payload["response_schema"] = schema
        inputs = json.loads(base.prompt.user_prefix).get("image_inputs")
        detail_plan = json.loads(base.prompt.user_prefix).get('detail_reading')
        if inputs:
            payload["image_inputs"] = inputs
        if detail_plan:
            payload['detail_reading'] = detail_plan
        return replace(outgoing, contract_version=REVIEW_CONTRACT if stage == "review" else EXTRACTION_CONTRACT,
                       contract_schema=schema,
                       prompt=MultimodalExtractionPrompt(
                           outgoing.prompt.system + "\n\n" + PUBLIC_PROMPT_PATH.read_text(encoding="utf-8") +
                           ("\n\n" + IMAGE_VIEWS_PROMPT if inputs else "") + ("\n\n" + DETAIL_VIEWS_PROMPT if detail_plan else ""),
                           json.dumps(payload, ensure_ascii=False), outgoing.prompt.user_suffix))

    def validate_review(self, raw, candidate):
        review = strict_json(raw)
        Draft202012Validator(review_schema()).validate(review)
        for finding in review["findings"]:
            path, kind = finding["path"], finding["kind"]
            public = path == "/public_content" or path.startswith("/public_content/")
            if public != (kind == "wrong_public_content"):
                raise ValueError("review.invalid_public_pointer")
            if not public and not (path == "/original_text" or path == "/root" or path.startswith("/root/")):
                raise ValueError("review.invalid_pointer")
            if kind == "wrong_transcription" and path != "/original_text":
                raise ValueError("review.invalid_transcription_pointer")
            value = pointer(candidate, path)
            # A source-only editorial label cannot be an offending substring of
            # a public field which does not contain it. Reject the misplaced
            # finding and request fresh source review; never mark it confirmed.
            excerpt = finding.get("source_excerpt", "")
            if (kind == "wrong_public_content" and path.endswith("/statement")
                    and isinstance(value, str)
                    and re.fullmatch(r"[【\[（(]?\s*(?:例题|例|变式(?:训练|练习)?|练习题|练习)\s*"
                                     r"(?:[1-9][0-9]{0,2}|[一二三四五六七八九十]{1,3})\s*[】\]）)]?", excerpt.strip())):
                normalize = lambda text: re.sub(r"[\s【】\[\]（）()]", "", text)
                if normalize(excerpt) not in normalize(value):
                    raise ValueError("review.source_label_not_at_public_pointer")
        return review

    def repair_diagnostics(self, current, proposed, diagnostics):
        mathematical = [item for item in diagnostics if not item["path"].startswith("/public_content")]
        errors = super().repair_diagnostics(mathematical_candidate(current), mathematical_candidate(proposed), mathematical)
        grants = [item["path"] for item in diagnostics
                  if item.get("action") == "repair" and item["path"].startswith("/public_content")]
        for path in changed_paths(current.get("public_content"), proposed.get("public_content"), "/public_content"):
            if not any(path == grant or path.startswith(grant + "/") for grant in grants):
                errors.append({"code": "repair.outside_authorized_path", "path": path,
                               "message": "仅可修改诊断明确授权的公开题目字段，不可顺带改变其他题意。"})
        return errors

    def result_fields(self, current):
        return {"output_contract": EXTRACTION_CONTRACT}
