"""Budgeted image review and atomic full-candidate repairs, without network."""

import json
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from shutil import copytree

import pytest
from _math_notation_test_support import Recorded, assert_removed_at_rejected

from shuxueshuo_server.problem_understanding.batch_smoke import prepare_fixture
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.notation_contract import schema
from shuxueshuo_server.problem_understanding.notation_service import parse_candidate
from shuxueshuo_server.problem_understanding.repair_guard import guard_changes
from shuxueshuo_server.problem_understanding.review_contract import (
    EXAMPLES_PATH,
    FILES,
    candidate_contract_summary,
    request_for,
    validate_review,
)
from shuxueshuo_server.problem_understanding.smoke import build_request
from shuxueshuo_server.problem_understanding.workflow import run_workflow
from shuxueshuo_server.problem_understanding.workflow_diagnostics import (
    diagnose,
    json_pointer,
    permissions,
    review_diagnostics,
)
from shuxueshuo_server.problem_understanding.workflow_ledger import (
    Budget,
    Ledger,
    WorkflowStop,
    save,
)
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore


def candidate(facts=(), **root):
    return {
        "root": {"facts": list(facts), **root},
        "match_status": "unmatched",
        "family_id": None,
        "match_reason": "independent",
    }


OK = {"status": "confirmed", "findings": []}


def finding(path="/root", kind="missing_condition", message="漏掉原图参数范围"):
    return {
        "status": "correction_required",
        "findings": [
            {
                "path": path,
                "kind": kind,
                "source_excerpt": "参数t>1",
                "message": message,
            }
        ],
    }


class Sequence(Recorded):
    def __init__(self, *responses):
        super().__init__("")
        self.responses, self.requests = list(responses), []

    def complete(self, request):
        self.requests.append(request)
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            self.calls += 1
            raise value
        self.text = (
            value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        )
        return super().complete(request)


def setup(tmp_path, registry=()):
    fixture = prepare_fixture("function-quantifiers", tmp_path / "fixture")
    return build_request(
        fixture, ExtractionArtifactStore(tmp_path / "inputs"), list(registry)
    )


def run(tmp_path, provider, **kwargs):
    return run_workflow(
        setup(tmp_path),
        provider,
        tmp_path / "run",
        [],
        problem_id="synthetic",
        **kwargs,
    )


def test_success_and_recovery_use_same_completed_calls(tmp_path):
    model = Sequence(candidate(["t>0"]), OK)
    result = run(tmp_path, model)
    assert result["status"] == "reviewed_candidate" and result["source_reviewed"]
    assert result["semantic_calls"] == 2 and result["content_calls"] == 1
    assert not result["solver_ready"] and result["candidate_only"]
    assert model.calls == 2
    restored = run(tmp_path, Sequence())
    assert restored == result


@pytest.mark.parametrize("changed_group", ["templates", "implementation"])
def test_relocated_checkout_resumes_but_changed_files_still_stop(
    tmp_path, monkeypatch, changed_group
):
    from shuxueshuo_server.problem_understanding import workflow

    original = run(tmp_path / "original", Sequence(candidate(["t>0"]), OK))
    frozen = workflow.frozen_files()
    root = tmp_path / "relocated-checkout"
    files = {
        "templates": [root / p for p in frozen["templates"]],
        "implementation": [
            root / "server/shuxueshuo_server" / p for p in frozen["implementation"]
        ],
    }
    assert all(not Path(p).is_absolute() for group in frozen.values() for p in group)
    for paths in files.values():
        for target in paths:
            source = workflow.ROOT / target.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    monkeypatch.setattr(workflow, "ROOT", root)
    monkeypatch.setattr(workflow, "FILES", tuple(files["templates"]))
    monkeypatch.setattr(
        workflow,
        "__file__",
        str(root / "server/shuxueshuo_server/problem_understanding/workflow.py"),
    )
    assert workflow.frozen_files() == frozen

    # Move the ledger and inputs as well; completed responses must be reused.
    moved = root / "run-output"
    copytree(tmp_path / "original", moved)
    ledger = moved / "run/ledger.json"
    before = ledger.read_bytes()
    model = Sequence()
    restored = run(moved, model)
    assert restored["source_reviewed"]
    assert restored["candidate"] == original["candidate"]
    assert restored["semantic_calls"] == original["semantic_calls"] == 2
    assert not model.requests and ledger.read_bytes() == before

    changed = files[changed_group][0]
    changed.write_bytes(changed.read_bytes() + b"\n")
    with pytest.raises(WorkflowStop, match="workflow.stale_binding"):
        run(moved, model)
    assert not model.requests and ledger.read_bytes() == before


def test_workflow_never_guesses_a_legacy_contract_from_payload_shape(tmp_path):
    request = replace(setup(tmp_path), contract_version="problem-domain/v1")
    model = Sequence()
    with pytest.raises(WorkflowStop, match="unsupported_or_stale_contract"):
        run_workflow(request, model, tmp_path / "run", [], problem_id="wrong-version")
    assert model.calls == 0


def test_review_receives_adopted_model_json_not_normalized_ir(tmp_path):
    original = candidate(
        ["Γ:y=x^2+q", "V=vertex(Γ)"],
        goals=[{"kind": "find_coordinates", "object": "V"}],
    )
    model = Sequence(original, OK)
    result = run(tmp_path, model)
    assert result["source_reviewed"]
    payload = json.loads(model.requests[1].prompt.user_prefix)
    sent = payload["candidate"]
    assert sent == original == result["candidate"]
    assert sent["root"]["goals"][0]["object"] == "V"
    assert "children" not in sent["root"]
    assert result["parsed"]["objects"]["ir"]["root"] != sent["root"]
    assert result["parsed"]["reports"]["ir"]["object_bindings"]
    checks = payload["code_validation"]
    assert (
        checks["candidate_revision"] == result["parsed"]["revision"] == revision(sent)
    )
    assert checks["json_schema"] == checks["notation_and_bindings"] == "passed"
    assert checks["match_declaration"] == "passed"
    assert checks["source_alignment"] == checks["family_semantics"] == "not_checked"
    assert checks["mathematical_equivalence"] == "partial"
    assert payload["candidate_contract"] == candidate_contract_summary()


def test_review_finds_omission_repair_same_schema_and_fresh_review(tmp_path):
    original, repaired = candidate(["t>0"]), candidate(["t>0", "t>1"])
    model = Sequence(original, finding(), repaired, OK)
    result = run(tmp_path, model)
    assert result["status"] == "reviewed_candidate", result["diagnostics"]
    assert result["first_candidate"] == original and result["candidate"] == repaired
    assert result["content_calls"] == 2 and result["review_calls"] == 2
    assert result["review"]["revision"] == revision(repaired)
    payload = json.loads(model.requests[2].prompt.user_prefix)
    assert payload["base_candidate"] == original
    assert payload["allowed_changes"][0]["mode"] == "append"
    assert model.requests[2].contract_version == model.requests[0].contract_version
    assert json.loads(model.requests[1].prompt.user_prefix)["candidate"] == original
    assert json.loads(model.requests[3].prompt.user_prefix)["candidate"] == repaired
    for request, value in (
        (model.requests[1], original),
        (model.requests[3], repaired),
    ):
        assert json.loads(request.prompt.user_prefix)["code_validation"][
            "candidate_revision"
        ] == revision(value)


def test_schema_or_json_failure_reextracts_without_patch_protocol(tmp_path):
    model = Sequence("{", {}, candidate(["a>0"]), OK)
    result = run(tmp_path, model)
    assert result["status"] == "reviewed_candidate"
    assert result["content_calls"] == 3 and result["review_calls"] == 1
    assert json.loads(model.requests[1].prompt.user_prefix)["base_candidate"] is None


def test_local_syntax_repair_does_not_touch_other_question(tmp_path):
    original = candidate(
        ["quadrilateral(A,B,C,D)", "angle(A,B)=45°"], children=[{"facts": ["t>1"]}]
    )
    repaired = deepcopy(original)
    repaired["root"]["facts"][1] = "angle(A,B,C)=45°"
    result = run(tmp_path, Sequence(original, repaired, OK))
    assert result["status"] == "reviewed_candidate", result
    assert result["semantic_calls"] == 3


def test_outside_changes_rejected_atomically_without_expanding_permissions(tmp_path):
    base = candidate(["t>0"], children=[{"facts": ["s=2"]}])
    bad = candidate(["t>0", "t>1"], children=[{"facts": ["s=9"]}])
    good = candidate(["t>0", "t>1"], children=[{"facts": ["s=2"]}])
    model = Sequence(base, finding(), bad, good, OK)
    result = run(tmp_path, model)
    assert result["status"] == "reviewed_candidate", result
    assert not result["events"][2]["adopted"]
    assert result["events"][2]["change_guard"]["violations"]
    assert json.loads(model.requests[3].prompt.user_prefix)["base_candidate"] == base


@pytest.mark.parametrize(
    "kind",
    [
        "missing_figure",
        "unreadable",
        "ambiguous_symbol",
        "occluded",
        "ambiguous_reuse",
        "unstructured",
    ],
)
def test_known_uncertainties_stop_without_review_or_automatic_resolution(
    tmp_path, kind
):
    result = run(
        tmp_path,
        Sequence(
            candidate(["t>0"], uncertainties=[{"kind": kind, "text": "来源问题"}])
        ),
    )
    assert result["semantic_calls"] == 1 and not result["source_reviewed"]
    assert result["continuation"]["blocked"]


@pytest.mark.parametrize(
    "review,status",
    [
        (
            {"status": "uncertain", "findings": finding()["findings"]},
            "needs_confirmation",
        ),
        (finding(kind="missing_figure"), "needs_confirmation"),
        (
            {"status": "confirmed", "findings": finding()["findings"]},
            "review.invalid_response",
        ),
        ({"status": "correction_required", "findings": []}, "review.invalid_response"),
        (finding(path="/root/facts/100"), "review.invalid_response"),
        ("{", "review.invalid_response"),
    ],
)
def test_review_stop_modes(tmp_path, review, status):
    result = run(tmp_path, Sequence(candidate(["t>0"]), review))
    assert result["status"] == status
    assert not result["source_reviewed"] and result["semantic_calls"] == 2


def test_code_gap_is_not_returned_as_a_model_mistake(tmp_path):
    result = run(tmp_path, Sequence(candidate(["Γ:y=a*x^2", "P=axis(Γ)∩x_axis"])))
    assert result["status"] == "code_gap"
    assert result["semantic_calls"] == 1
    assert result["diagnostics"][0]["code"] == "binding.intersection_not_proven_unique"


def test_no_progress_and_budget_stops(tmp_path):
    base = candidate(["t>0"])
    result = run(tmp_path / "same", Sequence(base, finding(), base))
    assert result["status"] == "workflow.no_progress"
    result = run(
        tmp_path / "budget", Sequence(base, finding()), budget=Budget(content=1)
    )
    assert (
        result["status"] == "workflow.budget_exhausted"
        and result["semantic_calls"] == 2
    )


def test_looping_source_corrections_stop_on_previous_revision(tmp_path):
    a, b = candidate(["t=1"]), candidate(["t=2"])
    model = Sequence(
        a,
        finding("/root/facts/0", "wrong_expression"),
        b,
        finding("/root/facts/0", "wrong_expression"),
        a,
    )
    result = run(tmp_path, model)
    assert result["status"] == "workflow.oscillation"
    assert result["candidate"] == b


def test_crash_unknown_and_concurrent_reservations_never_repay(tmp_path):
    request = setup(tmp_path)
    model = Sequence(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        run_workflow(request, model, tmp_path / "run", [], problem_id="synthetic")
    recovered = run_workflow(
        request, Sequence(), tmp_path / "run", [], problem_id="synthetic"
    )
    assert recovered["status"] == "workflow.outcome_unknown"
    assert recovered["network_reserved"] == 2
    with (
        Ledger(tmp_path / "lock", {}, Budget()),
        pytest.raises(WorkflowStop, match="concurrent"),
        Ledger(tmp_path / "lock", {}, Budget()),
    ):
        pass


EVALUATION = json.loads(
    (
        Path(__file__).parent / "fixtures/math-notation-v1/review-evaluation-24.json"
    ).read_text()
)["cases"]


@pytest.mark.parametrize("case", EVALUATION, ids=lambda case: case["id"])
def test_review_evaluation_candidates_are_legal_and_recorded_reviews_route(
    tmp_path, case
):
    from shuxueshuo_server.problem_understanding.notation_compile import (
        NotationValidator,
    )
    from shuxueshuo_server.problem_understanding.notation_semantics import compare
    from shuxueshuo_server.problem_understanding.workflow_diagnostics import (
        review_diagnostics,
    )

    for payload in (case["candidate"], case["reference"]):
        report = NotationValidator().validate(payload)
        assert report.ok, report.issues
    review = validate_review(json.dumps(case["expected_review"]), case["candidate"])
    is_good = review["status"] == "confirmed"
    assert compare(case["candidate"], case["reference"])["ok"] == is_good
    routed = review_diagnostics(review)
    assert not routed if is_good else routed
    if not is_good and all(d["action"] == "repair" for d in routed):
        assert guard_changes(
            case["candidate"], case["reference"], permissions(case["candidate"], routed)
        )["ok"]
    # These are recorded outcomes, not a measurement of model review accuracy.
    responses = [case["candidate"], review]
    if not is_good and all(d["action"] == "repair" for d in routed):
        responses.extend([case["reference"], OK])
    result = run(tmp_path, Sequence(*responses))
    assert result["status"] in {"reviewed_candidate", "needs_confirmation"}, result


def test_stale_inputs_and_tampered_responses_do_not_get_adopted(tmp_path):
    request = setup(tmp_path)
    run_workflow(
        request,
        Sequence(candidate(["t>0"]), OK),
        tmp_path / "run",
        [],
        problem_id="synthetic",
    )
    with pytest.raises(WorkflowStop, match="stale_binding"):
        run_workflow(request, Sequence(), tmp_path / "run", [], problem_id="different")
    ledger_path = tmp_path / "run/ledger.json"
    ledger = json.loads(ledger_path.read_text())
    ledger["calls"][0]["base_revision"] = "stale"
    save(ledger_path, ledger)
    result = run_workflow(
        request, Sequence(), tmp_path / "run", [], problem_id="synthetic"
    )
    assert result["status"] == "workflow.stale_response"


def test_provider_failure_is_persistent_and_does_not_enter_repair(tmp_path):
    model = Sequence(TimeoutError())
    result = run(tmp_path, model)
    assert result["status"] == "workflow.provider_failed"
    assert run(tmp_path, Sequence())["status"] == result["status"]


def test_schema_examples_and_request_boundaries(tmp_path):
    request = setup(tmp_path)
    examples = json.loads(EXAMPLES_PATH.read_text())
    assert len(examples) == 11
    for example in examples:
        validate_review(json.dumps(example["review"]), example["candidate"])
    original = candidate(["t>0"])
    parsed = parse_candidate(
        json.dumps(original),
        problem_id="synthetic",
        source_sha256=request.images[0].artifact.sha256,
        registry_snapshot=revision([]),
        registered_families=[],
    )
    review = request_for(request, "review", original, [], validation=parsed)
    repair = request_for(request, "repair", candidate(["t>0"]), [], [], [])
    assert json.loads(review.prompt.user_prefix)["few_shots"] == examples
    assert "few_shots" not in json.loads(repair.prompt.user_prefix)
    for item in (request, repair):
        assert (
            not {"candidate_contract", "code_validation"}
            & json.loads(item.prompt.user_prefix).keys()
        )
    for item in (request, review, repair):
        assert item.images == request.images
        payload = json.loads(item.prompt.user_prefix)
        assert "math_expression_catalog" in payload and "response_schema" in payload
        assert (
            not {"gold", "answers", "acceptance_policy", "reasoning_content"}
            & payload.keys()
        )
        assert all(
            not page["lines"] and not page["formula_candidates"]
            for page in payload.get("ocr_hints", {}).get("pages", [])
        )
        assert "function-quantifiers" not in item.prompt.user_prefix
    assert all(p.exists() for p in FILES)


def test_review_contract_meanings_and_enums_follow_candidate_schema():
    source = schema()
    summary = candidate_contract_summary()
    scope = source["$defs"]["Scope"]
    assert summary["scope"] == scope["description"]
    variants = scope["properties"]["goals"]["items"]["oneOf"]
    assert {goal["kind"] for goal in summary["goal_kinds"]} == {
        goal["properties"]["kind"]["const"] for goal in variants
    }
    for goal, short in zip(variants, summary["goal_kinds"], strict=True):
        assert short["meaning"] == goal["description"]
        assert short["required"] == goal["required"]
        assert set(short["required"] + short["optional"]) == set(goal["properties"])
        for field, meaning in summary["goal_fields"].items():
            if field in goal["properties"]:
                assert meaning == goal["properties"][field]["description"]
    assert len(json.dumps(summary)) < len(json.dumps(source)) / 3


@pytest.mark.parametrize(
    "failure",
    ["missing", "revision", "contract", "image", "registry", "valid", "ir", "match"],
)
def test_review_rejects_unverified_or_stale_code_check_summary(tmp_path, failure):
    request = setup(tmp_path)
    original = candidate(["t>0"])
    parsed = parse_candidate(
        json.dumps(original),
        problem_id="synthetic",
        source_sha256=request.images[0].artifact.sha256,
        registry_snapshot=revision([]),
        registered_families=[],
    )
    if failure == "missing":
        parsed = None
    elif failure == "revision":
        original["root"]["facts"].append("t>1")
    elif failure == "contract":
        parsed["contract"] = "problem-domain/v1"
    elif failure == "image":
        parsed["binding"]["source_sha256"] = "other-image"
    elif failure == "registry":
        parsed["binding"]["registry_snapshot"] = "other-registry"
    elif failure == "valid":
        parsed["contract_valid"] = False
    else:
        parsed["reports"][failure]["ok"] = False
    with pytest.raises(ValueError, match="review.invalid_validation_context"):
        request_for(request, "review", original, [], validation=parsed)


def test_review_readability_examples_stop_without_guessing_or_extra_calls(tmp_path):
    examples = {item["id"]: item for item in json.loads(EXAMPLES_PATH.read_text())}
    unclear = examples["unreadable_relation"]
    model = Sequence(unclear["candidate"], unclear["review"])
    result = run(tmp_path / "unclear", model)
    assert result["parse_status"] == "valid"
    assert result["status"] == "needs_confirmation"
    assert result["source_status"] == "uncertain" and not result["source_reviewed"]
    assert result["candidate"] == unclear["candidate"]
    assert result["content_calls"] == result["review_calls"] == 1
    assert result["diagnostics"][0]["code"] == "unreadable"
    clear = examples["readable_relation_control"]
    result = run(tmp_path / "clear", Sequence(clear["candidate"], clear["review"]))
    assert result["source_reviewed"] and result["status"] == "reviewed_candidate"


@pytest.mark.parametrize(
    "before,after",
    [
        (["t>1"], []),
        (["∀x∈ℝ:x^2>=0"], ["x^2>=0"]),
        (["a=1 ∨ a=2"], ["a=1"]),
        (["min(t)=2"], ["t=2"]),
    ],
)
def test_syntax_grant_never_allows_deleting_requirements(before, after):
    result = guard_changes(
        candidate(before),
        candidate(after),
        [{"path": "/root/facts/0", "mode": "replace"}],
    )
    assert not result["ok"]


def test_scope_move_requires_content_preservation_and_arrays_use_base_indexes():
    a = candidate(["s=3"], children=[{"facts": ["t=1"]}, {"facts": ["u=2"]}])
    b = candidate([], children=[{"facts": ["t=1"]}, {"facts": ["u=2", "s=3"]}])
    allowed = [{"path": "/root", "mode": "subtree"}]
    assert guard_changes(a, b, allowed)["ok"]
    b["root"]["children"][0]["facts"] = []
    assert not guard_changes(a, b, allowed)["ok"]
    # Deleting index zero must not silently authorize editing original index one.
    assert not guard_changes(
        candidate(["a=1", "b=2"]),
        candidate(["b=9"]),
        [{"path": "/root/facts/0", "mode": "replace"}],
    )["ok"]


def test_compatible_field_placement_order_and_optional_arrays_need_no_repair(tmp_path):
    value = candidate(["a=1", "b=2"], definitions=["Γ:y=x^2"])
    changed = candidate(["b=2", "Γ:y=x^2"], definitions=["a=1"], children=[])
    assert guard_changes(value, changed, [])["ok"]
    result = run(tmp_path, Sequence(changed, OK))
    assert result["content_calls"] == 1 and result["status"] == "reviewed_candidate"


def test_target_repair_does_not_authorize_changing_state():
    a = candidate(
        ["t=min(t)"], goals=[{"kind": "find_coordinates", "object": "unknown"}]
    )
    b = deepcopy(a)
    b["root"]["goals"][0].update(object="P")
    b["root"]["facts"][0] = "t=1"
    parsed = parse_candidate(
        json.dumps(a),
        problem_id="s",
        source_sha256="0" * 64,
        registry_snapshot="0" * 64,
        registered_families=[],
    )
    allowed = permissions(a, diagnose(parsed, a))
    assert not guard_changes(a, b, allowed)["ok"]
    assert json_pointer("r.c1.goals[0]") == "/root/children/1/goals/0"


def test_semantically_idle_repair_stops_even_when_reordered(tmp_path):
    a = candidate(["t>0", "u=sqrt(3)"])
    b = candidate(["u=√3", "t > 0"])
    result = run(tmp_path, Sequence(a, finding(), b))
    assert result["status"] == "workflow.no_progress"
    assert result["candidate"] == a


def test_six_semantic_twelve_network_ceiling_and_budget_reservation(tmp_path):
    class TwoAttempts(Sequence):
        def complete(self, request):
            response = super().complete(request)
            response.provider_attempts = ({"attempt": 1}, {"attempt": 2})
            return response

    a, b, c = (candidate([f"t={v}"]) for v in (1, 2, 3))
    feedback = finding("/root/facts/0", "wrong_expression")
    result = run(tmp_path / "full", TwoAttempts(a, feedback, b, feedback, c, OK))
    assert result["status"] == "reviewed_candidate"
    assert result["semantic_calls"] == 6 and result["network_attempts"] == 12
    result = run(tmp_path / "network", TwoAttempts(a), budget=Budget(network=3))
    assert result["status"] == "workflow.budget_exhausted"
    assert result["semantic_calls"] == 1


def test_truncated_content_never_adopted_and_truncated_review_stops(tmp_path):
    class TruncatedFirst(Sequence):
        def complete(self, request):
            response = super().complete(request)
            if self.calls == 1:
                response.finish_reason = "length"
            return response

    result = run(
        tmp_path / "content", TruncatedFirst(candidate(["t=9"]), candidate(["t=1"]), OK)
    )
    assert result["candidate"] == candidate(["t=1"])
    assert (
        result["first_candidate"] is None and result["first_finish_reason"] == "length"
    )
    model = Sequence(candidate(["t>0"]), OK)
    original = model.complete

    def complete(request):
        response = original(request)
        if model.calls == 2:
            response.finish_reason = "length"
        return response

    model.complete = complete
    result = run(tmp_path / "review", model)
    assert (
        result["status"] == "review.invalid_response" and not result["source_reviewed"]
    )


def test_response_bytes_and_workflow_code_are_bound_to_reservations(
    tmp_path, monkeypatch
):
    from shuxueshuo_server.problem_understanding import workflow

    result = run(tmp_path, Sequence(candidate(["t>0"]), OK))
    response = tmp_path / "run/calls/01-extract/response.json"
    stored = json.loads(response.read_text())
    stored["text"] = json.dumps(candidate(["t<0"]))
    save(response, stored)
    assert run(tmp_path, Sequence())["status"] == "workflow.response_hash_mismatch"
    monkeypatch.setattr(workflow, "frozen_files", dict)
    with pytest.raises(WorkflowStop, match="stale_binding"):
        run(tmp_path, Sequence())
    assert result["source_reviewed"]


def test_batch_freezes_all_cases_before_calls_and_records_first_final(tmp_path):
    from shuxueshuo_server.problem_understanding.batch_smoke import (
        CASES,
        NOTATION_FIXTURES,
        run_batch,
    )
    from shuxueshuo_server.solver.extraction.multimodal_provider import (
        problem_domain_family_catalog,
    )

    case = CASES[-1]
    output = tmp_path / "batch"

    class FrozenBeforeCalls(Sequence):
        def complete(self, request):
            frozen = json.loads((output / "frozen-batch.json").read_text())
            assert set(frozen["cases"]) == {case}
            assert frozen["cases"][case]["budget"]["content"] == 3
            assert frozen["cases"][case]["model"] == "deepseek-flash"
            assert frozen["cases"][case]["image_transport"] == "base64"
            return super().complete(request)

    gold = json.loads((NOTATION_FIXTURES / (case + ".json")).read_text())
    model = FrozenBeforeCalls(gold, OK)
    result = run_batch(
        output,
        (case,),
        lambda: model,
        list(problem_domain_family_catalog()),
        workflow="review-repair",
    )
    assert result["first_passed"] == result["passed"] == 1
    assert result["wall_seconds"] >= 0 and model.calls == 2
    assert result["image_transport_by_case"] == {case: "base64"}
    assert result["kpi_by_image_transport"]["base64"]["passed"] == 1
    # Simulate a historical batch without the newly added summary labels.
    result["results"][case].pop("image_transport")
    save(output / "batch-summary.json", result)
    from tools.report_math_notation_workflow import report

    report(output, tmp_path / "report")
    rendered = json.loads((tmp_path / "report/results.json").read_text())
    assert rendered["cases"][0]["image_transport"] == "base64"
    assert rendered["kpi_by_image_transport"]["base64"]["passed"] == 1


def test_array_changes_cannot_guess_correspondence_after_reordering():
    a = candidate(["a=1", "b=2", "c=3"])
    b = candidate(["c=3", "b=4", "a=5"])
    allowed = [{"path": f"/root/facts/{i}", "mode": "source_edit"} for i in (0, 1)]
    guard = guard_changes(a, b, allowed)
    assert not guard["ok"] and guard["actual_diff"]


def test_missing_goal_container_only_allows_append():
    a = candidate(goals=[{"kind": "find_value", "expression": "p"}])
    diagnostics = [
        {
            "stage": "review",
            "code": "wrong_goal",
            "path": "/root/goals",
            "action": "repair",
        }
    ]
    assert not guard_changes(a, candidate(goals=[]), permissions(a, diagnostics))["ok"]


def test_unknown_reference_can_add_only_its_local_definition(tmp_path):
    a = candidate(
        children=[
            {"definitions": ["P=(0,1)"]},
            {"goals": [{"kind": "find_coordinates", "object": "P"}]},
        ]
    )
    b = deepcopy(a)
    b["root"]["children"][1]["definitions"] = ["P=(1,0)"]
    result = run(tmp_path, Sequence(a, b, OK))
    assert result["status"] == "reviewed_candidate", result["diagnostics"]
    scopes = result["events"][1]["allowed_changes"]
    assert {r["path"] for r in scopes} == {
        "/root/children/1/goals/0/object",
        "/root/children/1/definitions",
        "/root/uncertainties",
    }


def test_optional_variable_hint_and_math_equivalence_do_not_retry(tmp_path):
    a = candidate(
        ["P∈x_axis", "x(P)>0"],
        goals=[{"kind": "find_minimum", "expression": "x(P)^2", "variables": ["P"]}],
    )
    b = deepcopy(a)
    del b["root"]["goals"][0]["variables"]
    for i, value in enumerate((a, b)):
        result = run(tmp_path / str(i), Sequence(value, OK))
        assert result["status"] == "reviewed_candidate" and result["content_calls"] == 1


def test_source_uncertainty_discovered_during_repair_stops_without_fabrication(
    tmp_path,
):
    a = candidate(["t>0"])
    b = candidate(
        ["t>0"], uncertainties=[{"kind": "unreadable", "text": "原图该条件无法确认"}]
    )
    result = run(tmp_path, Sequence(a, finding(), b))
    assert result["status"] == "needs_confirmation"
    assert result["candidate"] == b and not result["source_reviewed"]
    assert result["semantic_calls"] == 3


@pytest.mark.parametrize("replacement", ["1=1", "t=t", "t^2-t^2=0"])
def test_syntax_cannot_disguise_condition_deletion_as_tautology(replacement):
    guard = guard_changes(
        candidate(["angle(A,B)=45°"]),
        candidate([replacement]),
        [{"path": "/root/facts/0", "mode": "replace"}],
    )
    assert not guard["ok"]


def test_invalid_json_pointer_escape_is_not_silently_resolved():
    with pytest.raises(ValueError, match="pointer_escape"):
        validate_review(json.dumps(finding("/root/~2")), candidate())


def test_source_evidence_can_remove_invented_state_but_syntax_cannot():
    a = candidate(
        ["p>1", "p=min(p)"], goals=[{"kind": "find_value", "expression": "p"}]
    )
    b = candidate(["p>1"], goals=[{"kind": "find_value", "expression": "p"}])
    path = "/root/facts/1"
    assert guard_changes(
        a, b, [{"path": path, "mode": "source_edit", "reason": "unsupported_addition"}]
    )["ok"]
    assert not guard_changes(a, b, [{"path": path, "mode": "replace"}])["ok"]


def test_usage_keeps_reasoning_breakdown_and_unknowns():
    from shuxueshuo_server.problem_understanding.workflow_usage import call_usage

    response = {
        "metadata": {
            "usage": {"prompt_tokens": 100, "completion_tokens": 21},
            "provider_attempts": [
                {"usage": {"completion_tokens_details": {"reasoning_tokens": 8}}},
                {"usage": {"completion_tokens_details": {"reasoning_tokens": 9}}},
            ],
        }
    }
    counted = call_usage(response)
    assert counted["reasoning_tokens"] == 17 and counted["visible_output_tokens"] == 4
    assert call_usage({})["input_tokens"] is None
    response["metadata"].pop("provider_attempts")
    assert call_usage(response)["reasoning_tokens"] is None


LIVE_RECORDINGS = (
    Path(__file__).parent / "fixtures/math-notation-v1/recorded-review-repair-20260916"
)
LIVE_MANIFEST = json.loads((LIVE_RECORDINGS / "manifest.json").read_text())


@pytest.mark.parametrize(
    "entry", LIVE_MANIFEST["cases"], ids=lambda entry: entry["case"]
)
def test_recorded_real_workflow_preserves_responses_and_reassesses_equivalence(
    entry, tmp_path
):
    from shuxueshuo_server.problem_understanding.notation_semantics import evaluate
    from shuxueshuo_server.solver.extraction.multimodal_provider import (
        problem_domain_family_catalog,
    )

    for filename, digest in entry["files"].items():
        assert sha256((LIVE_RECORDINGS / filename).read_bytes()).hexdigest() == digest
    responses = [(LIVE_RECORDINGS / c["file"]).read_text() for c in entry["calls"]]
    if assert_removed_at_rejected(json.loads(responses[0])):
        return  # No adapter or artificial repair response for obsolete recordings.
    fixture = prepare_fixture(entry["case"], tmp_path / "fixture")
    registry = list(problem_domain_family_catalog())
    request = build_request(
        fixture, ExtractionArtifactStore(tmp_path / "inputs"), registry
    )
    assert request.images[0].artifact.sha256 == entry["image_sha256"]
    model = Sequence(*responses)
    result = run_workflow(
        request, model, tmp_path / "run", registry, problem_id=entry["case"]
    )
    expected = json.loads(
        (LIVE_RECORDINGS / (entry["case"] + ".gold.json")).read_text()
    )
    policy_path = LIVE_RECORDINGS / (entry["case"] + ".acceptance-policy.json")
    policy = json.loads(policy_path.read_text()) if policy_path.exists() else None
    checked = evaluate(expected, result["candidate"], policy)
    assert checked["ok"] == entry["expected_offline_passed"], checked
    assert result["source_reviewed"] == entry["source_reviewed"]
    assert model.calls == len(entry["calls"])
    if entry["case"] == "k-quad":
        assert result["status"] == "needs_confirmation" and result["review_calls"] == 0
        assert checked["accepted_omissions"] and not checked["strict"]["ok"]


@pytest.mark.parametrize("missing", [False, True])
def test_transcription_repair_has_narrow_authority_and_is_reviewed_again(tmp_path, missing):
    original = candidate(["t>0"])
    if not missing:
        original["original_text"] = "t>0"
    corrected = {**original, "original_text": "已知实数t>0。"}
    review = finding("" if missing else "/original_text", "wrong_transcription", "题干原文缺失或被改写")
    checked = validate_review(json.dumps(review), original)
    grants = permissions(original, review_diagnostics(checked, original))
    assert grants[0] == {"path": "/original_text", "mode": "source_edit", "reason": "wrong_transcription"}
    assert guard_changes(original, corrected, grants)["ok"]
    drift = deepcopy(corrected)
    drift["root"]["facts"] = ["t>=0"]
    assert not guard_changes(original, drift, grants)["ok"]
    if missing:
        assert not guard_changes(corrected, original, grants)["ok"]
    model = Sequence(original, review, corrected, OK)
    result = run(tmp_path, model)
    assert result["source_reviewed"] and result["status"] == "reviewed_candidate"
    assert len(model.requests) == 4
    wire = [json.loads(req.prompt.user_prefix) for req in model.requests]
    assert wire[1]["candidate"] == original
    assert wire[1]["candidate_contract"]["original_text"] == schema()["properties"]["original_text"]["description"]
    assert wire[2]["base_candidate"] == original
    assert wire[2]["diagnostics"][0]["source"] == original.get("original_text")
    assert wire[2]["allowed_changes"] == grants
    assert wire[3]["candidate"] == corrected
    assert all(not req.evidence_pack.printed_text for req in model.requests)


def test_transcription_cannot_be_silently_algebraically_rewritten():
    original = {**candidate(["t>0"]), "original_text": "t>0"}
    changed = {**original, "original_text": "0<t"}
    assert not guard_changes(original, changed, [])["ok"]
    assert guard_changes(original, changed, [{"path": "/original_text", "mode": "source_edit"}])["ok"]
    del changed["original_text"]
    assert not guard_changes(original, changed, [{"path": "/original_text", "mode": "source_edit"}])["ok"]


@pytest.mark.parametrize("exists,path", [(True, "/root"), (True, ""), (False, "/root")])
def test_transcription_findings_cannot_grant_a_math_subtree(exists, path):
    original = candidate(["t>0"])
    if exists:
        original["original_text"] = "已知实数t>0。"
    with pytest.raises(ValueError, match="invalid_transcription_pointer"):
        validate_review(json.dumps(finding(path, "wrong_transcription")), original)
