"""Nine real domain adapters driven by the build's frozen stage registry."""
from io import BytesIO
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
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
from .services import now
from .transport import context_for


class StageRunner:
    def __init__(self, context):
        self.x = context
        self.adapters = {key: getattr(self, key) for key in ('source', 'observation', 'extraction', 'projection', 'solver', 'evidence', 'lesson', 'visual', 'page')}

    def run(self):
        x = self.x
        if x.build['pipeline_key'] == 'problem_runtime_binding':
            from .runtime_binding import run_product
            return run_product(x)
        if x.build['pipeline_key'] == 'problem_understanding':
            from .understanding_runtime import run_product
            return run_product(x)
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
                        contract = next(s['contract_version'] for s in x.build['pipeline_snapshot']['stages'] if s['stage_key'] == 'extraction')
                        if contract != 'problem-math-notation/v1' and parent_resolved != x.build['requested_revision_id']:
                            raise IntegrityFailure('checkpoint.revision_mismatch')
                x.restore(parent, old)
                x.service.commit_stage(*x.args, key, manifest_artifact_id=old['manifest_artifact_id'],
                    checkpoint_artifact_id=old['checkpoint_artifact_id'], outputs=outputs, reused_from_attempt_id=old['id'])
                if key == 'extraction':
                    contract = next(s['contract_version'] for s in x.build['pipeline_snapshot']['stages'] if s['stage_key'] == 'extraction')
                    if contract != 'problem-math-notation/v1':
                        x.service.bind_requested_revision(*x.args)
                    else:
                        # Older checkpoint rebuilds created a child ledger row;
                        # keep it coherent when present.  New rebuilds that
                        # start after extraction retain the parent ledger and
                        # therefore legitimately have no child row to copy.
                        with transaction(x.service.db) as c:
                            parent_run = row(c, m.extraction_runs, build_id=x.build['parent_build_id'])
                            child_run = row(c, m.extraction_runs, build_id=x.build['id'])
                            if parent_run and child_run and parent_run['status'] == 'completed' and parent_run['candidate_id']:
                                c.execute(m.extraction_runs.update().where(m.extraction_runs.c.id == child_run['id']).values(
                                    status='completed', candidate_id=parent_run['candidate_id'],
                                    result_json=parent_run['result_json'], finished_at=now(c)))
                                c.execute(m.problems.update().where(m.problems.c.id == x.build['problem_id']).values(
                                    current_candidate_id=parent_run['candidate_id'], latest_extraction_run_id=child_run['id']))
                if key == 'projection':
                    contract = next(s['contract_version'] for s in x.build['pipeline_snapshot']['stages'] if s['stage_key'] == 'extraction')
                    if contract == 'problem-math-notation/v1':
                        with transaction(x.service.db) as c:
                            parent = row(c, m.builds, id=x.build['parent_build_id'])
                        if parent and parent['resolved_revision_id']:
                            x.service.bind_existing_revision(*x.args, parent['resolved_revision_id'])
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
        observation_mode = x.build.get('effective_config', {}).get('observation', {}).get('mode')
        if observation_mode == 'fast-pass':
            from .observation_fast_pass import run as run_fast_pass
            run_fast_pass(x, phase)
            return
        if observation_mode not in (None, 'ocr'):
            raise ProductError('configuration.observation_mode_invalid')
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
        extraction_contract = next(s['contract_version'] for s in x.build['pipeline_snapshot']['stages'] if s['stage_key'] == 'extraction')
        if extraction_contract == 'problem-math-notation/v1':
            return self.math_notation_extraction()
        raise ProductError('extraction.unsupported_contract')

    def math_notation_extraction(self):
        """Run the notation workflow inside this build's extraction attempt."""
        from .understanding import registry
        from .understanding_runtime import build_request
        from .understanding_storage import DatabaseWorkflowStorage
        from shuxueshuo_server.problem_understanding.workflow import run_workflow
        from shuxueshuo_server.solver.extraction.multimodal_provider import DeepSeekMultimodalExtractionProvider
        x = self.x
        with transaction(x.service.db) as c:
            run_row = row(c, m.extraction_runs, build_id=x.build['id'])
            run = dict(run_row) if run_row else None
            source = dict(row(c, m.problem_source_versions, id=run['source_version_id'])) if run else None
            candidate = row(c, m.problem_candidates, id=run['base_candidate_id']) if run and run['base_candidate_id'] else None
        if not run:
            raise ProductError('extraction.workflow_missing')
        if run['status'] == 'completed' and run['result_json']:
            result = run['result_json']
            x.add('problem-math-candidate.json', result.get('candidate'), schema='problem-math-notation/v1')
            x.add('problem-math-parsed.json', result.get('parsed'), schema='problem-math-notation-parse/v1')
            self._emit_math_diagnostics(result)
            x.add('problem-math-workflow.json', result, schema='problem-math-workflow/v1')
            x.add('problem-math-source-review.json', result.get('review'), schema='problem-math-source-review/v1')
            # StageRunner owns the single checkpoint/commit for every stage.
            # Keep this recovery path limited to restoring its outputs.
            return '恢复已持久化的数学记号候选与原图复核'
        store = DatabaseWorkflowStorage(x, run)
        store.guard()
        with transaction(x.service.db) as c:
            c.execute(m.extraction_runs.update().where(m.extraction_runs.c.id == run['id']).values(status='running'))
        if not x.config.deepseek_api_key:
            raise ProductError('configuration.extraction_key_missing')
        observation = x.read('observation', 'Observation Context')
        request = build_request(x.service, x.ctx, source, run['frozen']['registry'], observation=observation)
        provider = DeepSeekMultimodalExtractionProvider(
            api_key=x.config.deepseek_api_key, base_url='https://api.deepseek.com',
            model='deepseek-flash', request_timeout=300, max_output_tokens=16384,
            file_cache_dir=x.app.settings.root / 'deepseek-files-cache')
        result = run_workflow(request, provider, x.work, run['frozen']['registry'],
            problem_id=str(run['problem_id']), storage=store,
            initial_candidate=candidate['candidate_json'] if candidate else None,
            mode=run['mode'], source_hash=source['source_hash'])
        # Keep the workflow's durable ledger artifacts and expose the stable
        # extraction contract through the stage checkpoint.
        x.add('problem-math-candidate.json', result.get('candidate'), schema='problem-math-notation/v1')
        x.add('problem-math-parsed.json', result.get('parsed'), schema='problem-math-notation-parse/v1')
        self._emit_math_diagnostics(result)
        x.add('problem-math-workflow.json', result, schema='problem-math-workflow/v1')
        x.add('problem-math-source-review.json', result.get('review'), schema='problem-math-source-review/v1')
        with transaction(x.service.db) as c:
            c.execute(m.extraction_runs.update().where(m.extraction_runs.c.id == run['id']).values(
                status='completed', result_json=result, finished_at=datetime.now(timezone.utc)))
        return '数学记号候选与原图复核已持久化'

    def _emit_math_diagnostics(self, result):
        parsed = result.get('parsed') or {}
        x = self.x
        x.add('problem-math-normalized.json', parsed.get('objects', {}).get('ir'), role='validation')
        x.add('problem-math-compiled.json', parsed.get('objects', {}), role='validation')
        x.add('problem-math-continuation.json', parsed.get('continuation'), role='validation')
        x.add('problem-math-validation.json', parsed.get('reports', {}), role='validation')
        x.add('notation-diagnostics.json', result.get('diagnostics', []), role='validation')

    def projection(self):
        extraction_contract = next(s['contract_version'] for s in self.x.build['pipeline_snapshot']['stages'] if s['stage_key'] == 'extraction')
        if extraction_contract == 'problem-math-notation/v1':
            return self.math_runtime_projection()
        from shuxueshuo_server.solver.extraction.problem_planner_authority import VerifiedPlannerProblemAuthority
        x = self.x
        bundle = x.bundle()
        authority = VerifiedPlannerProblemAuthority.from_bundle(bundle)
        x.add('已验证题意', bundle.verified_problem, role='input')
        x.add('Solver ProblemIR', bundle.canonical_solver_input)
        x.add('Bundle authority', bundle.authority_token)
        x.add('Planning Context', authority.planning_context.authority_payload())
        return '来源、题意与 Solver 输入身份一致'

    def math_runtime_projection(self):
        x = self.x
        from shuxueshuo_server.problem_understanding.runtime_binding import authorize_binding
        try:
            binding, evidence = x.notation_binding()
            authority = authorize_binding(binding, evidence)
            x._notation_authority = authority
            x.service.bind_notation_revision(
                *x.args,
                graph=binding.bundle.source_graph.wire_payload(),
                semantic_hash=authority.bundle.authority_token.problem_semantic_hash,
                authority=authority.bundle.authority_payload(),
            )
        except Exception as exc:
            from shuxueshuo_server.problem_understanding.runtime_lowering import BindingError
            # ProductError stores the machine code in the message; its class
            # attribute .code is only the generic fallback "product.invalid".
            if isinstance(exc, BindingError):
                code = exc.code
            elif isinstance(exc, ProductError):
                code = str(exc) or 'product.invalid'
            else:
                code = getattr(exc, 'code', None) or 'binding.failed'
            if not isinstance(code, str) or not code:
                code = 'binding.failed'
            x.add('binding-diagnostic.json', {
                'schema_version': 'math-runtime-binding/v1', 'code': code,
                'message': str(exc), 'stage': 'projection',
                'path': getattr(exc, 'path', None),
            }, role='validation')
            # Admission refusals are expected product outcomes (unsupported /
            # incomplete source). Preserve the admission.* code so Studio can
            # show「暂不支持题型」instead of a generic system failure.
            raise ProductError(code) from exc
        for name, value in binding.artifacts().items():
            x.add('math-runtime-binding/' + name, value, role='output')
        x.add('Solver ProblemIR', authority.bundle.canonical_solver_input)
        x.add('Planning Context', authority.planning_context.authority_payload())
        x.add('Bundle authority', authority.bundle.authority_token)
        x.add('solver-authority.json', authority.bundle.authority_payload(), schema='solver-authority/v1')
        x.add('binding-result.json', {
            'schema_version': 'math-runtime-binding/v1',
            'source_identity': dict(binding.source_identity),
            'authority': authority.bundle.authority_payload(),
            'planning_context': authority.planning_context.authority_payload(),
        }, schema='math-runtime-binding/v1')
        return '数学记号已授权绑定到 Solver 输入'

    def solver(self):
        from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
        from shuxueshuo_server.solver.runtime.strategy_runtime_planner import strategy_planner_provider
        from shuxueshuo_server.review.pipeline import DebugJournal, solver_debug_role
        from shuxueshuo_server.review.replay import evidence_checkpoint, EVIDENCE
        x = self.x
        if not x.config.deepseek_api_key: raise ProductError('configuration.solver_key_missing')
        client = x.config.build_llm_client(thinking_effort='low')
        frozen_solver_config = x.build.get('effective_config', {}).get('solver', {})
        argument_encoding = frozen_solver_config.get('argument_encoding', x.config.argument_encoding)
        if argument_encoding not in ('source-ref', 'math-expression/v1'):
            raise ProductError('configuration.argument_encoding_invalid')
        orchestrator = RuntimeOrchestrator(family_registry=x.config.build_family_registry(), planner_providers={},
            default_planner_provider=strategy_planner_provider(mode='deepseek', client=AuditedClient(client, x),
                allow_same_problem_few_shot=False, functional_few_shot_mode=x.config.functional_few_shot_mode,
                argument_encoding=argument_encoding),
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
            if name == 'lesson-data.json':
                _use_reviewed_source_text(data, x)
                data.setdefault('meta', {})['outputPath'] = str(output / 'lesson.html')
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


def _use_reviewed_source_text(lesson_data, context):
    """Show the reviewed source transcription above the compiled lesson facts."""
    try:
        candidate = context.read('extraction', 'problem-math-candidate.json')
    except (KeyError, ProductError, TypeError, ValueError):
        return
    if not isinstance(candidate, dict):
        return
    value = candidate.get('original_text')
    if isinstance(value, str):
        source_lines = [line.strip() for line in value.splitlines() if line.strip()]
    elif isinstance(value, list):
        source_lines = [str(line).strip() for line in value if str(line).strip()]
    else:
        return
    if not source_lines or not isinstance(lesson_data.get('problem'), dict):
        return
    existing = lesson_data['problem'].get('lines') or []
    answers = [
        {'answerId': line['answerId'], 'answer': line.get('answer', '')}
        for line in existing
        if isinstance(line, dict) and line.get('answerId')
    ]
    chunks = []
    parent_mark = r'[（(]\s*(?:[0-9一二三四五六七八九十]+|[IVXⅠⅡⅢⅣⅤ]+)\s*[）)]'
    child_mark = r'[①②③④⑤⑥⑦⑧⑨⑩]'
    marker = re.compile(rf'(?={parent_mark}|(?={child_mark}))')
    for line in source_lines:
        chunks.extend(part.strip() for part in marker.split(line) if part.strip())
    if not chunks:
        chunks = source_lines
    parent_chunks = [
        index for index, line in enumerate(chunks)
        if re.search(parent_mark, line)
    ]
    child_chunks = [
        index for index, line in enumerate(chunks)
        if re.search(child_mark, line)
    ]
    # Answer slots follow section ownership: children between parent i and
    # parent i+1 belong to that section (parent is stem-only); a parent with
    # no children is itself answerable.  Flat （1）（2）（3） and heping-style
    # （Ⅰ）①②（Ⅱ） both fall out correctly; west-qing （1）（2）①② keeps （1）.
    if not parent_chunks:
        marker_chunks = child_chunks
    else:
        marker_chunks = [c for c in child_chunks if c < parent_chunks[0]]
        for i, parent_idx in enumerate(parent_chunks):
            next_parent = parent_chunks[i + 1] if i + 1 < len(parent_chunks) else len(chunks)
            kids = [c for c in child_chunks if parent_idx < c < next_parent]
            marker_chunks.extend(kids if kids else [parent_idx])
    for answer, index in zip(answers, marker_chunks):
        chunks[index] = {"text": chunks[index], **answer}
    lesson_data['problem']['lines'] = [
        item if isinstance(item, dict) else {"text": item}
        for item in chunks
    ]


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
