"""DeepSeek adapter. Credentials and teacher prompts never go to the browser."""

import json
import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).parent


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["method", "fill", "swap", "choice", "submit", "switch_route"]
    value: str | None = Field(default=None, max_length=80)
    index: int | None = Field(default=None, ge=0)


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reply: str = Field(min_length=1, max_length=8000)
    intent: Literal["answer", "question", "other", "route_change"]
    evidence: list[str] = Field(max_length=10)
    actions: list[Action] = Field(max_length=6)


class TutorUnavailable(Exception):
    pass


class DeepSeekTutor:
    def __init__(self):
        config = {**dotenv_values(ROOT.parents[1] / ".env"), **os.environ}
        self.key = config.get("DEEPSEEK_API_KEY")
        self.model = (
            config.get("TUTOR_DEEPSEEK_MODEL")
            or config.get("DEEPSEEK_MODEL")
            or "deepseek-v4-flash"
        )
        self.base_url = config.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
        self.env = Environment(
            loader=FileSystemLoader(ROOT / "prompts"), undefined=StrictUndefined
        )
        self.client = None

    def prompts(self, **data):
        return [
            {
                "role": "system",
                "content": self.env.get_template("tutor-system.jinja").render(),
            },
            {
                "role": "user",
                "content": self.env.get_template("tutor-turn.jinja").render(**data),
            },
        ]

    async def respond(self, **data) -> Proposal:
        if not self.key:
            raise TutorUnavailable("未配置 DEEPSEEK_API_KEY")
        if self.client is None:
            self.client = AsyncOpenAI(
                api_key=self.key, base_url=self.base_url, timeout=45, max_retries=0
            )
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=self.prompts(**data),
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "disabled"}},
                max_tokens=1600,
            )
            if response.choices[0].finish_reason != "stop":
                raise ValueError("incomplete response")
            return Proposal.model_validate(
                json.loads(response.choices[0].message.content or "")
            )
        except Exception as exc:
            # Do not send provider errors/credentials or unvalidated model output to clients.
            raise TutorUnavailable("老师暂时未能回复，请保留输入并重试。") from exc

    async def close(self):
        if self.client is not None:
            await self.client.close()
