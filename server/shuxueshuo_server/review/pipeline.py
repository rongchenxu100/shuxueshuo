"""Production adapters for the cold path; no corpus/expected/approved inputs."""
from collections.abc import Mapping
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import subprocess
import time
from threading import Event, Thread

from .store import REPO
from .replay import (KEYS, EVIDENCE, read_json, save_archive, restore_archive,
                     extraction_store as relocated_extraction_store, evidence_checkpoint, restore_evidence)


def payload(value):
    if hasattr(value, "to_payload"):
        return value.to_payload()
    if isinstance(value, Mapping):
        return {k: payload(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [payload(v) for v in value]
    return value


class AuditedClient:
    """Observe the existing client contract without changing retry/selection."""
    def __init__(self, client, store, run_id, stage):
        self.client, self.store, self.run_id, self.stage = client, store, run_id, stage
        self.attempt = 0

    def __getattr__(self, key):
        return getattr(self.client, key)

    def complete(self, request):
        self.attempt += 1
        title = f"attempt {self.attempt}"
        req = request.redacted_payload() if hasattr(request, "redacted_payload") else request
        request_ref = self.store.add(self.run_id, self.stage, "input", f"{title} 实际请求", req)
        if hasattr(request, "images"):
            for image in request.images:
                self.store.add(self.run_id, self.stage, "input", f"{title} 图片 {image.role}", image.content, image.artifact.media_type)
        started, result, error = time.time(), None, None
        try:
            result = self.client.complete(request)
            self.store.add(self.run_id, self.stage, "raw", f"{title} 原始返回",
                           result.text if hasattr(result, "text") else result, "text/plain",
                           dependencies=[request_ref["id"]])
            if hasattr(result, "raw_payload"):
                self.store.add(self.run_id, self.stage, "raw", f"{title} provider payload", result.raw_payload)
            return result
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            meta = result.metadata_payload() if hasattr(result, "metadata_payload") else {
                "provider": getattr(self.client, "provider_name", None),
                "request_model": getattr(self.client, "model", None),
                "response_model": getattr(self.client, "last_response_model", None) if result is not None else None,
                "usage": getattr(self.client, "last_usage", None) if result is not None else None,
                "provider_attempts": getattr(self.client, "last_provider_attempts", None) if result is not None else None,
            }
            self.store.add(self.run_id, self.stage, "call", f"{title} 调用记录", {
                **meta, "attempt": self.attempt, "error": error,
                "duration_seconds": time.time() - started, "request_artifact_id": request_ref["id"],
                "visible_response": result is not None,
            })


def solver_debug_role(name):
    """Keep raw authoring distinct from generated intermediate/final Plans."""
    kind = name.rsplit("/", 1)[-1].split(".", 1)[-1].removesuffix(".json")
    if kind in {"raw-response", "functional-plan", "provider-responses", "provider-reasoning"}:
        return "raw"
    if kind in {"request", "prompt", "provider-requests", "base-plan", "base-checkpoint", "base-authority"} or kind.startswith("payload."):
        return "input"
    if kind in {"normalized-response", "normalized-content", "candidate-plan", "compiled-plan", "canonical-plan", "compiled-planner-output", "verified-execution"}:
        return "output"
    return "validation"


class DebugJournal:
    """Publish completed execution/checkpoint files while the solver is running."""
    def __init__(self, directory, publish):
        self.directory, self.publish = directory, publish
        self.seen, self.errors = {}, []
        self.stop = Event()
        self.thread = Thread(target=self.watch, daemon=True)

    def scan(self):
        for path in sorted(self.directory.rglob("*.json"), key=lambda p: p.stat().st_mtime_ns):
            try:
                raw = path.read_bytes()
                doc = json.loads(raw)
            except (OSError, ValueError):
                continue  # A writer may not have finished the file yet.
            digest = sha256(raw).hexdigest()
            if self.seen.get(path) != digest:
                self.publish(str(path.relative_to(self.directory)), doc)
                self.seen[path] = digest

    def watch(self):
        try:
            while not self.stop.wait(0.3):
                self.scan()
        except Exception as exc:
            self.errors.append(exc)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        self.scan()
        if self.errors:
            raise self.errors[0]


def inspect_page(html):
    class Page(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if (tag == "script" and "src" in attrs) or (tag == "link" and attrs.get("rel") == "stylesheet"):
                raise ValueError("page.external_dependency: standalone 编译仍包含外部资源")
    Page().feed(html.decode("utf-8"))


def source_version():
    files = sorted((REPO / "server/shuxueshuo_server").rglob("*.py"))
    files += sorted(p for p in (REPO / "tools").rglob("*.mjs") if "tests" not in p.parts)
    files += sorted((REPO / "internal/templates").glob("*.html"))
    files += sorted((REPO / "site/assets/js").glob("*.js"))
    files += sorted((REPO / "site/assets/css").glob("*.css"))
    for directory in ("internal/llm-prompts", "internal/schemas"):
        files += sorted(path for path in (REPO / directory).rglob("*") if path.is_file())
    files += [REPO / "internal/config/style-presets.json"]
    digest = sha256()
    for path in files:
        digest.update(str(path.relative_to(REPO)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def generate(store, run_id):
    from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
    from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
    from shuxueshuo_server.solver.runtime.strategy_runtime_planner import strategy_planner_provider
    from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
    from shuxueshuo_server.solver.extraction.context import ProblemExtractionContext, ExtractionAttemptLedger
    from shuxueshuo_server.solver.extraction.problem_domain_service import ProblemDomainExtractionService
    from shuxueshuo_server.solver.extraction.multimodal_provider import create_vision_provider
    from shuxueshuo_server.solver.extraction.problem_solver_bundle import VerifiedSolverProblemBundleLoader
    from shuxueshuo_server.solver.extraction.problem_planner_authority import VerifiedPlannerProblemAuthority
    from shuxueshuo_server.solver.explanation.snapshot import ExplanationSnapshotBuilder
    from shuxueshuo_server.solver.explanation.annotated_teaching import AnnotatedTeachingPlanProjector
    from shuxueshuo_server.solver.explanation.scope_lesson import ScopeLessonAuthoringService
    from shuxueshuo_server.solver.explanation.lesson_ir import RecursiveLessonIRAssembler
    from shuxueshuo_server.solver.visual.builder import VisualStepBuilder
    from shuxueshuo_server.solver.visual.validator import VisualStepIRValidator
    from shuxueshuo_server.solver.visual.compiler import forward_compile

    from .rebuild import BuildGuard
    from .versions import Versions
    from .problem_edit import install, load_contexts
    guard = BuildGuard(store, run_id)
    versions = Versions(store)
    problem_revision = versions.revision(versions.info(run_id)["run_revision_id"])
    manual = problem_revision is not None and problem_revision["kind"] == "manual"

    def add(stage, role, name, value, media="application/json"):
        return store.add(run_id, stage, role, name, payload(value), media)
    def start(stage, summary=""):
        guard.check()
        store.stage(run_id, stage, "running", summary)
    def done(stage, summary):
        guard.complete(stage)
        store.stage(run_id, stage, "succeeded", summary)

    from_stage = store.get(run_id).get("from_stage", "source")
    position = KEYS.index(from_stage)
    def runs(stage):
        return KEYS.index(stage) >= position

    if runs("observation"):
        start("source", "检查上传来源与真实运行环境")
    else:
        start(from_stage, "恢复已保存输入；使用当前代码重新执行")
    config = SolverRuntimeConfig.from_sources(planner_mode="strategy", llm_provider="deepseek",
        allow_same_problem_few_shot=False)
    store.secrets = tuple(s for s in (config.deepseek_api_key, config.doubao_api_key) if s)
    if (runs("solver") or runs("lesson")) and not config.deepseek_api_key:
        raise ValueError("configuration.missing: 需要 DEEPSEEK_API_KEY；不会切换 Mock")
    if runs("extraction") and not manual and not config.deepseek_api_key:
        raise ValueError("configuration.missing: 需要 DEEPSEEK_API_KEY；不会切换 Mock")
    ocr_python = Path(os.environ.get("REVIEW_OCR_PYTHON", REPO / "server/.venv-ocr/bin/python"))
    if runs("observation") and not ocr_python.is_file():
        raise ValueError("configuration.ocr_missing: 未找到独立 OCR Python")
    revision = source_version()
    add(from_stage, "input", "运行配置 / 代码与 Spec 版本", {
        "source_version": revision, "extraction_model": config.deepseek_vision_model,
        "planner_model": config.llm_model or config.deepseek_model,
        "lesson_model": config.llm_model or config.deepseek_model,
        "planner_attempt_budget": config.max_llm_attempts, "extraction_attempt_budget": 3,
        "planner_pass1_thinking": "enabled", "planner_retry_thinking": "enabled",
        "planner_reasoning_effort": "low",
        "lesson_thinking": "disabled", "review_contract": "review-run/v1", "mode": "live",
    })
    work = store.root / run_id / "work"
    work.mkdir(exist_ok=True)
    if runs("observation"):
        env = {**os.environ, "PYTHONPATH": str(REPO / "server"), "PYTHONUNBUFFERED": "1"}
        ocr = subprocess.run([str(ocr_python), "-m", "shuxueshuo_server.review.ocr", str(store.root), run_id],
                             cwd=REPO / "server", env=env, capture_output=True, text=True, timeout=900)
        add("observation", "validation", "OCR 进程日志", {"exit_code": ocr.returncode, "stdout": ocr.stdout, "stderr": ocr.stderr})
        if ocr.returncode:
            raise RuntimeError(f"observation.failed: OCR 进程退出 {ocr.returncode}，查看 OCR 进程日志")
        save_archive(store, run_id, "observation")
        guard.complete("source")
        guard.complete("observation")
    if position <= KEYS.index("evidence"):
        from shuxueshuo_server.solver.extraction.context import ProblemExtractionContext
        initial = ProblemExtractionContext.from_payload(read_json(store, run_id, "source", "Source / selection / initial Context"))
        context = ProblemExtractionContext.from_payload(read_json(store, run_id, "observation", "Observation Context"), ancestor_contexts=(initial,))
        if not runs("observation"):
            restore_archive(store, run_id, "observation" if from_stage == "extraction" else "extraction")
        extraction_store = relocated_extraction_store(store.root / run_id / "extraction-artifacts")

    if runs("extraction") and manual:
        start("extraction", "校验人工修订并生成新的验证题意与 Context")
        install(store, run_id, problem_revision, context, (initial,), extraction_store)
        done("extraction", "人工题意通过完整校验；未调用抽取模型")
    elif runs("extraction"):
        start("extraction", "真实多模态题意抽取与数学合同校验")
        add("extraction", "input", "输入 Observation Context", context)
        provider = AuditedClient(create_vision_provider(config), store, run_id, "extraction")
        service = ProblemDomainExtractionService(input_artifact_reader=extraction_store,
            output_artifact_store=extraction_store, provider=provider)
        extraction = service.run(context, attempt_ledger=ExtractionAttemptLedger.for_context(context),
                                 ancestor_contexts=(initial,), max_attempts=3)
        for attempt in extraction.attempts:
            add("extraction", "validation", f"attempt {attempt.attempt_number} 校验与采用情况", attempt)
            if attempt.resulting_draft:
                add("extraction", "output", f"attempt {attempt.attempt_number} 题意草稿", attempt.resulting_draft)
            if attempt.patch:
                add("extraction", "output", f"attempt {attempt.attempt_number} 修复", attempt.patch)
        add("extraction", "output", "Extraction Context", extraction.final_context)
        if not extraction.accepted:
            raise ValueError(f"extraction.blocked: {extraction.blocked_reason}")
        add("extraction", "output", "VerifiedProblem", extraction.verified_problem)
        done("extraction", f"题意通过校验 · {len(extraction.attempts)} 次尝试")

        save_archive(store, run_id, "extraction")
    if position <= KEYS.index("evidence"):
        final_context, ancestors = load_contexts(store, run_id)
        bundle = VerifiedSolverProblemBundleLoader().load(final_context, extraction_store, ancestor_contexts=ancestors)
        authority = VerifiedPlannerProblemAuthority.from_bundle(bundle)
    if runs("projection"):
        start("projection")
        add("projection", "input", "已验证题意", bundle.verified_problem)
        add("projection", "output", "Solver ProblemIR", bundle.canonical_solver_input)
        add("projection", "output", "Bundle authority", bundle.authority_token)
        add("projection", "output", "Planning Context", authority.planning_context.authority_payload())
        done("projection", "来源、题意与 Solver 输入身份一致")

    if runs("solver"):
        start("solver", "规划与事务执行；保留真实 attempt 顺序")
        add("solver", "input", "ProblemPlanningContext", authority.planning_context.authority_payload())
        planner_client = AuditedClient(config.build_llm_client(thinking_effort="low"), store, run_id, "solver")
        debug_dir = work / "planner"
        orchestrator = RuntimeOrchestrator(family_registry=config.build_family_registry(),
            planner_providers={}, default_planner_provider=strategy_planner_provider(mode="deepseek",
                client=planner_client, allow_same_problem_few_shot=False,
                functional_few_shot_mode=config.functional_few_shot_mode,
                argument_encoding=config.argument_encoding),
            max_attempts=config.max_llm_attempts, debug_dir=str(debug_dir))
        with DebugJournal(debug_dir, lambda name, doc: add("solver", solver_debug_role(name), name, doc)):
            result = orchestrator.solve_verified(bundle)
            add("solver", "validation", "执行检查与结果摘要", result.to_dict())
        success = orchestrator.last_success_artifacts
        if not result.ok or success is None or success.verified_functional_execution is None:
            raise ValueError("solver.failed: 没有完整的已验证执行产物，停止教学生成")
        add("solver", "output", "VerifiedFunctionalPlanExecution", success.verified_functional_execution)
        add("solver", "output", EVIDENCE, evidence_checkpoint(success))
        done("solver", "所有目标经验证完成")

    elif from_stage == "evidence":
        success = restore_evidence(bundle, read_json(store, run_id, "solver", "VerifiedFunctionalPlanExecution"),
                                   read_json(store, run_id, "solver", EVIDENCE), config)

    if runs("evidence"):
        start("evidence")
        add("evidence", "input", "已验证执行", success.verified_functional_execution)
        snapshot = ExplanationSnapshotBuilder().build(success)
        add("evidence", "output", "ExplanationSnapshot", snapshot)
        projection = AnnotatedTeachingPlanProjector().project(snapshot)
        add("evidence", "output", "AnnotatedTeachingPlan", projection.plan)
        done("evidence", "仅从已验证执行投影教学材料")

    elif position <= KEYS.index("visual"):
        from shuxueshuo_server.solver.explanation.models import explanation_snapshot_from_payload
        snapshot = explanation_snapshot_from_payload(read_json(store, run_id, "evidence", "ExplanationSnapshot"))

    if runs("lesson"):
        start("lesson", "一次语义调用；校验后采用或明确标记 fallback")
        projection = AnnotatedTeachingPlanProjector().project(snapshot)
        add("lesson", "input", "ExplanationSnapshot", snapshot)
        add("lesson", "input", "教学材料", projection.plan)
        generation = ScopeLessonAuthoringService(client=AuditedClient(config.build_llm_client(), store, run_id, "lesson")).generate(snapshot)
        add("lesson", "input", "实际响应 Schema", generation.output_schema)
        add("lesson", "validation", "生成审计", generation.metadata_payload())
        add("lesson", "validation", "校验与 fallback", generation.validation)
        add("lesson", "output", "实际采用的讲解内容", generation.validation.accepted_content)
        if generation.validation.repaired_response is not None:
            add("lesson", "output", "语法修复后的返回（不是原始响应）", generation.validation.repaired_response, "text/plain")
        build = RecursiveLessonIRAssembler().assemble(snapshot, generation.projection, generation.validation)
        add("lesson", "output", "LessonIR（实际采用）", build.lesson)
        add("lesson", "output", "组装 provenance", build.assembly_authority)
        done("lesson", "采用 deterministic fallback（见校验）" if generation.validation.fallback_used else "采用通过校验的 LLM 学生讲解")

        lesson = build.lesson
    elif from_stage == "visual":
        from shuxueshuo_server.solver.explanation.lesson_ir import lesson_ir_from_payload
        lesson = lesson_ir_from_payload(read_json(store, run_id, "lesson", "LessonIR（实际采用）"))

    output = work / "page"
    output.mkdir(exist_ok=True)
    if runs("visual"):
        start("visual")
        add("visual", "input", "ExplanationSnapshot", snapshot)
        from shuxueshuo_server.solver.runtime.methods import method_spec_payloads
        from shuxueshuo_server.solver.runtime.recipes.registry import recipe_spec_payloads
        add("visual", "input", "VisualSpec 注册表快照", {"source_version": revision,
            "methods": [{"method_id": spec["method_id"], "visual": spec.get("visual")} for spec in method_spec_payloads()],
            "recipes": [{"recipe_id": spec["recipe_id"], "visual": spec.get("visual")} for spec in recipe_spec_payloads()]})
        add("visual", "input", "LessonIR", lesson)
        visual = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
        add("visual", "output", "VisualStepIR", visual)
        VisualStepIRValidator().validate(visual, lesson=lesson)
        add("visual", "validation", "VisualStepIR 校验", {"ok": True})
        compiled = forward_compile(visual)
        compiled.lesson_data.setdefault("meta", {})["outputPath"] = str(output / "lesson.html")
        for name, doc in (("geometry-spec.json", compiled.geometry_spec),
                          ("step-decorations.json", compiled.step_decorations), ("lesson-data.json", compiled.lesson_data)):
            add("visual", "output", name, doc)
            (output / name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        done("visual", "确定性图形、交互及页面 JSON 已生成")

    else:
        for name in ("geometry-spec.json", "step-decorations.json", "lesson-data.json"):
            doc = read_json(store, run_id, "visual", name)
            if name == "lesson-data.json":
                doc.setdefault("meta", {})["outputPath"] = str(output / "lesson.html")
            add("page", "input", name, doc)
            (output / name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    start("page")
    add("page", "input", "编译输入 manifest", {"source_version": revision, "mode": "standalone",
        "artifacts": [a["id"] for a in store.get(run_id)["artifacts"] if a["stage"] == "visual" and a["role"] == "output"]})
    for tool, args in (("validate-geometry-spec.mjs", []), ("build-lesson-page.mjs", ["--standalone"])):
        proc = subprocess.run(["node", str(REPO / "tools" / tool), str(output), *args],
                              cwd=REPO, capture_output=True, text=True, timeout=180)
        add("page", "validation", tool, {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
        if proc.returncode:
            raise ValueError(f"page.compile_failed: {tool}")
    guard.check()
    html = (output / "lesson.html").read_bytes()
    inspect_page(html)
    add("page", "validation", "页面资源与版本一致性", {"ok": True, "source_version": revision, "standalone": True})
    store.add(run_id, "page", "output", "lesson.html", html, "text/html", page_path="lesson.html")
    done("page", "完整课程页已编译并通过检查")
