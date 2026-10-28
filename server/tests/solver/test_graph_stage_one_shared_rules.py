"""The three stage-one roles receive one source interpretation contract."""

import json
from hashlib import sha256

import pytest
from shuxueshuo_server.graph_lesson.stage_one import contracts, runner
from shuxueshuo_server.graph_lesson.stage_one.extraction import (
    GraphStageOneContract,
    validate_candidate,
)
from shuxueshuo_server.search.extraction import (
    PUBLIC_PROMPT_PATH,
    SearchStageOneContract,
    build_search_request,
)
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore


@pytest.mark.parametrize("search", [False, True])
def test_every_provider_role_receives_the_same_source_rules(tmp_path, search):
    image = (runner.CORPUS / "q01/source.png").read_bytes()
    store = ExtractionArtifactStore(tmp_path / "inputs")
    contract = SearchStageOneContract() if search else GraphStageOneContract()
    builder = build_search_request if search else runner.build_image_request
    base = builder(image, store)
    candidate = {
        "original_text": "函数的定义域为实数集，求参数范围。",
        "root": {
            "definitions": ["f(t)=sqrt(a*t^2+2*a*t+5)"],
            "goals": [{"kind": "match_domain", "object": "f", "domain": "ℝ", "symbol": "a"}],
        },
    }
    requests = [base] + [
        contract.request_for(base, role, candidate, [])
        for role in ("review", "repair")
    ]
    shared = contracts.SOURCE_RULES_PATH.read_text(encoding="utf-8").strip()
    public = PUBLIC_PROMPT_PATH.read_text(encoding="utf-8").strip()
    for request in requests:
        assert request.prompt.system.count(shared) == 1
        assert (public in request.prompt.system) is search
        assert "求参数范围仍是 find_range" not in request.prompt.system
        payload = json.loads(request.prompt.user_prefix)
        assert payload["math_expression_catalog"] == contracts.expression_catalog()
        goals = payload["math_expression_catalog"]["expressions"]
        assert any(item["id"] == "function_domain_parameter_goal" for item in goals)
        assert request.images[0].content == image


@pytest.mark.parametrize("contract_type", [GraphStageOneContract, SearchStageOneContract])
def test_shared_source_rules_are_part_of_frozen_workflow_identity(contract_type):
    path = contracts.SOURCE_RULES_PATH
    assert path in contracts.TEMPLATE_FILES
    files = contract_type().frozen_files()
    assert files[str(path.relative_to(contracts.ROOT))] == sha256(path.read_bytes()).hexdigest()


def test_catalog_preserves_domain_goal_and_explicit_inequality_as_different_sources():
    entry = next(
        item for item in contracts.expression_catalog()["expressions"]
        if item["id"] == "function_domain_parameter_goal"
    )
    examples = entry["few_shots"]
    assert [item["output"]["goals"][0]["kind"] for item in examples] == [
        "match_domain", "find_range",
    ]
    for item in examples:
        candidate = {"original_text": item["input"], "root": item["output"]}
        checked = validate_candidate(candidate)
        assert checked["contract_valid"], checked
    assert examples[0]["output"]["facts"] == []
    assert examples[0]["output"]["goals"][0]["domain"] == "ℝ"
    assert "definitions" not in examples[1]["output"]


def test_shared_review_guidance_distinguishes_existing_and_missing_goal_authority():
    rules = contracts.SOURCE_RULES
    assert "指向已有目标条目或其字段的 wrong_goal，只授权原位置修正" in rules
    assert "wrong_goal 应指向所在作用域（如 /root）或已有 goals 数组（如 /root/goals）" in rules
    assert "仅授权在该作用域追加遗漏目标，不能改写已有目标或其他条件" in rules
    assert "missing_condition 应指向所在作用域或已有 facts/definitions 数组" in rules
    assert "wrong_scope 仅授权在所指范围内整理分问层次、顺序和移动已有内容" in rules


@pytest.mark.parametrize("contract_type", [GraphStageOneContract, SearchStageOneContract])
def test_comparison_admission_dependencies_change_the_workflow_fingerprint(monkeypatch, contract_type):
    from pathlib import Path

    read_bytes = Path.read_bytes
    contract = contract_type()
    before = contract.frozen_files()
    for relative in ("graph_lesson/function_equality.py", "graph_lesson/domain_expression.py"):
        path = contracts.ROOT / "server/shuxueshuo_server" / relative
        key = str(path.relative_to(contracts.ROOT))
        assert key in before
        with monkeypatch.context() as patch:
            patch.setattr(Path, "read_bytes", lambda item: read_bytes(item) + (b"\n# changed\n" if item == path else b""))
            after = contract.frozen_files()
        assert after[key] != before[key]
        assert {name for name in before if before[name] != after[name]} == {key}
