"""Image extraction transports, request policies, and auditable provider outcomes."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field, replace
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
from .problem_domain_prompt_rules import DOMAIN_RULES
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
    contract_version: Literal["problem-domain/v1", "problem-repair/v1", "problem-source-review/v1"]
    contract_schema: Mapping[str, Any]
    response_format: Mapping[str, Any]
    thinking_mode: Literal["disabled", "enabled"] = (
        MULTIMODAL_PASS1_THINKING_MODE
    )
    reasoning_effort: Literal["low"] | None = None
    stream: bool = True
    max_tokens: int = MULTIMODAL_MAX_OUTPUT_TOKENS
    timeout: float | None = None
    image_detail: str | None = None
    model: str | None = None

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
                                    "url": f"artifact://{item.artifact.artifact_id}",
                                    **({"detail": self.image_detail} if self.image_detail else {})
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
            "stream": self.stream,
            "tools": [],
            "max_tokens": self.max_tokens,
        }
        if self.model is not None:
            payload["model"] = self.model
        if self.stream:
            payload["stream_options"] = {"include_usage": True}
        if self.timeout is not None:
            payload["timeout"] = self.timeout
        if self.thinking_mode == "enabled" and not self.stream:
            payload.pop("temperature", None)
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
                        **({"detail": self.image_detail} if self.image_detail else {}),
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
    raw_payload: Mapping[str, Any] | None = None

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
            **({"raw_payload": dict(self.raw_payload)} if self.raw_payload is not None else {}),
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
    transport: Mapping[str, Any] = field(default_factory=dict)

    def metadata_payload(self) -> dict[str, Any]:
        stream_terminated_at_json = bool(
            self.raw_payload.get("stream_terminated_at_json", False)
        )
        return {
            "provider": self.provider_name,
            "request_model": self.request_model,
            "response_model": self.response_model,
            "usage": dict(self.usage) if self.usage is not None else None,
            "usage_complete": self.usage is not None and all(a.usage is not None for a in self.provider_attempts),
            "finish_reason": self.finish_reason,
            "stream_terminated_at_json": stream_terminated_at_json,
            "received_output_characters": len(self.text),
            "thinking_mode": self.thinking_mode,
            "reasoning_effort": self.reasoning_effort,
            "response_format": self.contract_version,
            "temperature": 0,
            "max_output_tokens": MULTIMODAL_MAX_OUTPUT_TOKENS,
            **dict(self.transport),
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
class _DeepSeekChatProvider:
    """Shared non-streaming transport; subclasses own the input contract."""

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
        request = self.prepare_request(request)
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
                    "max_tokens": request.max_tokens,
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
            choice = response.choices[0] if response.choices else None
            content = choice.message.content if choice is not None else None
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
                    raw_payload=raw_payload,
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
                transport={"max_output_tokens": request.max_tokens, "timeout": self.request_timeout,
                           "stream": False, "temperature": None if request.thinking_mode == "enabled" else 0,
                           "transport_response_format": "json_object", "image_detail": request.image_detail},
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
class DeepSeekTextProblemDomainProvider(_DeepSeekChatProvider):
    """Explicit text-only comparison baseline; never selected by the vision factory."""

    def prepare_request(self, request):
        if request.images:
            raise MultimodalProviderError(
                "extraction.multimodal_provider_contract_unsupported",
                "DeepSeek text baseline must not receive image inputs", result="failed")
        return replace(request, stream=False, timeout=self.request_timeout)


@dataclass
class DeepSeekMultimodalExtractionProvider(_DeepSeekChatProvider):
    """DeepSeek vision, with identical policy for draft, patch and source review."""

    supports_images: ClassVar[bool] = True
    preserve_original_images: ClassVar[bool] = True
    model: str = "deepseek-flash"
    max_output_tokens: int = 16_384

    def __post_init__(self):
        if self.model != "deepseek-flash" or self.request_timeout <= 0 or self.max_output_tokens < 1:
            raise MultimodalProviderError("extraction.multimodal_provider_config_invalid",
                "vision requires deepseek-flash and positive timeout/token limits", result="failed")
        super().__post_init__()

    def prepare_request(self, request):
        from hashlib import sha256
        from io import BytesIO
        from PIL import Image

        def reject(reason):
            raise MultimodalProviderError("extraction.multimodal_image_invalid", reason, result="failed")

        if not request.images or not any(i.role == "primary" for i in request.images):
            reject("vision requires the complete question image")
        expected = [(i.page_id, i.artifact.sha256) for i in request.evidence_pack.images]
        actual = [(i.page_id, i.artifact.sha256) for i in request.images if i.role == "primary"]
        if actual != expected:
            reject("complete primary images must match evidence hashes and page order")
        if len(request.images) > 600:
            reject("too many images")
        for item in request.images:
            if not item.content or len(item.content) > 32 * 1024**2:
                reject("empty image or inline image exceeds 32 MiB")
            if sha256(item.content).hexdigest() != item.artifact.sha256:
                reject("image artifact hash mismatch")
            try:
                with Image.open(BytesIO(item.content)) as decoded:
                    width, height = decoded.size
                    mime = Image.MIME.get(decoded.format)
                    decoded.verify()
            except Exception:
                reject("image cannot be decoded")
            if mime != item.artifact.media_type or mime not in {"image/png", "image/jpeg", "image/webp"}:
                reject("unsupported or mismatched image media type")
            if (width, height) != (item.width, item.height):
                reject("image dimensions do not match artifact metadata")
            if max(width, height) > (4096 if len(request.images) >= 15 else 8192):
                reject("image dimensions exceed vision limit")
            try:
                with Image.open(BytesIO(item.content)) as decoded:
                    decoded.load()
            except Exception:
                reject("image pixel data cannot be decoded")
        prepared = replace(request, thinking_mode="enabled", reasoning_effort="low",
            response_format={"type": "json_object"}, stream=False, max_tokens=self.max_output_tokens,
            timeout=self.request_timeout, image_detail="high", model=self.model)
        # Check the encoded request, not only the compressed source file size.
        if len(json.dumps(prepared.provider_messages(), ensure_ascii=False).encode()) > 48 * 1024**2 - 1024:
            reject("encoded request exceeds 48 MiB")
        return prepared


def vision_effective_config(config):
    """Non-secret frozen transport policy, also used in dependency fingerprints."""
    if config.problem_vision_provider != "deepseek":
        raise ValueError("PROBLEM_VISION_PROVIDER must be deepseek; no automatic fallback")
    return {"provider": "deepseek", "model": config.deepseek_vision_model,
        "base_url": config.deepseek_vision_base_url, "thinking": {"type": "enabled"},
        "reasoning_effort": "low", "response_format": {"type": "json_object"},
        "stream": False, "max_tokens": config.deepseek_vision_max_tokens,
        "timeout": config.deepseek_vision_timeout, "image_detail": "high", "sdk_retries": 0}


def create_vision_provider(config, *, frozen_config=None, **kwargs):
    policy = frozen_config if frozen_config is not None else vision_effective_config(config)
    if (policy.get("provider") != "deepseek" or policy.get("thinking") != {"type": "enabled"}
        or policy.get("reasoning_effort") != "low" or policy.get("stream") is not False
        or policy.get("response_format") != {"type": "json_object"}
        or policy.get("sdk_retries") != 0 or policy.get("image_detail") != "high"):
        raise ValueError("extraction.rebuild_required: invalid frozen vision policy")
    return DeepSeekMultimodalExtractionProvider(api_key=config.deepseek_api_key or "",
        base_url=policy["base_url"], model=policy["model"], request_timeout=policy["timeout"],
        max_output_tokens=policy["max_tokens"], **kwargs)


def prepare_provider_request(provider, request):
    prepare = getattr(provider, "prepare_request", None)
    return prepare(request) if prepare is not None else request


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
                    getattr(response.choices[0], "finish_reason", None) if response.choices else None
                ),
                "content": _optional_string(response.choices[0].message.content) if response.choices else None,
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
