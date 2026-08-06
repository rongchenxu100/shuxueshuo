"""Doubao multimodal provider contract for F3 problem extraction."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, Mapping, Protocol, Sequence

from shuxueshuo_server.solver.extraction.context import ExtractionArtifactRef
from shuxueshuo_server.solver.extraction.multimodal_evidence import (
    ExtractionArtifactReader,
    MultimodalEvidencePack,
)
from shuxueshuo_server.solver.runtime.config import DEFAULT_DOUBAO_MODEL


MULTIMODAL_PROVIDER_NAME = "doubao"
MULTIMODAL_THINKING_MODE = "disabled"
MULTIMODAL_MAX_OUTPUT_TOKENS = 16384

SYSTEM_PROMPT = """你是数学题面多模态语义提取器。完整题目图片是第一手权威，OCR、公式和墨迹信息只作辅助。
只输出一个严格 JSON 对象，必须符合 problem-extraction-candidate-patch/v1。
完整、逐小问地提取题面中的 classification、transcription_lines 以及 scope/entity/fact/goal 候选；不要省略已知条件、对象、关系或提问目标。
每个层级标记都单独建立 scope 候选，包括（I）（II）以及其下的①②；不要把嵌套小问合并成同一个 scope。
题面直接出现的点、线段、参数、表达式和图形都建立 entity 候选；提问中的前置条件也必须另建 fact 候选，不能只藏在 goal.payload 中。
每个 fact 或 goal 提到的数学对象都必须有独立 entity 候选，包括未命名的顶点、交点以及 AD、BC 这类只在线段关系中出现的对象。
例如“求抛物线的顶点坐标”必须建立未命名 point entity（role=parabola_vertex），但不得擅自给它添加题面没有出现的点名。
只转录和结构化题面，不求解题目，不补充由推理才能得到的新事实。
每个候选必须引用给定 evidence_refs。printed evidence 可以直接支持候选；mixed/unknown evidence 必须同时放入 review_region_refs，并用 ambiguity 引用同一 evidence 和区域，表示候选尚待复核。
若完整图片中存在 OCR/layout 未圈出的点名、图形标签或局部关系，使用覆盖该位置的 visual_review_tile 作为 evidence_refs 和 review_region_refs，并输出引用同一 tile 的 ambiguity。每页 tile 是 4×4 网格，r1c1 为左上、r4c4 为右下；visual_review_tile 永远是 unknown，不得当作已确认 printed evidence。不得因此省略肉眼可见的题面对象。
保持输出紧凑：使用单行 compact JSON；每个候选只引用最小充分 evidence；payload 只写规范化所需的短字段，不写 description、解释或重复题干。
ambiguity 只按 evidence_refs 和 review_region_refs 绑定复核区域；candidate_ids 固定输出空数组 []，不得填入 candidate_id 或 line_id。
每个 candidate 都必须输出 review_region_refs；没有复核区域时写空数组 []，不要省略字段。
不得把学生手写答案、演算、辅助线或 mixed/unknown 区域当成题设事实。
不得输出 ProblemIR、答案、解法、求解方法、capability、FunctionalPlan、typed identity、runtime path 或自由坐标。
候选 id 只在本次响应内有效，格式为 scope_*/entity_*/fact_*/goal_*。"""

OUTPUT_CONTRACT = {
    "schema_version": "problem-extraction-candidate-patch/v1",
    "base_context_id": "copy from evidence pack",
    "evidence_pack_id": "copy from evidence pack",
    "classification": {
        "pattern": "string or null",
        "problem_type": "string or null",
        "confidence": "0..1",
        "evidence_refs": ["printed evidence id"],
    },
    "transcription_lines": [
        {
            "line_id": "line-local-id",
            "text": "printed question text",
            "reading_order": 0,
            "evidence_refs": ["printed evidence id"],
            "review_region_refs": [],
        }
    ],
    "candidates": [
        {
            "candidate_id": "scope/entity/fact/goal_*",
            "candidate_type": "scope|entity|fact|goal",
            "confidence": "0..1",
            "evidence_refs": ["existing evidence id"],
            "review_region_refs": ["required for every mixed/unknown evidence id"],
            "payload": {"kind": "primitive semantic kind; no description/prose"},
        }
    ],
    "ambiguities": [
        {
            "ambiguity_id": "local id",
            "code": "typed ambiguity code",
            "candidate_ids": [],
            "evidence_refs": ["mixed/unknown evidence used by the candidate"],
            "review_region_refs": ["existing region id"],
            "message": "short explanation",
        }
    ],
    "review_region_refs": [],
}


class OpenAIClientFactory(Protocol):
    def __call__(self, **kwargs: Any) -> Any: ...


def _default_client_factory(**kwargs: Any) -> Any:
    from openai import OpenAI

    return OpenAI(**kwargs)


@dataclass(frozen=True)
class MultimodalProviderImage:
    image_id: str
    page_id: str
    artifact: ExtractionArtifactRef
    content: bytes = field(repr=False)
    width: int = 0
    height: int = 0

    def redacted_payload(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "page_id": self.page_id,
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

    @property
    def user_debug(self) -> str:
        return f"{self.user_prefix}\n\n[完整题目图片按 page order 插入此处]\n\n{self.user_suffix}"


@dataclass(frozen=True)
class MultimodalProviderRequest:
    evidence_pack: MultimodalEvidencePack
    prompt: MultimodalExtractionPrompt
    images: tuple[MultimodalProviderImage, ...]

    def redacted_payload(self) -> dict[str, Any]:
        return {
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
            "response_format": {"type": "json_object"},
            "thinking": {"type": MULTIMODAL_THINKING_MODE},
            "stream": False,
            "tools": [],
            "max_tokens": MULTIMODAL_MAX_OUTPUT_TOKENS,
        }

    def provider_messages(self) -> list[dict[str, Any]]:
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

    def metadata_payload(self) -> dict[str, Any]:
        return {
            "provider": MULTIMODAL_PROVIDER_NAME,
            "request_model": self.request_model,
            "response_model": self.response_model,
            "usage": dict(self.usage) if self.usage is not None else None,
            "finish_reason": self.finish_reason,
            "thinking_mode": MULTIMODAL_THINKING_MODE,
            "response_format": "json_object",
            "temperature": 0,
            "max_output_tokens": MULTIMODAL_MAX_OUTPUT_TOKENS,
            "provider_attempts": [
                item.to_payload() for item in self.provider_attempts
            ],
            "latency_ms": self.latency_ms,
        }


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
) -> MultimodalProviderRequest:
    pack.validate()
    images = tuple(
        MultimodalProviderImage(
            image_id=item.image_id,
            page_id=item.page_id,
            artifact=item.artifact,
            content=artifact_reader.read_bytes(item.artifact),
            width=item.width,
            height=item.height,
        )
        for item in pack.images
    )
    if not images or any(item.artifact.kind != "selection_crop" for item in images):
        raise MultimodalProviderError(
            "extraction.multimodal_full_image_missing",
            "every request requires complete selection images",
            result="failed",
        )
    user_suffix = "辅助观察与可引用区域：\n" + json.dumps(
        pack.prompt_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    user_suffix += "\n\n输出合同：\n" + json.dumps(
        OUTPUT_CONTRACT,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return MultimodalProviderRequest(
        evidence_pack=pack,
        prompt=MultimodalExtractionPrompt(
            system=SYSTEM_PROMPT,
            user_prefix=(
                "请按 page order 阅读下面的完整题目图片。图片覆盖全部题干和小问；"
                "辅助 OCR 可能有误，冲突时以图片为准并保留 ambiguity。"
                "evidence_refs 只复制 evidence_id（e###），review_region_refs 只复制 region_id（r###）。"
            ),
            user_suffix=user_suffix,
        ),
        images=images,
    )


@dataclass
class DoubaoMultimodalExtractionProvider:
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
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=request.provider_messages(),
                    temperature=0,
                    response_format={"type": "json_object"},
                    extra_body={"thinking": {"type": MULTIMODAL_THINKING_MODE}},
                    max_tokens=MULTIMODAL_MAX_OUTPUT_TOKENS,
                    stream=False,
                    timeout=self.request_timeout,
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
