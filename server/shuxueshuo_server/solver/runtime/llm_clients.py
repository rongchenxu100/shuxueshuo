"""LLM Planner client 协议与 OpenAI-compatible provider。

Phase A 只实现 provider 接入层：把受控 payload 发送给兼容 OpenAI Chat
Completions API 的模型，并取回 JSON 字符串。真正的 prompt 模板、SlotBinder、
repair loop 会在后续阶段继续补齐。
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
    last_usage: dict[str, Any] | None = field(default=None, init=False)
    last_response_model: str | None = field(default=None, init=False)
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    def __post_init__(self) -> None:
        """在构造阶段做配置校验，CLI 可以尽早给出可读错误。"""
        if not self.api_key:
            raise LLMClientConfigurationError(
                f"--planner llm requires {self.provider_name.upper()}_API_KEY"
            )
        if not self.base_url:
            raise LLMClientConfigurationError(
                f"--planner llm requires {self.provider_name.upper()}_BASE_URL"
            )
        if not self.model:
            raise LLMClientConfigurationError(
                f"--planner llm requires {self.provider_name.upper()}_MODEL"
            )
        self._client = self.client_factory(api_key=self.api_key, base_url=self.base_url)

    def complete(self, payload: dict[str, Any]) -> str:
        """发送一次 Chat Completions 请求，并返回 assistant message 文本。"""
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    # TODO(Phase C): 用 Jinja prompt 模板替换这个临时 system prompt。
                    "content": self.system_prompt,
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            temperature=self.temperature,
        )
        self.last_usage = _usage_to_dict(getattr(response, "usage", None))
        # 真实 provider 返回的 model 字段能帮助集成测试确认服务端实际命中的模型版本。
        response_model = getattr(response, "model", None)
        self.last_response_model = str(response_model) if response_model else None
        content = response.choices[0].message.content
        if content is None:
            return ""
        return str(content)


class DeepSeekPlannerClient(OpenAICompatiblePlannerClient):
    """DeepSeek Planner provider。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        client_factory: OpenAIClientFactory = _default_openai_client_factory,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            provider_name="deepseek",
            client_factory=client_factory,
        )


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
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            provider_name="doubao",
            client_factory=client_factory,
        )


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
