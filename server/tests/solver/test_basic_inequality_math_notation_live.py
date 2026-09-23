"""Paid stage-0 gate; skipped unless explicitly enabled."""

import json
import os

import pytest

from shuxueshuo_server.problem_understanding.basic_inequality_smoke import (
    CASES,
    SAMPLES_PER_CASE,
    run_batch,
)
from shuxueshuo_server.problem_understanding.batch_smoke import live_provider_factory


@pytest.mark.live_llm
def test_basic_inequality_deepseek_twice_all_representatives(tmp_path):
    if os.getenv("RUN_LLM_INTEGRATION") != "1":
        pytest.skip("real DeepSeek integration disabled")
    output = tmp_path / "basic-inequality-stage-0"
    summary = run_batch(
        output,
        cases=CASES,
        samples=SAMPLES_PER_CASE,
        provider_factory=live_provider_factory("deepseek"),
    )
    assert summary["total_samples"] == len(CASES) * SAMPLES_PER_CASE
    assert summary["passed"] == summary["total_samples"], summary
    frozen = []
    for case in CASES:
        for sample in range(1, SAMPLES_PER_CASE + 1):
            root = output / case / f"sample-{sample:02d}" / "run"
            frozen.append(json.loads((root / "frozen.json").read_text()))
            assert (root / "request.json").exists()
            assert (root / "raw-response.txt").exists()
            assert (root / "parsed.json").exists()
            assert (root / "diff.json").exists()
    for field in (
        "system_prompt_hash",
        "authoring_schema_hash",
        "registry_snapshot",
        "notation_family_catalog_hash",
        "expression_catalog_hash",
    ):
        assert len({item[field] for item in frozen}) == 1
