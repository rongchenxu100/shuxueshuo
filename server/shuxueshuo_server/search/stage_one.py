"""Run graph-guided stage one on a student's cropped question image (no gold fixture)."""

import json
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from shuxueshuo_server.graph_lesson.stage_one.extraction import StageOneStorage
from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.workflow import run_workflow
from shuxueshuo_server.problem_understanding.workflow_ledger import Budget, save
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore

from .extraction import SearchStageOneContract, build_search_request
from .identity import mathematical_candidate
from .question_image import expected_image_hashes

RESULT_FILE = "result.json"


def run_question_image(png, output, provider, *, problem_id, original_png=None, read_graph_details=False):
    """Live entry: one processed image for text, then figure-only extraction if needed."""
    from .text_first import run_text_first

    return run_text_first(png, output, provider, problem_id=problem_id,
                          original_png=original_png, read_graph_details=read_graph_details)


def run_legacy_question_image(png, output, provider, *, problem_id, original_png=None, read_graph_details=False):
    """Write result.json with the workflow status, candidate, features and image identity.

    ``sent_image_sha256`` comes from the workflow ledger binding. Replays pass
    ``original_png`` only when the original recording actually sent that image.
    For offline replay of existing single/dual-view recordings only. New uploads
    use run_question_image and never enter this historical full-question rereading path.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    request = build_search_request(png, ExtractionArtifactStore(output / "inputs"), original_png=original_png)
    # Refuse to overwrite the sources of an existing workflow or display manifest.
    for name, content in (("question.png", png), ("original.png", original_png)):
        if content is None:
            continue
        path = output / name
        if path.is_symlink() or (path.exists() and path.read_bytes() != content):
            raise ValueError("image_input.source_changed")
        path.write_bytes(content)
    storage = StageOneStorage(output / "workflow")
    workflow = run_workflow(request, provider, storage.directory, [], problem_id=problem_id,
                            storage=storage, contract_adapter=SearchStageOneContract())
    _verify_images(request, storage.directory, png)
    workflow_dir, detail_plan, detail_attempt = output / 'workflow', None, None
    if (read_graph_details and original_png is not None and workflow.get('content_calls') == 1 and
            workflow.get('review_calls') == 0):
        from .graph_details import plan_details
        detail_plan = plan_details(workflow, original_png)
        if detail_plan:
            detail_request = build_search_request(png, ExtractionArtifactStore(output / 'detail-inputs'),
                                                 original_png=original_png, detail_plan=detail_plan)
            save(output / 'detail-reading.json', detail_plan)
            detail_storage = StageOneStorage(output / 'workflow-detail')
            detail_workflow = run_workflow(detail_request, provider, detail_storage.directory, [],
                problem_id=problem_id, storage=detail_storage, contract_adapter=SearchStageOneContract(),
                budget=Budget(content=1, review=1, semantic=2, network=4))
            _verify_images(detail_request, detail_storage.directory, png)
            detail_attempt = {key: detail_workflow.get(key) for key in
                              ('status', 'source_reviewed', 'content_calls', 'review_calls', 'network_attempts')}
            if detail_workflow.get('status') in ('reviewed_candidate', 'needs_confirmation'):
                workflow, request, workflow_dir = detail_workflow, detail_request, detail_storage.directory
            # A failed extra reading cannot erase the original uncertainty.
    public_candidate = workflow.get("candidate")
    candidate = mathematical_candidate(public_candidate)
    features = candidate_features(candidate)
    result = {
        "status": workflow.get("status"),
        "source_reviewed": workflow.get("source_reviewed", False),
        "output_contract": workflow.get("output_contract"),
        "public_candidate": public_candidate,
        "reviewed_candidate_revision": (workflow.get("review") or {}).get("revision"),
        "candidate": candidate,
        "features": features["features"],
        "features_ok": features.get("ok", False),
        "feature_diagnostics": features.get("diagnostics", []),
        "review_findings": _findings(workflow_dir),
        "confirmation_diagnostics": [d for d in workflow.get("diagnostics", [])
                                     if d.get("action") == "needs_confirmation"],
        # Internal errors are tagged code_gap too, but say nothing about the mathematics.
        "unsupported_diagnostics": [d for d in workflow.get("diagnostics", [])
                                    if d.get("action") == "code_gap" and d.get("stage") != "internal"],
        "question_sha256": sha256(png).hexdigest(),
        "sent_image_sha256": ledger_images(workflow_dir),
        "elapsed_seconds": round(perf_counter() - started, 3),
    }
    inputs = json.loads(request.prompt.user_prefix).get("image_inputs")
    if inputs:
        result['image_inputs'] = inputs
    if detail_attempt:
        result['detail_attempt'] = detail_attempt
        result['workflow_directory'] = workflow_dir.name
        if workflow_dir.name == 'workflow-detail':
            result['detail_reading'] = detail_plan
    if result['sent_image_sha256'] != expected_image_hashes(result):
        raise ValueError('image_input.sent_image_mismatch')
    from .reviewed_figures import install
    binding = install(output, result)
    if binding:
        result['figure_binding'] = binding
    from ..graph_lesson.stage_one.extraction import scopes
    if candidate and any(goal.get('kind') == 'select_function_graph'
                         for _, scope, _ in scopes(candidate['root']) for goal in scope.get('goals', [])) and not binding:
        result['features_ok'] = False
        result['feature_diagnostics'].append({'code': 'figure.reviewed_options_required'})
    save(output / RESULT_FILE, result)
    return result


def _verify_images(request, directory, png):
    result = {'question_sha256': sha256(png).hexdigest()}
    inputs = json.loads(request.prompt.user_prefix).get('image_inputs')
    if inputs:
        result['image_inputs'] = inputs
    if ledger_images(directory) != expected_image_hashes(result):
        raise ValueError('image_input.sent_image_mismatch')


def ledger_images(workflow_dir):
    path = Path(workflow_dir) / "ledger.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["identity"]["binding"]["images"]


def ledger_calls(workflow_dir):
    """(stage, status) of each model call so far, for progress display."""
    calls = []
    for directory in (Path(workflow_dir), *(Path(workflow_dir).with_name(name) for name in
                      ('workflow-detail', 'workflow-figures', 'workflow-figures-original'))):
        path = directory / 'ledger.json'
        if path.exists():
            calls.extend((call['stage'], call['status']) for call in json.loads(path.read_text())['calls'])
    return calls


def reviewing_candidate(workflow_dir):
    """The candidate a review call is checking, or None.

    A review is only requested for a candidate that passed schema and compile
    checks, so it can be shown before the review answers; ``candidate.json``
    must still be that exact revision (a later repair may have replaced it).
    """
    workflow_dir = Path(workflow_dir)
    detail_dir = workflow_dir.with_name('workflow-detail')
    if (detail_dir / 'ledger.json').exists():
        workflow_dir = detail_dir
    ledger, candidate = workflow_dir / "ledger.json", workflow_dir / "candidate.json"
    if not ledger.exists() or not candidate.exists():
        return None
    reviews = [c for c in json.loads(ledger.read_text(encoding="utf-8"))["calls"] if c["stage"] == "review"]
    value = json.loads(candidate.read_text(encoding="utf-8"))
    if not reviews or revision(value) != reviews[-1]["base_revision"]:
        return None
    return value


def _findings(workflow_dir):
    """Review findings of the last completed review call (missing figure, unreadable ...)."""
    workflow_dir = Path(workflow_dir)
    path = workflow_dir / "ledger.json"
    if not path.exists():
        return []
    reviews = [c for c in json.loads(path.read_text(encoding="utf-8"))["calls"]
               if c["stage"] == "review" and c["status"] == "completed" and c.get("response_file")]
    if not reviews:
        return []
    response = json.loads((workflow_dir / reviews[-1]["response_file"]).read_text(encoding="utf-8"))
    try:
        return json.loads(response["text"]).get("findings", [])
    except (KeyError, TypeError, ValueError):
        return []
