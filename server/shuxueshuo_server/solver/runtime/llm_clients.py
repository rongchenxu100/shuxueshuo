"""LLM Planner client 协议与 OpenAI-compatible provider。

本模块只保留 provider 接入层：把调用方准备好的 Chat payload 发送给兼容
OpenAI Chat Completions API 的模型，并取回 JSON 字符串。旧 LLM planner 已删除，
新的 Strategy Planner 落地后会复用这一层 client。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class LLMPlannerClient(Protocol):
    """LLM Planner client 的最小协议。

    Runtime planner 只关心“给一个受控 payload，拿回一段 JSON 字符串”。模型名、
    API key、base_url、重试和 token 统计都由具体 provider 自己处理。
    """

    def complete(self, payload: dict[str, Any]) -> str:
        """根据受控 payload 返回模型输出的 JSON 字符串。"""
        ...


class LLMClientConfigurationError(ValueError):
    """LLM provider 配置不完整时抛出的错误。"""


class LLMProviderResponseError(ValueError):
    """A provider consumed output tokens but returned no visible content."""

    code = "provider.reasoning_only_empty_response"


OpenAIClientFactory = Callable[..., Any]
DEFAULT_SYSTEM_PROMPT = (
    "You are a math planning engine. Return JSON only. "
    "Do not include markdown fences."
)


def _default_openai_client_factory(**kwargs: Any) -> Any:
    """延迟导入 OpenAI SDK，避免 deterministic 路径无故依赖真实 provider。"""
    from openai import OpenAI

    return OpenAI(**kwargs)


@dataclass
class OpenAICompatiblePlannerClient:
    """兼容 OpenAI Chat Completions API 的 Planner client。

    DeepSeek 和豆包 Ark 都走这个基类，只差 provider 名称、默认 base_url 和默认
    model。测试可以注入 ``client_factory``，从而不需要真实网络调用。
    """

    api_key: str
    base_url: str
    model: str
    provider_name: str
    client_factory: OpenAIClientFactory = _default_openai_client_factory
    temperature: float = 0.0
    request_timeout: float = 120.0
    last_usage: dict[str, Any] | None = field(default=None, init=False)
    last_response_model: str | None = field(default=None, init=False)
    last_provider_attempts: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
    )
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    def __post_init__(self) -> None:
        """在构造阶段做配置校验，CLI 可以尽早给出可读错误。"""
        if not self.api_key:
            raise LLMClientConfigurationError(
                f"LLM provider requires {self.provider_name.upper()}_API_KEY"
            )
        if not self.base_url:
            raise LLMClientConfigurationError(
                f"LLM provider requires {self.provider_name.upper()}_BASE_URL"
            )
        if not self.model:
            raise LLMClientConfigurationError(
                f"LLM provider requires {self.provider_name.upper()}_MODEL"
            )
        self._client = self.client_factory(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.request_timeout,
        )

    def complete(self, payload: dict[str, Any]) -> str:
        """发送一次 Chat Completions 请求，并返回 assistant message 文本。

        Phase C 的受控 planner 会把 Jinja 渲染后的 messages 放进 payload；legacy
        planner 仍只传结构化 dict。这里兼容两种形态，避免 provider 层理解具体
        planner 类型。
        """
        messages = _messages_from_payload(payload, self.system_prompt)
        request_options = self._completion_request_options(payload)
        request_audit = _completion_request_audit(request_options)
        attempts: list[dict[str, Any]] = []
        request_messages = list(messages)
        for provider_attempt in range(1, 3):
            response = self._client.chat.completions.create(
                model=self.model,
                messages=request_messages,
                timeout=self.request_timeout,
                **request_options,
            )
            usage = _usage_to_dict(getattr(response, "usage", None))
            response_model = getattr(response, "model", None)
            content = response.choices[0].message.content
            text = "" if content is None else str(content)
            attempts.append(
                {
                    "provider_attempt": provider_attempt,
                    "response_model": (
                        str(response_model) if response_model else None
                    ),
                    "usage": usage,
                    "finish_reason": getattr(
                        response.choices[0],
                        "finish_reason",
                        None,
                    ),
                    "visible_content": bool(text.strip()),
                    **request_audit,
                }
            )
            self.last_provider_attempts = tuple(attempts)
            self.last_usage = _sum_usage(
                tuple(item.get("usage") for item in attempts)
            )
            self.last_response_model = (
                str(response_model) if response_model else None
            )
            if text.strip():
                return text
            if not _usage_consumed_output_tokens(usage):
                return text
            if provider_attempt == 1:
                request_messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "上一响应消耗了输出 token 但没有可见内容。"
                            "请立即输出严格 JSON，不要输出解释或 Markdown。"
                        ),
                    },
                ]
                continue
            raise LLMProviderResponseError(
                "provider.reasoning_only_empty_response: "
                "two provider requests consumed output tokens without visible content"
            )
        raise AssertionError("provider retry loop exhausted")

    def _completion_request_options(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Return provider-specific Chat Completions request options."""
        del payload
        return {"temperature": self.temperature}


class DeepSeekPlannerClient(OpenAICompatiblePlannerClient):
    """DeepSeek Planner provider。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        client_factory: OpenAIClientFactory = _default_openai_client_factory,
        request_timeout: float = 120.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            provider_name="deepseek",
            client_factory=client_factory,
            request_timeout=request_timeout,
        )

    def _completion_request_options(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Use direct JSON on pass 1 and low thinking only for semantic repair."""
        planner_attempt = payload.get("planner_attempt", 1)
        options: dict[str, Any] = {
            "response_format": {"type": "json_object"},
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        if isinstance(planner_attempt, int) and planner_attempt > 1:
            options.update(
                {
                    "reasoning_effort": "low",
                    "extra_body": {"thinking": {"type": "enabled"}},
                }
            )
        return options


class DoubaoPlannerClient(OpenAICompatiblePlannerClient):
    """豆包 Ark Planner provider。

    首版只实现文本模式；后续多模态题面应先通过 ProblemIR 抽取链路结构化，不把
    图片内容直接塞进 Planner payload。
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        client_factory: OpenAIClientFactory = _default_openai_client_factory,
        request_timeout: float = 120.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            provider_name="doubao",
            client_factory=client_factory,
            request_timeout=request_timeout,
        )


def _completion_request_audit(options: dict[str, Any]) -> dict[str, Any]:
    response_format = options.get("response_format")
    extra_body = options.get("extra_body")
    thinking = (
        extra_body.get("thinking")
        if isinstance(extra_body, dict)
        else None
    )
    return {
        "response_format": (
            response_format.get("type")
            if isinstance(response_format, dict)
            else None
        ),
        "thinking_mode": (
            thinking.get("type")
            if isinstance(thinking, dict)
            else None
        ),
        "reasoning_effort": options.get("reasoning_effort"),
    }


def _usage_to_dict(usage: Any) -> dict[str, Any] | None:
    """把不同 SDK 形态的 usage 对象转成可序列化 dict。"""
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return dict(usage.model_dump())
    if isinstance(usage, dict):
        return dict(usage)
    result: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if hasattr(usage, key):
            result[key] = getattr(usage, key)
    return result or None


def _usage_consumed_output_tokens(usage: dict[str, Any] | None) -> bool:
    if not usage:
        return False
    completion = usage.get("completion_tokens")
    if isinstance(completion, (int, float)) and completion > 0:
        return True
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict):
        reasoning = details.get("reasoning_tokens")
        return isinstance(reasoning, (int, float)) and reasoning > 0
    return False


def _sum_usage(
    usages: tuple[dict[str, Any] | None, ...],
) -> dict[str, Any] | None:
    values = [item for item in usages if isinstance(item, dict)]
    if not values:
        return None
    result: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        numbers = [
            item.get(key)
            for item in values
            if isinstance(item.get(key), (int, float))
        ]
        if numbers:
            result[key] = sum(numbers)
    if len(values) > 1:
        result["provider_request_count"] = len(values)
    return result


def _messages_from_payload(
    payload: dict[str, Any],
    system_prompt: str,
) -> list[dict[str, str]]:
    """从 provider payload 中取出 Chat messages。

    受控 planner 会显式传入 Jinja 渲染后的 ``messages``；legacy planner 还只传
    结构化 payload，因此这里保留一次兼容包装。Provider 层只识别通用 Chat
    messages envelope，不理解具体 planner 的字段语义。
    """
    messages = payload.get("messages")
    if isinstance(messages, list):
        return messages
    return [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False),
        },
    ]
