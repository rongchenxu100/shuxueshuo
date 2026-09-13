"""Nine real domain adapters driven by the build's frozen stage registry."""
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request
from uuid import UUID

from PIL import Image, ImageOps
from sqlalchemy import select

from .application import load_application
from .config import REPO
from .db import transaction
from . import models as m
from .errors import Conflict, IntegrityFailure, ProductError
from .execution import ExecutionContext, AuditedClient
from .repositories import row
from .runtime_config import load_runtime
from .transport import context_for


class StageRunner:
    def __init__(self, context):
        self.x = context
        self.adapters = {key: getattr(self, key) for key in ('source', 'observation', 'extraction', 'projection', 'solver', 'evidence', 'lesson', 'visual', 'page')}

    def run(self):
        x = self.x
        definitions = x.build['pipeline_snapshot']['stages']
        keys = [s['stage_key'] for s in definitions]
        if any(k not in self.adapters for k in keys): raise Conflict('pipeline.unsupported_adapter')
        start = keys.index(x.build['from_stage'])
        for position, definition in enumerate(definitions):
            x.guard()
            key = definition['stage_key']
            with transaction(x.service.db) as c:
                stage = row(c, m.build_stages, build_id=x.build['id'], stage_key=key)
                accepted = row(c, m.stage_attempts, id=stage['accepted_attempt_id']) if stage['accepted_attempt_id'] else None
            if accepted:
                x.restore(stage, accepted)
                continue
            if position < start:
                with transaction(x.service.db) as c:
                    parent = row(c, m.build_stages, build_id=x.build['parent_build_id'], stage_key=key)
                    old = row(c, m.stage_attempts, id=parent['accepted_attempt_id']) if parent else None
                    if not old: raise IntegrityFailure('checkpoint.parent_missing')
                    outputs = x.service._attempt_outputs(c, old['id'])
                    if key == 'extraction':
                        parent_build = row(c, m.builds, id=x.build['parent_build_id'])
                        parent_resolved = parent_build['resolved_revision_id'] if parent_build else None
                        if parent_resolved != x.build['requested_revision_id']:
                            raise IntegrityFailure('checkpoint.revision_mismatch')
                x.restore(parent, old)
                x.service.commit_stage(*x.args, key, manifest_artifact_id=old['manifest_artifact_id'],
                    checkpoint_artifact_id=old['checkpoint_artifact_id'], outputs=outputs, reused_from_attempt_id=old['id'])
                if key == 'extraction': x.service.bind_requested_revision(*x.args)
                continue
            x.begin(key)
            summary = self.adapters[key]()
            x.complete(summary)
        package = x.read('page', 'page_manifest')
        x.service.finish_page(*x.args, entry_artifact_id=UUID(package['entry_artifact_id']),
            package_manifest_artifact_id=UUID(str(x.refs[('page', 'page_manifest')]['artifact_id'])),
            assets={k: UUID(v) for k, v in package['assets'].items()})

    def ocr(self, phase):
        x = self.x
        work, source_id = str(x.work), str(x.build['source_id'])
        url = (os.environ.get('PRODUCT_OCR_URL') or '').rstrip('/')
        if url:
            payload = json.dumps({'work_dir': work, 'source_id': source_id, 'phase': phase}).encode()
            request = urllib.request.Request(
                f'{url}/v1/observe', data=payload, method='POST',
                headers={'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(request, timeout=900) as response:
                    body = json.loads(response.read().decode())
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode(errors='replace')
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    x.add('OCR 进程日志', {'exit_code': 1, 'stdout': '', 'stderr': f'sidecar HTTP {exc.code}: {raw}'}, role='validation')
                    raise ProductError('observation.provider_failed') from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                x.add('OCR 进程日志', {'exit_code': 1, 'stdout': '', 'stderr': f'sidecar request failed: {exc}'}, role='validation')
                raise ProductError('observation.provider_failed') from exc
            exit_code = int(body.get('exit_code', 1))
            x.add('OCR 进程日志', {
                'exit_code': exit_code, 'stdout': body.get('stdout', ''), 'stderr': body.get('stderr', ''),
                'via': 'sidecar', 'url': url,
            }, role='validation')
            if exit_code:
                raise ProductError('observation.provider_failed')
        else:
            interpreter = os.environ.get('REVIEW_OCR_PYTHON', str(REPO / 'server/.venv-ocr/bin/python'))
            if not Path(interpreter).is_file(): raise ProductError('configuration.ocr_missing')
            result = subprocess.run([interpreter, '-m', 'shuxueshuo_server.product.observation', work, source_id, phase],
                cwd=REPO / 'server', env={**os.environ, 'PYTHONPATH': str(REPO / 'server')}, capture_output=True, timeout=900)
            x.add('OCR 进程日志', {'exit_code': result.returncode, 'stdout': result.stdout.decode(errors='replace'),
                                'stderr': result.stderr.decode(errors='replace')}, role='validation')
            if result.returncode: raise ProductError('observation.provider_failed')
        journal = x.work / f'{phase}-journal.json'
        if journal.exists():
            for entry in json.loads(journal.read_text()):
                name = entry['path']
                if Path(name).name != name: raise IntegrityFailure('observation.path')
                content = (x.work / name).read_bytes()
                if entry['media_type'] == 'application/json': content = json.loads(content)
                x.add(entry['name'], content, role=entry['role'], mime=entry['media_type'])

    def source(self):
        x = self.x
        with x.service.storage.open(x.source['storage_key']) as f: raw = f.read()
        with Image.open(BytesIO(raw)) as image:
            normalized = BytesIO()
            ImageOps.exif_transpose(image).convert('RGB').save(normalized, format='PNG')
        (x.work / 'normalized.png').write_bytes(normalized.getvalue())
        x.add('规范化图片', normalized.getvalue(), mime='image/png', kind='source_normalized')
        self.ocr('source')
        x.validate_restored('source')
        return '来源已校验并规范化'

    def observation(self):
        x = self.x
        (x.work / 'normalized.png').write_bytes(x.bytes('source', '规范化图片'))
        (x.work / 'initial.json').write_text(json.dumps(x.read('source', 'Source / selection / initial Context')))
        self.ocr('observation')
        from shuxueshuo_server.review.replay import archive_bytes, ARCHIVE
        x.add(ARCHIVE, archive_bytes(x.work / 'extraction-artifacts'), mime='application/zip')
        x.validate_restored('observation')
        return '版面、文字、公式与观察 Context 已生成'

    def extraction(self):
        x = self.x
        from shuxueshuo_server.solver.extraction.context import ExtractionAttemptLedger, SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND
        from shuxueshuo_server.solver.extraction.problem_domain_service import ProblemDomainExtractionService
        from shuxueshuo_server.solver.extraction.multimodal_provider import DoubaoMultimodalExtractionProvider
        from shuxueshuo_server.review.replay import archive_bytes, ARCHIVE, extraction_store
        initial, observation, _ = x.contexts()
        store = extraction_store(x.work / 'extraction-artifacts')
        with transaction(x.service.db) as c:
            revision = row(c, m.problem_revisions, id=x.build['requested_revision_id']) if x.build['requested_revision_id'] else None
        if revision and revision['kind'] == 'manual':
            from shuxueshuo_server.review.problem_edit import validate
            from shuxueshuo_server.solver.extraction.problem_domain_context import ProblemDomainContextTransitionService
            with transaction(x.service.db) as c:
                base = row(c, m.problem_revisions, id=revision['parent_revision_id'])
            checked, verified = validate(revision['domain_json'], {'domain': base['domain_json'], 'verified': base['verified_json']})
            x.add('人工修订完整校验', checked.report.to_payload(), role='validation')
            if not verified: raise ProductError('revision.revalidation_failed')
            put = lambda kind, value: store.put_json(kind=kind, payload=value)
            final = ProblemDomainContextTransitionService().accepted(observation,
                verified_problem=verified, solver_projection=checked.projection,
                verified_artifact=put('verified_problem', verified.to_payload()),
                solver_problem_projection_artifact=put(SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND, checked.projection.to_payload()),
                validation_artifact=put('problem_validation_report', checked.report.to_payload()),
                attempt_ledger=ExtractionAttemptLedger.for_context(observation), ancestor_contexts=(initial,), producer='product_human_revision')
            x.add('Extraction Context ancestry', [initial.to_payload(), observation.to_payload()])
            x.service.bind_requested_revision(*x.args)
        else:
            if not x.config.doubao_api_key: raise ProductError('configuration.extraction_key_missing')
            provider = AuditedClient(DoubaoMultimodalExtractionProvider(api_key=x.config.doubao_api_key,
                base_url=x.config.doubao_base_url, model=x.config.doubao_model, request_timeout=180), x)
            result = ProblemDomainExtractionService(input_artifact_reader=store, output_artifact_store=store, provider=provider).run(
                observation, attempt_ledger=ExtractionAttemptLedger.for_context(observation), ancestor_contexts=(initial,), max_attempts=3)
            for attempt in result.attempts: x.add(f'attempt {attempt.attempt_number} 校验与采用情况', attempt, role='validation')
            if not result.accepted: raise ProductError('extraction.blocked')
            final, verified = result.final_context, result.verified_problem
            # Revision binding and accepting the extraction checkpoint commit together.
            x.pending_revision = verified.to_payload()['graph']
        x.add('Extraction Context', final)
        x.add('VerifiedProblem', verified)
        x.add(ARCHIVE, archive_bytes(x.work / 'extraction-artifacts'), mime='application/zip')
        x.bundle()
        return '题意通过正式校验并绑定修订'

    def projection(self):
        from shuxueshuo_server.solver.extraction.problem_planner_authority import VerifiedPlannerProblemAuthority
        x = self.x
        bundle = x.bundle()
        authority = VerifiedPlannerProblemAuthority.from_bundle(bundle)
        x.add('已验证题意', bundle.verified_problem, role='input')
        x.add('Solver ProblemIR', bundle.canonical_solver_input)
        x.add('Bundle authority', bundle.authority_token)
        x.add('Planning Context', authority.planning_context.authority_payload())
        return '来源、题意与 Solver 输入身份一致'

    def solver(self):
        from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
        from shuxueshuo_server.solver.runtime.strategy_runtime_planner import strategy_planner_provider
        from shuxueshuo_server.review.pipeline import DebugJournal, solver_debug_role
        from shuxueshuo_server.review.replay import evidence_checkpoint, EVIDENCE
        x = self.x
        if not x.config.deepseek_api_key: raise ProductError('configuration.solver_key_missing')
        client = x.config.build_llm_client(thinking_effort='low')
        orchestrator = RuntimeOrchestrator(family_registry=x.config.build_family_registry(), planner_providers={},
            default_planner_provider=strategy_planner_provider(mode='deepseek', client=AuditedClient(client, x),
                allow_same_problem_few_shot=False, functional_few_shot_mode=x.config.functional_few_shot_mode),
            max_attempts=x.config.max_llm_attempts, debug_dir=str(x.work / 'planner'))
        with DebugJournal(x.work / 'planner', lambda name, doc: x.add(name, doc, role=solver_debug_role(name))):
            result = orchestrator.solve_verified(x.bundle())
            x.add('执行检查与结果摘要', result.to_dict(), role='validation')
        success = orchestrator.last_success_artifacts
        if not result.ok or success is None or success.verified_functional_execution is None: raise ProductError('solver.failed')
        x.add('VerifiedFunctionalPlanExecution', success.verified_functional_execution)
        x.add(EVIDENCE, evidence_checkpoint(success))
        return '所有目标经验证完成'

    def evidence(self):
        from shuxueshuo_server.review.replay import restore_evidence, EVIDENCE
        from shuxueshuo_server.solver.explanation.snapshot import ExplanationSnapshotBuilder
        from shuxueshuo_server.solver.explanation.annotated_teaching import AnnotatedTeachingPlanProjector
        x = self.x
        success = restore_evidence(x.bundle(), x.read('solver', 'VerifiedFunctionalPlanExecution'), x.read('solver', EVIDENCE), x.config)
        snapshot = ExplanationSnapshotBuilder().build(success)
        x.add('ExplanationSnapshot', snapshot)
        x.add('AnnotatedTeachingPlan', AnnotatedTeachingPlanProjector().project(snapshot).plan)
        return '仅从已验证执行投影教学材料'

    def lesson(self):
        from shuxueshuo_server.solver.explanation.models import explanation_snapshot_from_payload
        from shuxueshuo_server.solver.explanation.scope_lesson import ScopeLessonAuthoringService
        from shuxueshuo_server.solver.explanation.lesson_ir import RecursiveLessonIRAssembler
        x = self.x
        snapshot = explanation_snapshot_from_payload(x.read('evidence', 'ExplanationSnapshot'))
        generation = ScopeLessonAuthoringService(client=AuditedClient(x.config.build_llm_client(), x)).generate(snapshot)
        x.add('实际响应 Schema', generation.output_schema, role='input')
        x.add('生成审计', generation.metadata_payload(), role='validation')
        x.add('校验与 fallback', generation.validation, role='validation')
        build = RecursiveLessonIRAssembler().assemble(snapshot, generation.projection, generation.validation)
        x.add('LessonIR（实际采用）', build.lesson)
        x.add('组装 provenance', build.assembly_authority)
        return '采用 deterministic fallback（见校验）' if generation.validation.fallback_used else '采用通过校验的学生讲解'

    def visual(self):
        from shuxueshuo_server.solver.explanation.models import explanation_snapshot_from_payload
        from shuxueshuo_server.solver.explanation.lesson_ir import lesson_ir_from_payload
        from shuxueshuo_server.solver.visual.builder import VisualStepBuilder
        from shuxueshuo_server.solver.visual.validator import VisualStepIRValidator
        from shuxueshuo_server.solver.visual.compiler import forward_compile
        x = self.x
        snapshot = explanation_snapshot_from_payload(x.read('evidence', 'ExplanationSnapshot'))
        lesson = lesson_ir_from_payload(x.read('lesson', 'LessonIR（实际采用）'))
        visual = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
        VisualStepIRValidator().validate(visual, lesson=lesson)
        x.add('VisualStepIR', visual)
        compiled = forward_compile(visual)
        for name, value in (('geometry-spec.json', compiled.geometry_spec), ('step-decorations.json', compiled.step_decorations), ('lesson-data.json', compiled.lesson_data)):
            x.add(name, value)
        return '确定性图形和交互已生成并通过校验'

    def page(self):
        from shuxueshuo_server.review.pipeline import inspect_page
        x = self.x
        output = x.work / 'page'
        output.mkdir(exist_ok=True)
        for name in ('geometry-spec.json', 'step-decorations.json', 'lesson-data.json'):
            data = x.read('visual', name)
            if name == 'lesson-data.json': data.setdefault('meta', {})['outputPath'] = str(output / 'lesson.html')
            (output / name).write_text(json.dumps(data, ensure_ascii=False))
        for tool, args in (('validate-geometry-spec.mjs', []), ('build-lesson-page.mjs', ['--standalone', '--product-preview'])):
            result = subprocess.run(['node', str(REPO / 'tools' / tool), str(output), *args], cwd=REPO, capture_output=True, text=True, timeout=180)
            x.add(tool, {'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}, role='validation')
            if result.returncode: raise ProductError('page.compile_failed')
        html = (output / 'lesson.html').read_bytes()
        inspect_page(html)
        entry = x.add('page_html', html, kind='page_html', page=True, mime='text/html')
        x.add('page_manifest', {'schema_version': 'product-page/v1', 'entry_artifact_id': str(entry['id']), 'assets': {'index.html': str(entry['id'])}},
              kind='page_manifest', schema='product-page/v1')
        return '解析网页已编译并通过检查'


def main():
    build_id, execution_id, epoch = UUID(sys.argv[1]), UUID(sys.argv[2]), int(sys.argv[3])
    a = load_application()
    try:
        with transaction(a.db) as c:
            build = row(c, m.builds, id=build_id)
            ctx = context_for(c, build)
        x = ExecutionContext(a, ctx, build_id, execution_id, epoch)
        try: StageRunner(x).run()
        except Exception as exc:
            code = str(exc) if isinstance(exc, ProductError) else 'pipeline.' + type(exc).__name__
            try:
                a.service.record_diagnostic(*x.args, code=code, message=x.redact(str(exc))[:2000], stage_attempt_id=x.attempt['id'] if x.attempt else None)
                a.service.finish_failure(*x.args, code, interrupted=False)
            except Conflict: pass
            print(code, flush=True)
            return 1
        return 0
    finally: a.close()


if __name__ == '__main__': sys.exit(main())
