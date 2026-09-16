"""Offline provider double; request preparation never calls the network."""

from types import SimpleNamespace


class Recorded:
    def __init__(self, text, finish="stop", fail=False):
        self.text, self.finish, self.fail, self.calls = text, finish, fail, 0

    def prepare_request(self, r):
        from shuxueshuo_server.solver.extraction.multimodal_provider import (
            DeepSeekMultimodalExtractionProvider,
        )

        return DeepSeekMultimodalExtractionProvider(
            api_key="recorded",
            base_url="https://api.deepseek.com",
            model="deepseek-flash",
            request_timeout=300,
            max_output_tokens=16384,
        ).prepare_request(r)

    def complete(self, r):
        self.calls += 1
        if self.fail:
            raise TimeoutError("recorded timeout")
        return SimpleNamespace(
            text=self.text,
            finish_reason=self.finish,
            raw_payload={
                "choices": [
                    {"message": {"content": self.text}, "finish_reason": self.finish}
                ]
            },
            provider_attempts=({"attempt": 1},),
            metadata_payload=lambda: {"model": "deepseek-flash"},
        )
