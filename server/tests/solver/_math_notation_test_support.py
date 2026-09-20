"""Offline provider double; request preparation never calls the network."""

from types import SimpleNamespace


def assert_removed_at_rejected(*payloads):
    """Archives are evidence, not a compatibility path for removed fields."""
    from shuxueshuo_server.problem_understanding.notation_compile import (
        NotationValidator,
    )

    def contains(value):
        if isinstance(value, dict):
            return "at" in value or any(contains(v) for v in value.values())
        return isinstance(value, list) and any(contains(v) for v in value)

    found = False
    for payload in payloads:
        if contains(payload):
            found = True
            report = NotationValidator().validate(payload)
            assert not report.ok and not report.semantic and not report.normalized
            assert all(issue["code"] == "schema.invalid" for issue in report.issues)
    return found


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
