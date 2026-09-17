"""Keep image transport cohorts separate, using recorded requests for history."""

import json
from pathlib import Path


def request_image_transport(payload):
    modes = set()
    declared = payload.get("image_transport")
    if isinstance(declared, dict):
        declared = declared.get("mode")
    if declared in ("files", "base64"):
        modes.add(declared)
    for message in payload.get("messages", []):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if part.get("type") == "file":
                modes.add("files")
            elif part.get("type") == "image_url":
                url = part.get("image_url", {}).get("url", "")
                modes.add(
                    "base64"
                    if isinstance(url, str) and url.startswith(("data:", "artifact://"))
                    else "unknown"
                )
    return next(iter(modes)) if len(modes) == 1 else "mixed" if modes else "unknown"


def workflow_image_transport(directory):
    directory = Path(directory)
    ledger = json.loads((directory / "ledger.json").read_text())
    modes = set()
    for call in ledger["calls"]:
        path = directory / call["directory"] / "request.json"
        modes.add(
            request_image_transport(json.loads(path.read_text()))
            if path.exists()
            else "unknown"
        )
    return next(iter(modes)) if len(modes) == 1 else "mixed" if modes else "unknown"


def _total(values):
    return sum(values) if values and all(v is not None for v in values) else None


def transport_cohorts(results):
    """Case KPIs, never allocate a mixed/unknown case to a known transport."""
    groups = {}
    for case, row in results.items():
        mode = row.get("image_transport", "unknown")
        if mode not in {"files", "base64", "mixed", "unknown"}:
            mode = "unknown"
        groups.setdefault(mode, {})[case] = row
    result = {}
    for mode, cases in sorted(groups.items()):
        rows = list(cases.values())
        cohort = {
            "cases": sorted(cases),
            "completed": len(rows),
            "passed": sum(bool(r.get("passed")) for r in rows),
            "first_passed": _total([r.get("first_passed") for r in rows]),
            "elapsed_seconds": _total([r.get("elapsed_seconds") for r in rows]),
            "semantic_calls": _total([r.get("semantic_calls") for r in rows]),
            "network_attempts": _total([r.get("network_attempts") for r in rows]),
            "file_api_calls": _total([r.get("file_api_calls") for r in rows]),
        }
        for field in ("input_tokens", "output_tokens", "reasoning_tokens"):
            cohort[field] = _total(
                [
                    _total([s.get(field) for s in r["stages"].values()])
                    if r.get("stages")
                    else r.get("usage", {}).get(field)
                    for r in rows
                ]
            )
        if cohort["elapsed_seconds"] is not None:
            cohort["elapsed_seconds"] = round(cohort["elapsed_seconds"], 3)
        result[mode] = cohort
    return result
