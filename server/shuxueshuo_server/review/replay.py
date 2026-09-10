"""Versioned, immutable stage boundaries. Never deserialize executable objects."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from types import SimpleNamespace
from zipfile import ZipFile, ZIP_DEFLATED

from .store import STAGES, TERMINAL

KEYS = [key for key, _ in STAGES]
ARCHIVE = "Extraction artifact checkpoint/v1"
EVIDENCE = "Evidence input checkpoint/v1"
REQUIRED = {
    "source": (), "observation": (("source", "规范化图片"),),
    "extraction": (("source", "Source / selection / initial Context"), ("observation", "Observation Context")),
    "projection": (("extraction", "Extraction Context"),),
    "solver": (("extraction", "Extraction Context"),),
    "evidence": (("solver", EVIDENCE), ("solver", "VerifiedFunctionalPlanExecution"), ("extraction", "Extraction Context")),
    "lesson": (("evidence", "ExplanationSnapshot"),),
    "visual": (("evidence", "ExplanationSnapshot"), ("lesson", "LessonIR（实际采用）")),
    "page": tuple(("visual", name) for name in ("geometry-spec.json", "step-decorations.json", "lesson-data.json")),
}


def find(doc, stage, name):
    return next((a for a in reversed(doc["artifacts"]) if a["stage"] == stage and a["name"] == name), None)


def read_json(store, run_id, stage, name):
    ref = find(store.get(run_id), stage, name)
    if ref is None:
        raise ValueError(f"replay.missing: {stage}/{name}")
    return json.loads(store.read(run_id, ref["id"])[1])


def archive_source(store, doc, stage):
    """Find old unregistered blobs only along an unchanged Context lineage."""
    seen = set()
    while doc["id"] not in seen:
        seen.add(doc["id"])
        ref = find(doc, stage, ARCHIVE)
        if ref:
            return doc["id"], ref
        directory = store.root / doc["id"] / "extraction-artifacts"
        if directory.is_dir():
            return doc["id"], None
        if not doc.get("parent_run_id"):
            break
        parent = store.get(doc["parent_run_id"])
        name = "Observation Context" if stage == "observation" else "Extraction Context"
        current_ref, parent_ref = find(doc, stage, name), find(parent, stage, name)
        if not current_ref or not parent_ref or current_ref["sha256"] != parent_ref["sha256"]:
            break
        doc = parent
    return None


def availability(store, doc):
    result = {}
    for stage in KEYS:
        before = KEYS[:KEYS.index(stage)]
        missing = [name for owner, name in REQUIRED[stage] if not find(doc, owner, name)]
        if stage in {"projection", "solver", "evidence"}:
            missing += [name for owner, name in REQUIRED["extraction"] if not find(doc, owner, name)]
        reason = ""
        if doc["status"] not in TERMINAL:
            reason = "请等待当前运行结束"
        elif any(s["status"] != "succeeded" for s in doc["stages"] if s["id"] in before):
            reason = "此前阶段尚未全部成功，请从更早的阶段重跑"
        elif missing:
            reason = "缺少恢复材料：" + "、".join(missing)
        elif stage in {"extraction", "projection", "solver", "evidence"}:
            owner = "observation" if stage == "extraction" else "extraction"
            if not archive_source(store, doc, owner):
                reason = "缺少抽取产物库，需从 OCR 阶段重跑"
        result[stage] = {"available": not reason, "reason": reason}
    return result


def archive_bytes(directory):
    out = BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                relative = str(path.relative_to(directory))
                # Attempt-ledger locks and mutable process journals are not
                # content-addressed inputs. The new invocation owns its ledger.
                if relative.startswith("_authority/"):
                    continue
                if not re.fullmatch(r"[a-f0-9]{2}/[a-f0-9]{64}\.[a-z0-9]+", relative):
                    raise ValueError("replay.invalid_artifact_path")
                content = path.read_bytes()
                if path.stem != sha256(content).hexdigest():
                    raise ValueError("replay.artifact_hash_mismatch")
                archive.writestr(relative, content)
    return out.getvalue()


def save_archive(store, run_id, stage):
    store.add(run_id, stage, "output", ARCHIVE,
              archive_bytes(store.root / run_id / "extraction-artifacts"), "application/zip")


def restore_archive(store, run_id, stage):
    ref = find(store.get(run_id), stage, ARCHIVE)
    if ref is None:
        raise ValueError("replay.missing_extraction_archive")
    root = store.root / run_id / "extraction-artifacts"
    with ZipFile(BytesIO(store.read(run_id, ref["id"])[1])) as archive:
        for entry in archive.infolist():
            if not re.fullmatch(r"[a-f0-9]{2}/[a-f0-9]{64}\.[a-z0-9]+", entry.filename):
                raise ValueError("replay.invalid_archive_path")
            content = archive.read(entry)
            path = root / entry.filename
            if path.stem != sha256(content).hexdigest() or path.parent.name != path.stem[:2]:
                raise ValueError("replay.artifact_hash_mismatch")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def extraction_store(root):
    from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
    class RelocatedStore(ExtractionArtifactStore):
        def read_bytes(self, artifact):
            # Locator is historical provenance. Resolve only within this run by
            # authenticated content hash, without mutating Context identities.
            matches = list(self.root.glob(f"{artifact.sha256[:2]}/{artifact.sha256}.*"))
            if not matches:
                raise ValueError("replay.missing_content_addressed_artifact")
            content = matches[0].read_bytes()
            if sha256(content).hexdigest() != artifact.sha256 or (artifact.byte_size is not None and len(content) != artifact.byte_size):
                raise ValueError("replay.artifact_hash_mismatch")
            return content
    return RelocatedStore(root)


def evidence_checkpoint(success):
    return {"schema_version": "review-evidence-input/v1", "answers": success.solver_result.answers,
            "execution_signature": success.verified_functional_execution.execution_signature,
            "steps": [{"step_id": step.step_id, "checks": [
                {"name": c.name, "status": c.status, "detail": c.detail} for c in step.checks]}
                for step in success.execution.step_results]}


def restore_evidence(bundle, execution_payload, checkpoint, config):
    """Reconstruct Snapshot inputs without running the planner or math methods."""
    from shuxueshuo_server.solver.runtime.functional_goal_execution import VerifiedFunctionalPlanExecution
    from shuxueshuo_server.solver.extraction.problem_planner_authority import VerifiedPlannerProblemAuthority
    from shuxueshuo_server.solver.extraction.problem_planning_binding import ProblemPlanningBindingCatalogBuilder
    from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
    from shuxueshuo_server.solver.runtime.planner_state_context import initial_planner_state_context
    from shuxueshuo_server.solver.runtime.orchestrator import ContextBuilder, ContextInventoryBuilder, SympyKernel, MethodSpecRegistry, extract_question_goals
    from shuxueshuo_server.solver.runtime.planner import PlannerInputs
    from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
    execution = VerifiedFunctionalPlanExecution.from_payload(execution_payload)
    if checkpoint["schema_version"] != "review-evidence-input/v1" or checkpoint["execution_signature"] != execution.execution_signature:
        raise ValueError("replay.execution_identity_mismatch")
    authority = VerifiedPlannerProblemAuthority.from_bundle(bundle)
    if execution.planning_context_id != authority.planning_context.planning_context_id:
        raise ValueError("replay.planning_context_mismatch")
    problem = bundle.build_solver_problem()
    family = config.build_family_registry().match(problem)
    context = ContextBuilder(SympyKernel()).build(problem)
    specs = MethodSpecRegistry.load_from_code()
    goals = extract_question_goals(problem)
    inputs = PlannerInputs(problem.problem_id, family, goals, ContextInventoryBuilder().build(context, specs), specs, problem=problem)
    problem_payload = problem_to_llm_payload(problem)
    handles = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    state = initial_planner_state_context(inputs, problem_payload=problem_payload, handle_registry=handles)
    bindings = ProblemPlanningBindingCatalogBuilder().build(bundle, authority.planning_context, state, handles, expected_token=bundle.authority_token)
    return SimpleNamespace(problem=problem, family=family, problem_authority=authority,
        problem_binding_catalog=bindings, question_goals=goals,
        solver_result=SimpleNamespace(status="ok", answers=checkpoint["answers"]),
        verified_functional_execution=execution,
        execution=SimpleNamespace(step_results=[SimpleNamespace(step_id=s["step_id"],
            checks=[SimpleNamespace(**c) for c in s["checks"]]) for s in checkpoint["steps"]]))
