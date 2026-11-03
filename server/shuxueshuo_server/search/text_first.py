"""Keep ordinary questions on one image; append independently reviewed figure facts."""

import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import perf_counter

from PIL import Image

from ..graph_lesson.stage_one.extraction import StageOneStorage, validate_candidate
from ..graph_lesson.stage_one.runner import candidate_features
from ..problem_understanding.identity import revision
from ..problem_understanding.workflow import run_workflow
from ..problem_understanding.workflow_ledger import Budget, save
from ..solver.extraction.artifacts import ExtractionArtifactStore
from .extraction import SearchStageOneContract
from .figure_extraction import (
    FigureExtractionContract,
    build_figure_request,
    merge_figures,
    supported_inventory,
)
from .identity import EXTRACTION_CONTRACT, mathematical_candidate
from .question_image import question_png
from .text_extraction import (
    TextExtractionContract,
    build_text_request,
    graph_goals,
    reading_regions,
)


def _diagnostic(code, message, *, action='needs_confirmation'):
    return {'stage': 'figure', 'code': code, 'path': '/public_content/figure_detection',
            'message': message, 'action': action}


def run_text_first(png, output, provider, *, problem_id, original_png=None, read_graph_details=False):
    from .stage_one import _findings, _verify_images, ledger_images

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    # Keeping an original for display/retry does not include it in a request.
    if original_png is not None:
        with Image.open(BytesIO(original_png)) as original:
            if original.format != 'PNG' or question_png(original) != png:
                raise ValueError('image_input.crop_mismatch')
    for name, content in (('question.png', png), ('original.png', original_png)):
        path = output / name
        if content is not None and (path.is_symlink() or path.exists() and path.read_bytes() != content):
            raise ValueError('image_input.source_changed')
    for name, content in (('question.png', png), ('original.png', original_png)):
        if content is not None:
            (output / name).write_bytes(content)
    request = build_text_request(png, ExtractionArtifactStore(output / 'inputs'))
    text_workflow = run_workflow(request, provider, output / 'workflow', [], problem_id=problem_id,
                                 storage=StageOneStorage(output / 'workflow'), contract_adapter=TextExtractionContract())
    _verify_images(request, output / 'workflow', png)
    base = text_workflow.get('candidate')
    current = base
    status = text_workflow['status']
    reviewed = bool(text_workflow.get('source_reviewed'))
    diagnostics = list(text_workflow.get('diagnostics', []))
    findings = _findings(output / 'workflow')
    attempts, binding = [], None
    if status == 'reviewed_candidate' and (graph_goals(base) or reading_regions(base)):
        reviewed = False
        if not supported_inventory(base):
            status = 'needs_confirmation'
            diagnostics = [_diagnostic('figure.unsupported_inventory', '配图尚未完整定位，或超出当前图形读取范围。')]
        else:
            sources = [('workflow-figures', None)]
            if read_graph_details and original_png is not None:
                sources.append(('workflow-figures-original', original_png))
            for name, original in sources:
                try:
                    graph_request, manifest = build_figure_request(
                        png, base, ExtractionArtifactStore(output / (name + '-inputs')), original=original)
                except ValueError as exc:
                    status = 'needs_confirmation'
                    diagnostics = [_diagnostic(str(exc), '图形裁片太小或超过读取预算，请调整选区。')]
                    break
                save(output / name / 'image-inputs.json', manifest)
                workflow = run_workflow(graph_request, provider, output / name, [], problem_id=problem_id,
                    storage=StageOneStorage(output / name), contract_adapter=FigureExtractionContract(base),
                    # A malformed review may retry once against the same facts.
                    # Successful/uncertain reviews never consume this reserve.
                    budget=Budget(content=1, review=2, semantic=3, network=6))
                sent = ledger_images(output / name)
                if sent != [i.artifact.sha256 for i in graph_request.images]:
                    raise ValueError('image_input.sent_image_mismatch')
                attempts.append({'workflow_directory': name, 'status': workflow['status'],
                                 'content_calls': workflow['content_calls'], 'review_calls': workflow['review_calls']})
                findings = _findings(output / name)
                diagnostics = workflow.get('diagnostics', [])
                if workflow['status'] == 'reviewed_candidate' and workflow.get('source_reviewed'):
                    merged = merge_figures(base, workflow['candidate'])
                    parsed = SearchStageOneContract().parse(json.dumps(merged, ensure_ascii=False),
                        problem_id=problem_id, source_hash=sha256(png).hexdigest(), registry=[], store=None)
                    save(output / name / 'merged-validation.json', parsed)
                    if not parsed['contract_valid']:
                        status = 'needs_confirmation'
                        diagnostics = [_diagnostic('figure.merge_invalid', '图形事实与题干结构不一致，暂不能确认。')]
                        break
                    current, status, reviewed = merged, 'reviewed_candidate', True
                    binding = {'base_revision': revision(base), 'figure_revision': revision(workflow['candidate']),
                               'workflow_directory': name, 'image_inputs': manifest}
                    diagnostics = []
                    break
                # Preserve contract/transport/budget failures as system errors;
                # only an actual reading uncertainty asks the student to retake.
                status = workflow['status']
                # Retry only a genuine pixel-reading ambiguity, never schema/transport failures.
                if not (workflow['status'] == 'needs_confirmation' and diagnostics and
                        all(d.get('code') in {'figure.uncertain_facts', 'unreadable', 'ambiguous'}
                            for d in diagnostics)):
                    break
    candidate = mathematical_candidate(current)
    valid = bool(candidate and validate_candidate(candidate)['contract_valid'])
    features = candidate_features(candidate) if valid else {
        'ok': False, 'features': [], 'diagnostics': [{'code': 'figure.pending_or_invalid_mathematics'}]}
    result = {
        'pipeline': 'text-then-figures/v1', 'output_contract': EXTRACTION_CONTRACT,
        'status': status, 'source_reviewed': reviewed, 'public_candidate': current, 'candidate': candidate,
        'reviewed_candidate_revision': revision(current) if reviewed else None,
        'features': features['features'], 'features_ok': bool(reviewed and features['ok']),
        'feature_diagnostics': features.get('diagnostics', []), 'review_findings': findings,
        'confirmation_diagnostics': [d for d in diagnostics if d.get('action') == 'needs_confirmation'],
        'unsupported_diagnostics': [d for d in diagnostics if d.get('action') == 'code_gap' and d.get('stage') != 'internal'],
        'question_sha256': sha256(png).hexdigest(), 'sent_image_sha256': ledger_images(output / 'workflow'),
        'elapsed_seconds': round(perf_counter() - started, 3), 'figure_attempts': attempts,
    }
    if original_png is not None:
        result['stored_original_sha256'] = sha256(original_png).hexdigest()
    if binding:
        from . import reviewed_figures

        result['figure_reading'] = binding
        result['figure_binding'] = reviewed_figures.install(output, result)
        if not result['figure_binding']:
            raise ValueError('figure.missing_binding')
    save(output / 'result.json', result)
    return result
