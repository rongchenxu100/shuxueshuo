"""Token accounting from the durable provider records, including reasoning."""

import json
from pathlib import Path


def call_usage(response):
    metadata = response.get("metadata", {})
    usage = metadata.get("usage") or {}
    attempts = metadata.get("provider_attempts", [])
    reasoning = [
        ((attempt.get("usage") or {}).get("completion_tokens_details") or {}).get(
            "reasoning_tokens"
        )
        for attempt in attempts
    ]
    reasoning_tokens = (
        sum(reasoning)
        if reasoning and all(isinstance(n, int) for n in reasoning)
        else (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
    )
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "visible_output_tokens": output_tokens - reasoning_tokens
        if isinstance(output_tokens, int) and isinstance(reasoning_tokens, int)
        else None,
        "usage_available": bool(usage) and metadata.get("usage_complete", True),
    }


def stages(directory):
    directory = Path(directory)
    ledger = json.loads((directory / "ledger.json").read_text())
    result = {}
    for call in ledger["calls"]:
        row = result.setdefault(
            call["stage"],
            {
                "calls": 0,
                "file_api_calls": 0,
                "seconds": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "visible_output_tokens": 0,
                "usage_available": True,
            },
        )
        row["calls"] += 1
        row["file_api_calls"] += call.get("file_api_calls", 0)
        row["seconds"] += call.get("elapsed_seconds", 0)
        response = (
            json.loads((directory / call["response_file"]).read_text())
            if "response_file" in call
            else {}
        )
        usage = call_usage(response)
        row["usage_available"] &= usage["usage_available"]
        for field in (
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "visible_output_tokens",
        ):
            value = usage[field]
            row[field] = (
                row[field] + value
                if row[field] is not None and value is not None
                else None
            )
        row["seconds"] = round(row["seconds"], 3)
    return result
