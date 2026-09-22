"""Review uses source criteria, never the legacy Solver authoring contract."""

import json
from copy import deepcopy
from hashlib import sha256

import pytest
from test_math_notation_workflow import OK, Sequence, candidate, setup

from shuxueshuo_server.problem_understanding import review_contract, workflow
from shuxueshuo_server.problem_understanding.review_contract import (
    FAMILIES_PATH,
    FILES,
    ReviewFamilyCatalogError,
    review_family_context,
)
from shuxueshuo_server.problem_understanding.workflow_ledger import WorkflowStop
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    problem_domain_family_catalog,
)


def test_current_families_all_have_source_review_guidance():
    registry = list(problem_domain_family_catalog())
    source = json.loads(FAMILIES_PATH.read_text())
    context = review_family_context(registry)
    # The review catalog may contain notation-only families that are not yet
    # executable in DEFAULT_FAMILY_REGISTRY. Every runtime family still needs
    # guidance, while the extra entries are selected only when notation asks
    # for them.
    assert {f["family_id"] for f in source["families"]} >= {
        f["family_id"] for f in registry
    }
    assert context["registered_families"] == [
        family for family in source["families"] if family["family_id"] in {
            item["family_id"] for item in registry
        }
    ]
    assert context["family_review_scope"] == source["review_scope"]
    # A regression to the old authoring catalog is not a harmless prompt change.
    text = json.dumps(context, ensure_ascii=False)
    for old_instruction in (
        "primitive_types",
        "path_minimum_target",
        "minimum_value",
        "use_when",
        "required_source_primitives",
        "conditional_source_requirements",
        "反射",
        "等价替换",
        "路径降维",
        "核心机制",
        "拉直",
    ):
        assert old_instruction not in text


def test_selection_uses_registered_ids_only_without_mutating_raw_registry():
    source = list(problem_domain_family_catalog())
    selected = [source[-1], source[0]]
    poisoned = deepcopy(selected)
    for family in poisoned:
        for key in family.keys() - {"family_id"}:
            family[key] = "LEGACY_AUTHORING_SHOULD_NOT_REACH_REVIEW"
        family["new_solver_description"] = "SOLVE_FIRST"
    snapshot = deepcopy(poisoned)
    context = review_family_context(poisoned)
    assert context == review_family_context(selected)
    assert [f["family_id"] for f in context["registered_families"]] == [
        f["family_id"] for f in selected
    ]
    assert poisoned == snapshot
    assert review_family_context([])["registered_families"] == []


@pytest.mark.parametrize(
    "failure",
    ["invalid_json", "missing_scope", "extra_legacy_field", "duplicate", "empty_rules"],
)
def test_invalid_catalog_never_falls_back_to_legacy_guidance(
    tmp_path, monkeypatch, failure
):
    document = json.loads(FAMILIES_PATH.read_text())
    if failure == "missing_scope":
        document.pop("review_scope")
    elif failure == "extra_legacy_field":
        document["families"][0]["required_source_primitives"] = ["path_minimum_target"]
    elif failure == "duplicate":
        document["families"].append(document["families"][0])
    elif failure == "empty_rules":
        document["families"][0]["source_conditions"] = []
    path = tmp_path / "families.json"
    path.write_text("{" if failure == "invalid_json" else json.dumps(document))
    monkeypatch.setattr(review_contract, "FAMILIES_PATH", path)
    with pytest.raises(ReviewFamilyCatalogError, match="review.invalid_family_catalog"):
        review_family_context(problem_domain_family_catalog())


@pytest.mark.parametrize("failure", ["unknown_family", "duplicate", "invalid_id"])
def test_unreviewable_registry_stops_before_paid_workflow(tmp_path, failure):
    registry = list(problem_domain_family_catalog())
    if failure == "unknown_family":
        registry.append({"family_id": "NewFamily", "use_when": "legacy instructions"})
        code = "review.family_catalog_missing:NewFamily"
    elif failure == "duplicate":
        registry.append(registry[0])
        code = "review.invalid_family_registry"
    else:
        registry[0] = {"family_id": None}
        code = "review.invalid_family_registry"
    request, model = setup(tmp_path), Sequence()
    with pytest.raises(WorkflowStop, match=code):
        workflow.run_workflow(
            request, model, tmp_path / "run", registry, problem_id="synthetic"
        )
    assert not model.requests and model.calls == 0
    assert not (tmp_path / "run").exists()


def test_review_catalog_is_frozen_and_changed_guidance_cannot_resume(
    tmp_path, monkeypatch
):
    assert FAMILIES_PATH in FILES
    assert (
        workflow.frozen_files()["templates"][
            FAMILIES_PATH.relative_to(workflow.ROOT).as_posix()
        ]
        == sha256(FAMILIES_PATH.read_bytes()).hexdigest()
    )
    # Exercise a real file change without mutating the repository's prompt.
    root = tmp_path / "checkout"
    files = []
    for source in FILES:
        target = root / source.relative_to(workflow.ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        files.append(target)
    path = root / FAMILIES_PATH.relative_to(workflow.ROOT)
    monkeypatch.setattr(workflow, "ROOT", root)
    monkeypatch.setattr(workflow, "FILES", tuple(files))
    document = json.loads(FAMILIES_PATH.read_text())
    monkeypatch.setattr(review_contract, "FAMILIES_PATH", path)
    registry = list(problem_domain_family_catalog())
    request = setup(tmp_path, registry)
    result = workflow.run_workflow(
        request,
        Sequence(candidate(["t>0"]), OK),
        tmp_path / "run",
        registry,
        problem_id="synthetic",
    )
    assert result["source_reviewed"]
    document["review_scope"].append("新增的复核边界")
    path.write_text(json.dumps(document))
    model = Sequence()
    with pytest.raises(WorkflowStop, match="stale_binding"):
        workflow.run_workflow(
            request, model, tmp_path / "run", registry, problem_id="synthetic"
        )
    assert model.calls == 0
