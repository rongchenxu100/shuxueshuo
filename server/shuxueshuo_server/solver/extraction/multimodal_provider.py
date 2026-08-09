"""Doubao multimodal provider contract for F3 problem extraction."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, ClassVar, Literal, Mapping, Protocol, Sequence

from shuxueshuo_server.solver.extraction.context import ExtractionArtifactRef
from shuxueshuo_server.solver.extraction.multimodal_evidence import (
    ExtractionArtifactReader,
    MultimodalEvidencePack,
)
from shuxueshuo_server.solver.extraction.problem_domain import (
    PROBLEM_DOMAIN_CONTRACT,
    PROBLEM_REPAIR_CONTRACT,
    ProblemDraft,
    ProblemValidationIssue,
    problem_domain_response_format,
    problem_repair_response_format,
)
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.runtime.config import (
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_DOUBAO_MODEL,
)


MULTIMODAL_PROVIDER_NAME = "doubao"
DEEPSEEK_TEXT_PROVIDER_NAME = "deepseek"
MULTIMODAL_PASS1_THINKING_MODE: Literal["disabled"] = "disabled"
MULTIMODAL_RETRY_THINKING_MODE: Literal["enabled"] = "enabled"
MULTIMODAL_RETRY_REASONING_EFFORT: Literal["low"] = "low"
MULTIMODAL_MAX_OUTPUT_TOKENS = 4_096

PASS1_SYSTEM_PROMPT = """你是数学题图片到 Problem 领域图的多模态提取器。
完整题目图片是语义权威，OCR仅作辅助；忽略学生答案、演算、批注和辅助线。
只输出严格匹配 response_format 的 JSON，不要解释、答案、解法、步骤或 Solver/Planner 字段。关闭顶层 root 对象后立即结束输出，不得追加说明、注释或重复括号。
顶层形状固定为 {"schema_version":"problem-domain/v1","problem_id":"...","family_id":"...","source":{...},"root":{...}}；完整字段、required、union 和 additionalProperties 约束以 response_format JSON Schema 为准。
输出只含题面可见语义：嵌套 scope、实体、事实和原子目标。代码只会规范化题面已引用的坐标原点 O、父子 scope 中同 kind+label 的重复身份，以及 x_range、minimum_value_given、square_center 已明确表达的等价 primitive fact；不会推导新数学事实或替换 family。
结构引用使用当前 scope 到祖先的词法 local id；Symbol 也可使用同词法范围内唯一的题面标签。禁止 sibling 引用和 ancestor 同名遮蔽。
Entity只表达身份；坐标、构造、从属和等量关系只写 Fact，禁止双写。
线段、射线、角和长度表达式优先使用 schema 的值对象；只有题面赋予独立身份时才声明 Entity。
每个独立求值对象输出一个 Goal。未命名对象使用角色 id，例如 vertex，不猜字母。
family_id 由你选择；必须满足 family_catalog 的 use_when、required_source_primitives、conditional_source_requirements，并避开 do_not_use_when。
problem_id 必须逐字复制请求值。"""

REPAIR_SYSTEM_PROMPT = """你修复一个已建立的数学题 ProblemDraft。
完整题图仍是语义权威。只输出严格匹配 response_format 的 problem-repair/v1 JSON。
顶层形状固定为 {"schema_version":"problem-repair/v1","base_revision_id":"...","replacements":[],"additions":[],"removals":[]}；完整 operation 字段和 value union 以 response_format JSON Schema 为准。
只能修改 repair cone：verified/frozen 单元只读；禁止输出整题、JSON Patch、答案、解法或解释。
replacement 保持 unit kind 和 owner scope；addition 写入指定 scope；removal 只能针对当前 issue 授权的单元。
family 只能用 unit_id=family 的 replacement 修改，代码不会自动换 family。"""

DOMAIN_RULES = """领域约束：
1. 根 scope 通常为 problem；每个 scope 保存对应印刷 source_text，children 保持题面顺序。
2. scope/entity id 由模型给出；Fact/Goal 不输出 id，代码分配稳定 unit id。
3. 表达式使用显式 * 和 **，其中自由符号写题面标签（如 x、a），并确保该标签对应当前 scope 或祖先中唯一可见的 Symbol。独立范围写 {"kind":"symbol_constraint","symbol":"实体id","operator":">","value":"0"}；链式区间拆成多条。若 point_on_curve_with_x 已写严格 x_range，则不重复写有限端约束，代码会等价展开；不得输出 n<+inf 或 n>-inf 这类恒真约束。比较符号只能放在 operator 字段，禁止 operator=in 或把 ">" 当字段名。
4. 仅当题面文字、Fact 或 Goal 实际引用坐标原点 O 时，才在根 scope 声明一次 point O 并写 point_construction(origin)，所有子问复用；不得仅因出现坐标系或抛物线而补 O。
5. 同一公共抛物线只声明一次；子问给定系数使用 local symbol_value，不复制闭合函数。
6. point_construction 按 schema 提供 owner/vector/x_expression。vertex、各类 intercept 和 curve_at_x 已包含其构造归属，不再重复 point_on_curve；“抛物线对称轴与 x 轴的交点”直接写 axis_x_intercept，不拆成两个 point_on_axis。只有题面另行声明的曲线、轴、线段或射线成员关系才写对应 Fact。
7. minimum_target 保存完整带权 LengthSum；题面直接给出该最小值时写 minimum_value_given。同一 scope 通过该条件反求 parameter_value 时，或已输出 minimum_value goal 时，代码会为同一 expression 等价补出 minimum_target，禁止重复抄写。
8. source_text 忠实转录印刷题面，不概括，不加入学生书写或推导结果。
9. 每个表达式自由符号都必须有可见 Symbol；结构字段优先引用 local id，表达式直接使用题面符号标签。
10. 父 scope 已有相同 kind+label 的实体时，子 scope 必须复用祖先 local id；各子问不同的取值或约束只写在本 scope 的 Fact 中，不复制 Entity。此规则不跨 sibling 合并局部对象。
11. 每个 Entity 必须被另一个 Entity、Fact、Goal 或表达式引用。OM、BN、BC 这类仅作为长度或成员关系出现的线段直接写 SegmentTerm，不声明 named_line；named_line 只用于题面明确称为“直线”的独立对象。
12. Symbol role：自变量用 function_variable；抛物线系数通常用 quadratic_coefficient；动点坐标参数用 dynamic_parameter；明确作为本题主反求参数时可用 primary_parameter；不要把普通系数泛写成 parameter，也不要为函数等号左侧的 y 单独建 Symbol。
13. sibling 各自重新给出同名点（例如两问分别写 A(-1,0)）时，在每个 sibling 分别声明 A；只有题面在共同父级先引入对象时才由 children 共享。
14. 题面写 M(f(t),y_M) 且只说明 M 在曲线上时，用 curve_at_x 表达；若 y_M 后续未参与任何关系，不为这个占位纵坐标创建 Symbol。题面写 N(n,0) 是 x 轴或其正半轴上的点时，写 point_coordinate、point_on_axis 和有限端 symbol_constraint；除非题面明确另说 N 在曲线上，否则不得写 point_on_curve_with_x。
15. named_ray 只用于题面明确出现“射线”，named_line 只用于题面明确出现“直线”。普通 DM、MN、BC 一律使用 SegmentTerm。正方形方位使用结构化 orientation，例如 {"point":"G","relation":"below_x_axis"}；不要再重复写 quadrant_membership。square_center 已完整表达中心位于两条对角线，代码会物化对应 point_on_segment，不要重复输出。
16. polygon 必须按题面顺序填写 vertices，例如正方形 AEKG 写 ["A","E","K","G"]；不得只输出 id、kind 和 label。"""


def problem_domain_family_catalog() -> tuple[dict[str, object], ...]:
    """Expose only source-visible family selection guidance to the model."""

    allowed = (
        "family_id",
        "title",
        "use_when",
        "required_source_primitives",
        "do_not_use_when",
    )
    return tuple(
        {
            **{
                key: payload[key]
                for key in allowed
                if key in payload
            },
            "conditional_source_requirements": [
                requirement
                for preflight in family.runtime_preflights
                if (requirement := preflight.source_authoring_payload()) is not None
            ],
        }
        for family in sorted(
            DEFAULT_FAMILY_REGISTRY.families,
            key=lambda item: item.family_id,
        )
        for payload in (family.authoring_guidance_payload(),)
    )


class OpenAIClientFactory(Protocol):
    def __call__(self, **kwargs: Any) -> Any: ...


def _default_client_factory(**kwargs: Any) -> Any:
    from openai import OpenAI

    return OpenAI(**kwargs)


@dataclass(frozen=True)
class MultimodalProviderImage:
    image_id: str
    page_id: str
    role: Literal["primary", "zoom"]
    artifact: ExtractionArtifactRef
    content: bytes = field(repr=False)
    width: int = 0
    height: int = 0

    def redacted_payload(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "page_id": self.page_id,
            "role": self.role,
            "artifact_id": self.artifact.artifact_id,
            "sha256": self.artifact.sha256,
            "media_type": self.artifact.media_type,
            "byte_size": len(self.content),
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class MultimodalExtractionPrompt:
    system: str
    user_prefix: str
    user_suffix: str
    includes_images: bool = True

    @property
    def user_debug(self) -> str:
        separator = (
            "[完整题目图片按 page order 插入此处]"
            if self.includes_images
            else "[本次文本基线不发送图片]"
        )
        return f"{self.user_prefix}\n\n{separator}\n\n{self.user_suffix}"


@dataclass(frozen=True)
class MultimodalProviderRequest:
    evidence_pack: MultimodalEvidencePack
    prompt: MultimodalExtractionPrompt
    images: tuple[MultimodalProviderImage, ...]
    contract_version: Literal["problem-domain/v1", "problem-repair/v1"]
    contract_schema: Mapping[str, Any]
    response_format: Mapping[str, Any]
    thinking_mode: Literal["disabled", "enabled"] = (
        MULTIMODAL_PASS1_THINKING_MODE
    )
    reasoning_effort: Literal["low"] | None = None

    def thinking_payload(self) -> dict[str, Any]:
        return {"thinking": {"type": self.thinking_mode}}

    def redacted_payload(self) -> dict[str, Any]:
        payload = {
            "messages": [
                {"role": "system", "content": self.prompt.system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.prompt.user_prefix},
                        *[
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"artifact://{item.artifact.artifact_id}"
                                },
                                "image": item.redacted_payload(),
                            }
                            for item in self.images
                        ],
                        {"type": "text", "text": self.prompt.user_suffix},
                    ],
                },
            ],
            "temperature": 0,
            "response_format": dict(self.response_format),
            "contract_schema": dict(self.contract_schema),
            **self.thinking_payload(),
            "stream": True,
            "stream_options": {"include_usage": True},
            "tools": [],
            "max_tokens": MULTIMODAL_MAX_OUTPUT_TOKENS,
        }
        if self.reasoning_effort is not None:
            payload["reasoning_effort"] = self.reasoning_effort
        return payload

    def provider_messages(self) -> list[dict[str, Any]]:
        if not self.images:
            return [
                {"role": "system", "content": self.prompt.system},
                {
                    "role": "user",
                    "content": f"{self.prompt.user_prefix}\n\n{self.prompt.user_suffix}",
                },
            ]
        image_parts = []
        for item in self.images:
            media_type = item.artifact.media_type or "image/png"
            encoded = base64.b64encode(item.content).decode("ascii")
            image_parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{media_type};base64,{encoded}",
                    },
                }
            )
        return [
            {"role": "system", "content": self.prompt.system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": self.prompt.user_prefix},
                    *image_parts,
                    {"type": "text", "text": self.prompt.user_suffix},
                ],
            },
        ]


@dataclass(frozen=True)
class ProviderSubAttempt:
    provider_attempt: int
    status: str
    response_model: str | None
    usage: Mapping[str, Any] | None
    finish_reason: str | None
    visible_content: bool
    latency_ms: int
    error_code: str | None = None
    error_message: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "provider_attempt": self.provider_attempt,
            "status": self.status,
            "response_model": self.response_model,
            "usage": dict(self.usage) if self.usage is not None else None,
            "finish_reason": self.finish_reason,
            "visible_content": self.visible_content,
            "latency_ms": self.latency_ms,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


@dataclass(frozen=True)
class MultimodalProviderResponse:
    text: str
    raw_payload: Mapping[str, Any]
    request_model: str
    response_model: str | None
    usage: Mapping[str, Any] | None
    finish_reason: str | None
    provider_attempts: tuple[ProviderSubAttempt, ...]
    latency_ms: int
    thinking_mode: Literal["disabled", "enabled"]
    reasoning_effort: Literal["low"] | None
    contract_version: str = PROBLEM_DOMAIN_CONTRACT
    provider_name: str = MULTIMODAL_PROVIDER_NAME

    def metadata_payload(self) -> dict[str, Any]:
        stream_terminated_at_json = bool(
            self.raw_payload.get("stream_terminated_at_json", False)
        )
        return {
            "provider": self.provider_name,
            "request_model": self.request_model,
            "response_model": self.response_model,
            "usage": dict(self.usage) if self.usage is not None else None,
            "usage_complete": self.usage is not None,
            "finish_reason": self.finish_reason,
            "stream_terminated_at_json": stream_terminated_at_json,
            "received_output_characters": len(self.text),
            "thinking_mode": self.thinking_mode,
            "reasoning_effort": self.reasoning_effort,
            "response_format": self.contract_version,
            "temperature": 0,
            "max_output_tokens": MULTIMODAL_MAX_OUTPUT_TOKENS,
            "provider_attempts": [
                item.to_payload() for item in self.provider_attempts
            ],
            "latency_ms": self.latency_ms,
        }


@dataclass(frozen=True)
class _StreamCompletion:
    text: str
    raw_payload: Mapping[str, Any]
    response_model: str | None
    usage: Mapping[str, Any] | None
    finish_reason: str | None


class MultimodalProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        result: str,
        provider_attempts: Sequence[ProviderSubAttempt] = (),
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.result = result
        self.provider_attempts = tuple(provider_attempts)


def build_multimodal_provider_request(
    pack: MultimodalEvidencePack,
    *,
    artifact_reader: ExtractionArtifactReader,
    expected_problem_id: str,
    current_draft: ProblemDraft | None = None,
    validation_issues: Sequence[ProblemValidationIssue] = (),
    zoom_images: Sequence[MultimodalProviderImage] = (),
    semantic_attempt_number: int = 1,
    include_images: bool = True,
    response_format_mode: Literal["json_schema", "json_object"] = "json_schema",
) -> MultimodalProviderRequest:
    pack.validate()
    if semantic_attempt_number < 1:
        raise ValueError("semantic_attempt_number must be positive")
    images = (
        tuple(
            MultimodalProviderImage(
                image_id=item.image_id,
                page_id=item.page_id,
                role="primary",
                artifact=item.artifact,
                content=artifact_reader.read_bytes(item.artifact),
                width=item.width,
                height=item.height,
            )
            for item in pack.images
        )
        if include_images
        else ()
    )
    if include_images and (
        not images
        or any(item.artifact.kind != "selection_crop" for item in images)
    ):
        raise MultimodalProviderError(
            "extraction.multimodal_full_image_missing",
            "every request requires complete selection images",
            result="failed",
        )
    if include_images and any(item.role != "zoom" for item in zoom_images):
        raise MultimodalProviderError(
            "extraction.multimodal_zoom_invalid",
            "retry images must have role=zoom",
            result="failed",
        )
    contract_version = (
        PROBLEM_REPAIR_CONTRACT
        if current_draft is not None
        else PROBLEM_DOMAIN_CONTRACT
    )
    schema_response_format = (
        problem_repair_response_format()
        if current_draft is not None
        else problem_domain_response_format()
    )
    if response_format_mode == "json_schema":
        response_format = schema_response_format
        schema_for_prompt: Mapping[str, Any] | None = None
    else:
        response_format = {"type": "json_object"}
        schema_for_prompt = schema_response_format["json_schema"]["schema"]
    return MultimodalProviderRequest(
        evidence_pack=pack,
        prompt=build_multimodal_prompt(
            pack,
            expected_problem_id=expected_problem_id,
            current_draft=current_draft,
            validation_issues=validation_issues,
            include_images=include_images,
            schema_for_prompt=schema_for_prompt,
        ),
        images=(*images, *(zoom_images if include_images else ())),
        contract_version=contract_version,
        contract_schema=schema_response_format["json_schema"]["schema"],
        response_format=response_format,
        thinking_mode=(
            MULTIMODAL_RETRY_THINKING_MODE
            if current_draft is not None
            else MULTIMODAL_PASS1_THINKING_MODE
        ),
        reasoning_effort=(
            MULTIMODAL_RETRY_REASONING_EFFORT
            if current_draft is not None
            else None
        ),
    )


def build_multimodal_prompt(
    pack: MultimodalEvidencePack,
    *,
    expected_problem_id: str,
    current_draft: ProblemDraft | None = None,
    validation_issues: Sequence[ProblemValidationIssue] = (),
    include_images: bool = True,
    schema_for_prompt: Mapping[str, Any] | None = None,
) -> MultimodalExtractionPrompt:
    pack.validate()
    user_suffix = "辅助观察：\n" + json.dumps(
        pack.prompt_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    user_suffix += "\n\n本次 problem_id：" + expected_problem_id
    user_suffix += "\nfamily_catalog：" + json.dumps(
        problem_domain_family_catalog(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    user_suffix += "\n\n" + DOMAIN_RULES
    if schema_for_prompt is not None:
        user_suffix += "\n\n完整 JSON Schema（必须逐字段遵守）：\n" + json.dumps(
            schema_for_prompt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    if current_draft is not None:
        user_suffix += "\n\n当前 Draft（value 是领域 wire，unit_id 由代码分配）：\n" + json.dumps(
            _compact_draft_for_repair(current_draft),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        user_suffix += "\nValidator root issues：\n" + json.dumps(
            [_compact_retry_issue(item) for item in validation_issues],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return MultimodalExtractionPrompt(
        system=(
            REPAIR_SYSTEM_PROMPT
            if current_draft is not None
            else PASS1_SYSTEM_PROMPT
        ),
        user_prefix=(
            (
                "请按 page order 阅读下面的完整题目图片。图片覆盖全部题干和小问；"
                "辅助OCR可能有误，冲突时以图片为准。"
            )
            if include_images
            else (
                "本次是无图片文本基线。请仅依据下面的可信印刷OCR与可靠公式提取题目；"
                "不得根据学生笔迹或常见题型补写OCR中不存在的题面。"
            )
        ),
        user_suffix=user_suffix,
        includes_images=include_images,
    )


def _compact_retry_issue(item: ProblemValidationIssue) -> dict[str, Any]:
    return {
        "code": item.code,
        "unit_ids": list(item.unit_ids),
        "dependency_unit_ids": list(item.dependency_unit_ids),
        "message": item.message,
        "repair_action": item.repair_action,
        "region_refs": list(item.region_refs),
    }


def _compact_draft_for_repair(draft: ProblemDraft) -> dict[str, Any]:
    def scope_payload(scope: Any) -> dict[str, Any]:
        return {
            "unit_id": scope.unit_id,
            "value": {
                "id": scope.local_id,
                "label": scope.label,
                "source_text": list(scope.source_text),
            },
            "entities": [
                {"unit_id": item.unit_id, "value": item.wire_payload()}
                for item in scope.entities
            ],
            "facts": [
                {"unit_id": item.unit_id, "value": item.wire_payload()}
                for item in scope.facts
            ],
            "goals": [
                {"unit_id": item.unit_id, "value": item.wire_payload()}
                for item in scope.goals
            ],
            "children": [scope_payload(item) for item in scope.children],
        }

    return {
        "revision_id": draft.revision_id,
        "family": {"unit_id": "family", "value": {"family_id": draft.graph.family_id}},
        "root": scope_payload(draft.graph.root_scope),
        "frozen_unit_ids": list(draft.frozen_unit_ids),
        "repairable_unit_ids": list(draft.repairable_unit_ids),
    }


@dataclass
class DoubaoMultimodalExtractionProvider:
    provider_name: ClassVar[str] = MULTIMODAL_PROVIDER_NAME
    supports_images: ClassVar[bool] = True
    response_format_mode: ClassVar[Literal["json_schema"]] = "json_schema"
    api_key: str
    base_url: str
    model: str
    client_factory: OpenAIClientFactory = _default_client_factory
    request_timeout: float = 120.0
    sleeper: Callable[[float], None] = time.sleep
    last_provider_attempts: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
    )
    last_usage: dict[str, Any] | None = field(default=None, init=False)
    last_response_model: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not self.api_key or not self.base_url or not self.model:
            raise MultimodalProviderError(
                "extraction.multimodal_provider_config_invalid",
                "DOUBAO_API_KEY, DOUBAO_BASE_URL and DOUBAO_MODEL are required",
                result="failed",
            )
        if self.model != DEFAULT_DOUBAO_MODEL:
            raise MultimodalProviderError(
                "extraction.multimodal_provider_config_invalid",
                f"F3 requires {DEFAULT_DOUBAO_MODEL}, got {self.model}",
                result="failed",
            )
        if self.request_timeout <= 0:
            raise MultimodalProviderError(
                "extraction.multimodal_provider_config_invalid",
                "provider request timeout must be positive",
                result="failed",
            )
        self._client = self.client_factory(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.request_timeout,
            max_retries=0,
        )

    def complete(
        self,
        request: MultimodalProviderRequest,
    ) -> MultimodalProviderResponse:
        attempts: list[ProviderSubAttempt] = []
        started = perf_counter()
        for provider_attempt in range(1, 3):
            attempt_started = perf_counter()
            try:
                options: dict[str, Any] = {
                    "model": self.model,
                    "messages": request.provider_messages(),
                    "temperature": 0,
                    "response_format": dict(request.response_format),
                    "extra_body": request.thinking_payload(),
                    "max_tokens": MULTIMODAL_MAX_OUTPUT_TOKENS,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                    "timeout": self.request_timeout,
                }
                if request.reasoning_effort is not None:
                    options["reasoning_effort"] = request.reasoning_effort
                stream = self._client.chat.completions.create(**options)
                completion = _consume_first_json_object(
                    stream,
                    deadline=attempt_started + self.request_timeout,
                )
            except Exception as exc:  # provider SDK exceptions vary by version
                error_code, result, retryable = _classify_provider_exception(exc)
                attempts.append(
                    ProviderSubAttempt(
                        provider_attempt=provider_attempt,
                        status="error",
                        response_model=None,
                        usage=None,
                        finish_reason=None,
                        visible_content=False,
                        latency_ms=_elapsed_ms(attempt_started),
                        error_code=error_code,
                        error_message=str(exc),
                    )
                )
                self._remember(attempts)
                if retryable and provider_attempt == 1:
                    self.sleeper(0.25)
                    continue
                raise MultimodalProviderError(
                    error_code,
                    str(exc),
                    result=result,
                    provider_attempts=attempts,
                ) from exc
            raw_payload = completion.raw_payload
            text = completion.text
            usage = completion.usage
            response_model = completion.response_model
            finish_reason = completion.finish_reason
            attempts.append(
                ProviderSubAttempt(
                    provider_attempt=provider_attempt,
                    status="completed",
                    response_model=response_model,
                    usage=usage,
                    finish_reason=finish_reason,
                    visible_content=bool(text.strip()),
                    latency_ms=_elapsed_ms(attempt_started),
                )
            )
            self._remember(attempts)
            if not text.strip():
                raise MultimodalProviderError(
                    "extraction.multimodal_provider_empty_response",
                    "provider returned no visible JSON content",
                    result="empty_response",
                    provider_attempts=attempts,
                )
            return MultimodalProviderResponse(
                text=text,
                raw_payload=raw_payload,
                request_model=self.model,
                response_model=response_model,
                usage=_sum_usage(attempts),
                finish_reason=finish_reason,
                provider_attempts=tuple(attempts),
                latency_ms=_elapsed_ms(started),
                thinking_mode=request.thinking_mode,
                reasoning_effort=request.reasoning_effort,
                contract_version=request.contract_version,
                provider_name=self.provider_name,
            )
        raise AssertionError("provider retry loop exhausted")

    def _remember(self, attempts: Sequence[ProviderSubAttempt]) -> None:
        self.last_provider_attempts = tuple(item.to_payload() for item in attempts)
        self.last_usage = _sum_usage(attempts)
        self.last_response_model = next(
            (
                item.response_model
                for item in reversed(tuple(attempts))
                if item.response_model is not None
            ),
            None,
        )


@dataclass
class DeepSeekTextProblemDomainProvider:
    """Text-only comparison provider using trusted F2 OCR and JSON Output."""

    provider_name: ClassVar[str] = DEEPSEEK_TEXT_PROVIDER_NAME
    supports_images: ClassVar[bool] = False
    response_format_mode: ClassVar[Literal["json_object"]] = "json_object"

    api_key: str
    base_url: str
    model: str = DEFAULT_DEEPSEEK_MODEL
    client_factory: OpenAIClientFactory = _default_client_factory
    request_timeout: float = 300.0
    sleeper: Callable[[float], None] = time.sleep
    last_provider_attempts: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
    )
    last_usage: dict[str, Any] | None = field(default=None, init=False)
    last_response_model: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not self.api_key or not self.base_url or not self.model:
            raise MultimodalProviderError(
                "extraction.multimodal_provider_config_invalid",
                "DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL and DEEPSEEK_MODEL are required",
                result="failed",
            )
        self._client = self.client_factory(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.request_timeout,
            max_retries=0,
        )

    def complete(
        self,
        request: MultimodalProviderRequest,
    ) -> MultimodalProviderResponse:
        if request.images:
            raise MultimodalProviderError(
                "extraction.multimodal_provider_contract_unsupported",
                "DeepSeek text baseline must not receive image inputs",
                result="failed",
            )
        attempts: list[ProviderSubAttempt] = []
        started = perf_counter()
        for provider_attempt in range(1, 3):
            attempt_started = perf_counter()
            try:
                options: dict[str, Any] = {
                    "model": self.model,
                    "messages": request.provider_messages(),
                    "response_format": {"type": "json_object"},
                    "extra_body": request.thinking_payload(),
                    "max_tokens": MULTIMODAL_MAX_OUTPUT_TOKENS,
                    "stream": False,
                    "timeout": self.request_timeout,
                }
                if request.thinking_mode == "disabled":
                    options["temperature"] = 0
                if request.reasoning_effort is not None:
                    options["reasoning_effort"] = request.reasoning_effort
                response = self._client.chat.completions.create(**options)
            except Exception as exc:  # provider SDK exceptions vary by version
                error_code, result, retryable = _classify_provider_exception(exc)
                attempts.append(
                    ProviderSubAttempt(
                        provider_attempt=provider_attempt,
                        status="error",
                        response_model=None,
                        usage=None,
                        finish_reason=None,
                        visible_content=False,
                        latency_ms=_elapsed_ms(attempt_started),
                        error_code=error_code,
                        error_message=str(exc),
                    )
                )
                self._remember(attempts)
                if retryable and provider_attempt == 1:
                    self.sleeper(0.25)
                    continue
                raise MultimodalProviderError(
                    error_code,
                    str(exc),
                    result=result,
                    provider_attempts=attempts,
                ) from exc
            raw_payload = _provider_payload(response)
            choice = response.choices[0]
            content = choice.message.content
            text = "" if content is None else str(content)
            usage = _usage_payload(getattr(response, "usage", None))
            response_model = _optional_string(getattr(response, "model", None))
            finish_reason = _optional_string(getattr(choice, "finish_reason", None))
            attempts.append(
                ProviderSubAttempt(
                    provider_attempt=provider_attempt,
                    status="completed",
                    response_model=response_model,
                    usage=usage,
                    finish_reason=finish_reason,
                    visible_content=bool(text.strip()),
                    latency_ms=_elapsed_ms(attempt_started),
                )
            )
            self._remember(attempts)
            if not text.strip():
                if provider_attempt == 1:
                    self.sleeper(0.25)
                    continue
                raise MultimodalProviderError(
                    "extraction.multimodal_provider_empty_response",
                    "provider returned no visible JSON content",
                    result="empty_response",
                    provider_attempts=attempts,
                )
            return MultimodalProviderResponse(
                text=text,
                raw_payload=raw_payload,
                request_model=self.model,
                response_model=response_model,
                usage=_sum_usage(attempts),
                finish_reason=finish_reason,
                provider_attempts=tuple(attempts),
                latency_ms=_elapsed_ms(started),
                thinking_mode=request.thinking_mode,
                reasoning_effort=request.reasoning_effort,
                contract_version=request.contract_version,
                provider_name=self.provider_name,
            )
        raise AssertionError("provider retry loop exhausted")

    def _remember(self, attempts: Sequence[ProviderSubAttempt]) -> None:
        self.last_provider_attempts = tuple(item.to_payload() for item in attempts)
        self.last_usage = _sum_usage(attempts)
        self.last_response_model = next(
            (
                item.response_model
                for item in reversed(tuple(attempts))
                if item.response_model is not None
            ),
            None,
        )


def _consume_first_json_object(stream: Any, *, deadline: float) -> _StreamCompletion:
    """Consume a provider stream only until one complete JSON object exists."""

    parts: list[str] = []
    response_model: str | None = None
    usage: Mapping[str, Any] | None = None
    provider_finish_reason: str | None = None
    completed_json: str | None = None
    trailing_characters = 0
    try:
        if perf_counter() >= deadline:
            raise TimeoutError("provider stream exceeded the request wall-clock deadline")
        for chunk in stream:
            if perf_counter() >= deadline:
                raise TimeoutError(
                    "provider stream exceeded the request wall-clock deadline"
                )
            chunk_model = _optional_string(_payload_field(chunk, "model"))
            if chunk_model is not None:
                response_model = chunk_model
            chunk_usage = _usage_payload(_payload_field(chunk, "usage"))
            if chunk_usage is not None:
                usage = chunk_usage
            choices = _payload_field(chunk, "choices") or ()
            if not choices:
                continue
            choice = choices[0]
            finish_reason = _optional_string(
                _payload_field(choice, "finish_reason")
            )
            if finish_reason is not None:
                provider_finish_reason = finish_reason
            delta = _payload_field(choice, "delta")
            content = _payload_field(delta, "content") if delta is not None else None
            if content is not None:
                parts.append(str(content))
            received = "".join(parts)
            completed_json = _first_complete_json_object(received)
            if completed_json is not None:
                trailing_characters = max(0, len(received.strip()) - len(completed_json))
                break
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()

    text = completed_json if completed_json is not None else "".join(parts)
    finish_reason = (
        "json_complete" if completed_json is not None else provider_finish_reason
    )
    raw_payload = {
        "model": response_model,
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"content": text},
            }
        ],
        "usage": dict(usage) if usage is not None else None,
        "stream_terminated_at_json": completed_json is not None,
        "discarded_trailing_characters": trailing_characters,
    }
    return _StreamCompletion(
        text=text,
        raw_payload=raw_payload,
        response_model=response_model,
        usage=usage,
        finish_reason=finish_reason,
    )


def _first_complete_json_object(value: str) -> str | None:
    start = len(value) - len(value.lstrip())
    if start >= len(value) or value[start] != "{":
        return None
    try:
        payload, end = json.JSONDecoder().raw_decode(value, start)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    return value[start:end]


def _payload_field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _classify_provider_exception(exc: Exception) -> tuple[str, str, bool]:
    status = getattr(exc, "status_code", None)
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    if status == 429 or "ratelimit" in name or "rate limit" in message:
        return "extraction.multimodal_provider_rate_limited", "rate_limited", True
    if "timeout" in name or isinstance(exc, TimeoutError):
        return "extraction.multimodal_provider_timeout", "timeout", True
    if isinstance(status, int) and status >= 500:
        return "extraction.multimodal_provider_unavailable", "failed", True
    if status == 400:
        return (
            "extraction.multimodal_provider_contract_unsupported",
            "failed",
            False,
        )
    return "extraction.multimodal_provider_failed", "failed", False


def _provider_payload(response: Any) -> Mapping[str, Any]:
    if hasattr(response, "model_dump"):
        payload = response.model_dump(mode="json")
        if isinstance(payload, Mapping):
            return payload
    if isinstance(response, Mapping):
        return response
    return {
        "model": _optional_string(getattr(response, "model", None)),
        "choices": [
            {
                "finish_reason": _optional_string(
                    getattr(response.choices[0], "finish_reason", None)
                ),
                "content": _optional_string(response.choices[0].message.content),
            }
        ],
        "usage": _usage_payload(getattr(response, "usage", None)),
    }


def _usage_payload(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        payload = usage.model_dump(mode="json")
        return dict(payload) if isinstance(payload, Mapping) else None
    if isinstance(usage, Mapping):
        return dict(usage)
    result = {}
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = getattr(usage, name, None)
        if value is not None:
            result[name] = value
    return result or None


def _sum_usage(attempts: Sequence[ProviderSubAttempt]) -> dict[str, Any] | None:
    totals: dict[str, Any] = {}
    for attempt in attempts:
        if attempt.usage is None:
            continue
        for key, value in attempt.usage.items():
            if isinstance(value, (int, float)):
                totals[key] = totals.get(key, 0) + value
    return totals or None


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None
