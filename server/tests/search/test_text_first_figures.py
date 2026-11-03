"""Offline unit contracts for the incremental path, not live photo accuracy evidence."""

import json
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from PIL import Image

from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.search import reviewed_figures
from shuxueshuo_server.search.dev_api import _present
from shuxueshuo_server.search.figure_extraction import (
    MAX_IMAGE_BYTES,
    MAX_SIDE,
    MAX_TOTAL_BYTES,
    crop_figures,
)
from shuxueshuo_server.search.identity import (
    IdentityUnavailable,
    build_identity,
    candidate_schema,
    public_structure_errors,
)
from shuxueshuo_server.search.question_image import question_png
from shuxueshuo_server.search.stage_one import ledger_calls, run_question_image
from shuxueshuo_server.search.text_extraction import (
    TextExtractionContract,
    build_text_request,
    inventory_issues,
    text_schema,
)
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    MultimodalProviderError,
)
from tests.search.test_identity import CORPUS, public_candidate
from tests.search.test_public_extraction import CONFIRMED, Responses

RECORDING = Path(__file__).parent / 'fixtures/function-graph/b09-recorded-20261102'


def graph_inputs(recording=RECORDING):
    # Adapt an old reviewed fixture into two explicit unit responses; no new model claim.
    base = deepcopy(json.loads((recording / 'result.json').read_text())['public_candidate'])
    values, regions = [], []
    public = base['public_content']
    goal = base['root']['goals'][0]
    boxes = public.pop('figure_regions')
    for i, (option, box) in enumerate(zip(goal['options'], boxes, strict=True)):
        fid = f'figure-{i + 1}'
        values.append({'figure_id': fid, 'facts': option.pop('facts'), 'uncertainties': option.pop('uncertainties')})
        regions.append({'id': fid, 'role': 'option', **box})
    for box in public.pop('statement_figure_regions', []):
        fid = f'figure-{len(values) + 1}'
        source = goal['source_graph']
        values.append({'figure_id': fid, 'facts': source.pop('facts'), 'uncertainties': source.pop('uncertainties')})
        regions.append({'id': fid, 'role': 'statement', **box})
    public['figure'] = 'unrepresented'
    public['figure_detection'] = {'status': 'present', 'regions': regions}
    supplement = {'base_revision': revision(base), 'figures': values}
    png, original = [(recording / name).read_bytes() for name in ('question.png', 'original.png')]
    return png, original, base, supplement


def test_ordinary_question_keeps_single_image_and_original_call_count(tmp_path):
    base = public_candidate()
    base['public_content']['figure_detection'] = {'status': 'none', 'regions': []}
    original = (CORPUS / 'q01/source.png').read_bytes()
    with Image.open(BytesIO(original)) as picture:
        processed = question_png(picture)
    provider = Responses(base, CONFIRMED)
    result = run_question_image(processed, tmp_path, provider, problem_id='plain',
                                original_png=original, read_graph_details=True)
    assert result['status'] == 'reviewed_candidate' and result['features_ok']
    assert result['public_candidate'] == base and build_identity(result)
    assert len(provider.requests) == 2  # Original extraction + review, not two extraction calls.
    assert all([i.content for i in request.images] == [processed] for request in provider.requests)
    assert result['sent_image_sha256'] == [sha256(processed).hexdigest()]
    assert not result['figure_attempts'] and not (tmp_path / 'workflow-figures').exists()
    assert (tmp_path / 'original.png').read_bytes() == original


def test_shared_prompt_is_small_and_graph_facts_are_not_requested_with_text(tmp_path):
    processed, _, _, _ = graph_inputs()
    request = build_text_request(processed, ExtractionArtifactStore(tmp_path))
    payload = json.loads(request.prompt.user_prefix)
    graph = text_schema()['$defs']['FunctionGraphGoal']['oneOf'][0]['properties']
    assert 'facts' not in graph['options']['items']['properties']
    assert 'facts' not in graph['source_graph']['properties']
    assert all(word not in request.prompt.system for word in ('### G1', '### G2', '### G4', '第 2 张 original'))
    piecewise = next(x for x in payload['math_expression_catalog']['expressions']
                     if x['id'] == 'piecewise_function_definition')
    assert piecewise['meaning'] == '按原题顺序记录每段的解析式及适用条件，保留开闭边界，不补默认分段。'
    assert 'match_range' not in piecewise['meaning']


@pytest.mark.parametrize('fixture,recording_name', [
    ('schematic-comparison-misclassified.json', 'b09-v3-reviewed-recorded-20261102'),
    ('formula-graph-comparison-misclassified.json', 'b09-recorded-20261102'),
])
def test_schematic_comparison_is_repaired_and_reviewed_before_reading_figures(tmp_path, fixture, recording_name):
    from shuxueshuo_server.search.lesson import present_lesson, run_stage_two

    png, original, _, _ = graph_inputs(RECORDING.parent / recording_name)
    recorded = json.loads((RECORDING.parent / fixture).read_text())
    mistaken = recorded['text_candidate']
    corrected = deepcopy(mistaken)
    corrected['root']['goals'][0]['comparison'] = 'rough_shape'
    # Authored correction + offline review responses, not new photo accuracy evidence.
    supplement = {'base_revision': revision(corrected), 'figures': recorded['figures']}
    contract = TextExtractionContract()
    parsed = contract.parse(json.dumps(mistaken))
    diagnoses = contract.diagnose(parsed, mistaken)
    assert not parsed['contract_valid']
    assert [(d['path'], d['action']) for d in diagnoses] == [('/root/goals/0/comparison', 'repair')]
    # The repair only authorizes this classification, not expressions, regions or facts.
    changed = deepcopy(corrected)
    changed['root']['goals'][0]['expression'] = 'f(2+x)'
    assert contract.repair_diagnostics(mistaken, changed, diagnoses)
    provider = Responses(mistaken, corrected, CONFIRMED, supplement, CONFIRMED)
    result = run_question_image(png, tmp_path, provider, problem_id='schematic-comparison', original_png=original)
    assert result['status'] == 'reviewed_candidate' and result['features_ok']
    assert build_identity(result) and result['figure_binding']['option_figures']
    assert len(provider.requests) == 5
    count = len(supplement['figures'])
    assert [len(r.images) for r in provider.requests] == [1, 1, 1, count, count]
    assert json.loads(provider.requests[2].prompt.user_prefix)['candidate'] == corrected
    assert result['public_candidate']['original_text'] == mistaken['original_text']
    assert result['public_candidate']['public_content']['scopes'] == mistaken['public_content']['scopes']
    assert result['public_candidate']['root'].get('definitions') == mistaken['root'].get('definitions')
    assert mistaken['root']['goals'][0]['comparison'] == 'exact_equivalence'
    stage_two = run_stage_two(tmp_path, result, provider=lambda *a, **k: pytest.fail('unexpected model call'),
                              unsupported_root=tmp_path / 'unsupported')
    assert stage_two['status'] == 'completed'
    assert stage_two['goals'][0]['d1']['fragments'] and not stage_two['goals'][0]['d1']['diagnostics']
    lesson = present_lesson(stage_two, result['features'], corrected['original_text'], candidate=result['candidate'])
    assert lesson['goals'][0]['walk']
    if corrected['root'].get('definitions'):
        from shuxueshuo_server.graph_lesson.stage_three.context import build_context
        from shuxueshuo_server.graph_lesson.stage_three.graph_transform_runtime import admitted
        from shuxueshuo_server.graph_lesson.function_graph import solve, verify

        context = build_context(result['candidate'], '/root/goals/0')
        assert admitted(context)
        solution = solve(context['graph_goal'])
        assert verify(context['graph_goal'], solution) and solution['correct_option_id'] == 'a'


@pytest.mark.parametrize('recording_name', ['b09-recorded-20261102', 'b09-v3-reviewed-recorded-20261102'])
def test_figures_only_are_read_and_reviewed_without_reextracting_text(tmp_path, recording_name):
    png, original, base, supplement = graph_inputs(RECORDING.parent / recording_name)
    provider = Responses(base, CONFIRMED, supplement, CONFIRMED)
    result = run_question_image(png, tmp_path, provider, problem_id='figures', original_png=original,
                                read_graph_details=True)
    assert result['status'] == 'reviewed_candidate' and result['features_ok'], result
    assert build_identity(result) and result['figure_binding']['option_figures']
    extraction, review = provider.requests[2:]
    assert review.prompt.system != extraction.prompt.system
    assert review.images == extraction.images
    assert json.loads(review.prompt.user_prefix)['candidate'] == supplement
    assert set(review.contract_schema['properties']) == {'status', 'findings'}
    merged = result['public_candidate']
    assert 'figure_detection' not in merged['public_content']
    assert inventory_issues(merged) == []
    # Older represented records may still carry the text inventory; it is no longer pending.
    legacy = deepcopy(merged)
    legacy['public_content']['figure_detection'] = base['public_content']['figure_detection']
    assert inventory_issues(legacy) == []
    assert merged['original_text'] == base['original_text']
    assert merged['public_content']['scopes'] == base['public_content']['scopes']
    text_root = deepcopy(merged['root'])
    for option in text_root['goals'][0]['options']:
        del option['facts'], option['uncertainties']
    if 'source_graph' in text_root['goals'][0]:
        source = text_root['goals'][0]['source_graph']
        del source['facts'], source['uncertainties']
        assert result['figure_binding']['statement_figures']
    assert text_root == base['root']
    assert len(provider.requests) == 4
    for request in provider.requests[:2]:
        assert [i.content for i in request.images] == [png]
    for request in provider.requests[2:]:
        assert len(request.images) == len(supplement['figures'])
        assert all(i.content not in (png, original) for i in request.images)
        assert max(max(i.width, i.height) for i in request.images) <= MAX_SIDE
        assert sum(len(i.content) for i in request.images) <= MAX_TOTAL_BYTES
        payload = json.loads(request.prompt.user_prefix)
        assert 'math_expression_catalog' not in payload
        assert payload['base_revision'] == revision(base)
    assert result['figure_attempts'] == [{'workflow_directory': 'workflow-figures',
        'status': 'reviewed_candidate', 'content_calls': 1, 'review_calls': 1}]
    assert len(ledger_calls(tmp_path / 'workflow')) == 4
    # A merged text mutation or a different source crop cannot be published as reviewed.
    changed = deepcopy(result)
    changed['public_candidate']['original_text'] += '改写'
    changed['reviewed_candidate_revision'] = revision(changed['public_candidate'])
    with pytest.raises(ValueError, match='merge_mismatch'):
        reviewed_figures.install(tmp_path, changed)
    changed = deepcopy(result)
    changed['figure_reading']['image_inputs']['views'][0]['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='crop_image_mismatch'):
        reviewed_figures.install(tmp_path, changed)


@pytest.mark.parametrize('nested', [False, True], ids=['same-scope', 'separate-subquestions'])
def test_mixed_graph_and_range_goals_keep_text_goal_and_bind_only_graph(tmp_path, nested):
    png, original, base, supplement = graph_inputs()
    public = base['public_content']
    graph_goal = base['root']['goals'][0]
    range_goal = {'kind': 'find_range', 'object': 'f'}
    graph_choice = public['scopes'][0]['choices'][0]
    range_choice = {'status': 'none', 'selection_mode': 'none', 'options': []}
    base['root']['definitions'] = ['f(x)=abs(x-1)+1']
    base['original_text'] = '已知函数 f(x)=|x-1|+1，求值域，并选择大致图像。'
    if nested:
        base['root']['goals'] = []
        base['root']['children'] = [{'label': '(1)', 'goals': [range_goal]},
                                    {'label': '(2)', 'goals': [graph_goal]}]
        range_ref, graph_ref = '/root/children/0/goals/0', '/root/children/1/goals/0'
        public['scopes'] = [
            {'scope_ref': '/root', 'statement': '已知函数 $f(x)=|x-1|+1$。', 'choices': []},
            {'scope_ref': '/root/children/0', 'statement': '求函数的值域。', 'choices': [range_choice]},
            {'scope_ref': '/root/children/1', 'statement': '选择函数的大致图像。', 'choices': [graph_choice]},
        ]
    else:
        base['root']['goals'] = [range_goal, graph_goal]
        range_ref, graph_ref = '/root/goals/0', '/root/goals/1'
        public['scopes'][0].update(statement='已知函数 $f(x)=|x-1|+1$，求值域并选择大致图像。',
                                   choices=[range_choice, graph_choice])
    range_choice['target_ref'], graph_choice['target_ref'] = range_ref, graph_ref
    for region in public['figure_detection']['regions']:
        region['target_ref'] = graph_ref
    supplement['base_revision'] = revision(base)
    frozen = deepcopy(base)
    provider = Responses(base, CONFIRMED, supplement, CONFIRMED)
    result = run_question_image(png, tmp_path, provider, problem_id='mixed-goals', original_png=original)
    assert result['status'] == 'reviewed_candidate', result['confirmation_diagnostics']
    assert build_identity(result)
    merged = result['public_candidate']
    assert merged['original_text'] == base['original_text']
    assert merged['public_content']['scopes'] == public['scopes']
    range_scope = merged['root']['children'][0] if nested else merged['root']
    assert range_scope['goals'][0] == range_goal
    assert {r['target_ref'] for r in result['figure_binding']['option_figures']} == {graph_ref}
    assert 'figure_detection' not in merged['public_content']
    assert base == frozen and len(provider.requests) == 4
    # Non-graph questions do not mask unsupported graph facts or wrong/missing graph crops.
    for defect in ('unsupported', 'missing', 'wrong-target', 'no-graph'):
        bad = deepcopy(merged)
        graph_scope = bad['root']['children'][1] if nested else bad['root']
        goal = graph_scope['goals'][-1]
        if defect == 'unsupported':
            goal['options'][0]['facts']['vertex']['evidence'] = 'estimated'
        elif defect == 'missing':
            bad['public_content']['figure_regions'].pop()
        elif defect == 'wrong-target':
            bad['public_content']['figure_regions'][0]['target_ref'] = range_ref
        else:
            goal.clear()
            goal.update(range_goal)
        assert public_structure_errors(bad), defect
    for status in ('incomplete', 'unknown'):
        bad = deepcopy(result)
        scopes = bad['public_candidate']['public_content']['scopes']
        scope = scopes[-1] if nested else scopes[0]
        scope['choices'][-1]['status'] = status
        bad['reviewed_candidate_revision'] = revision(bad['public_candidate'])
        assert reviewed_figures.install(tmp_path, bad) is None


def test_represented_requires_a_graph_goal_even_with_no_regions():
    candidate = public_candidate()
    candidate['public_content']['figure'] = 'represented'
    candidate['public_content']['figure_regions'] = []
    assert any(path == '/public_content/figure' for path, _ in public_structure_errors(candidate))


@pytest.mark.parametrize('missing', ['option_id', 'label'])
def test_option_inventory_requires_identity_in_text_schema(missing):
    _, _, base, _ = graph_inputs()
    assert Draft202012Validator(text_schema()).is_valid(base)
    del base['public_content']['figure_detection']['regions'][0][missing]
    assert not Draft202012Validator(text_schema()).is_valid(base)
    # The shared public contract applies the same requirement, independently of text-only math.
    public_schema = candidate_schema()['properties']['public_content']
    assert not Draft202012Validator(public_schema).is_valid(base['public_content'])


@pytest.mark.parametrize('role', ['statement', 'workspace'])
def test_non_option_inventory_does_not_accept_option_identity(role):
    _, _, base, _ = graph_inputs()
    region = base['public_content']['figure_detection']['regions'][0]
    region['role'] = role
    assert not Draft202012Validator(text_schema()).is_valid(base)
    del region['option_id'], region['label']
    assert Draft202012Validator(text_schema()).is_valid(base)


def test_unclear_graph_uses_bounded_original_crops_once_and_keeps_text(tmp_path):
    png, original, base, supplement = graph_inputs()
    unclear = deepcopy(supplement)
    unclear['figures'][0].update(facts=None, uncertainties=['空心点看不清'])
    provider = Responses(base, CONFIRMED, unclear, supplement, CONFIRMED)
    result = run_question_image(png, tmp_path, provider, problem_id='retry', original_png=original,
                                read_graph_details=True)
    assert result['status'] == 'reviewed_candidate', result
    assert len(provider.requests) == 5 and len(result['figure_attempts']) == 2
    assert result['figure_reading']['workflow_directory'] == 'workflow-figures-original'
    assert result['public_candidate']['original_text'] == base['original_text']
    for request in provider.requests[3:]:
        assert all(i.content != original for i in request.images)
        assert all(max(i.width, i.height) <= MAX_SIDE and len(i.content) <= MAX_IMAGE_BYTES for i in request.images)
        assert all(v['source_kind'] == 'original' for v in json.loads(request.prompt.user_prefix)['image_inputs']['views'])
    failed = json.loads((tmp_path / 'workflow-figures/workflow-result.json').read_text())
    assert failed['candidate'] == unclear and failed['status'] == 'needs_confirmation'


@pytest.mark.parametrize('recovers', [True, False])
def test_estimated_coordinate_with_empty_uncertainties_retries_original_once(tmp_path, recovers):
    png, original, base, supplement = graph_inputs(RECORDING.parent / 'b09-v3-reviewed-recorded-20261102')
    unclear = deepcopy(supplement)
    unclear['figures'][1]['facts']['x_intercept'] = {'x': '约 -2', 'evidence': 'estimated'}
    assert not unclear['figures'][1]['uncertainties']
    replies = [base, CONFIRMED, unclear, supplement, CONFIRMED] if recovers else [base, CONFIRMED, unclear, unclear]
    provider = Responses(*replies)
    result = run_question_image(png, tmp_path, provider, problem_id='estimated', original_png=original,
                                read_graph_details=True)
    assert len(result['figure_attempts']) == 2 and len(provider.requests) == len(replies)
    failed = json.loads((tmp_path / 'workflow-figures/workflow-result.json').read_text())
    assert failed['status'] == 'needs_confirmation' and not failed['source_reviewed']
    assert failed['review_calls'] == 0 and failed['candidate'] == unclear
    assert failed['diagnostics'][0]['path'] == '/figures/1/facts/x_intercept/evidence'
    if recovers:
        assert result['status'] == 'reviewed_candidate' and build_identity(result)
        assert result['figure_reading']['workflow_directory'] == 'workflow-figures-original'
    else:
        assert result['status'] == 'needs_confirmation' and not result.get('figure_binding')
        with pytest.raises(IdentityUnavailable):
            build_identity(result)


def test_still_unclear_after_original_crops_does_not_loop_or_publish(tmp_path):
    png, original, base, supplement = graph_inputs()
    supplement['figures'][0].update(facts=None, uncertainties=['图被遮挡'])
    provider = Responses(base, CONFIRMED, supplement, supplement)
    result = run_question_image(png, tmp_path, provider, problem_id='unclear', original_png=original,
                                read_graph_details=True)
    assert result['status'] == 'needs_confirmation' and not result['source_reviewed']
    assert result['public_candidate'] == base and len(provider.requests) == 4
    assert len(result['figure_attempts']) == 2 and not result.get('figure_binding')
    with pytest.raises(IdentityUnavailable):
        build_identity(result)


@pytest.mark.parametrize('mutation', ['rewrite_text', 'swap_id', 'stale_base'])
def test_figure_response_cannot_rewrite_text_or_change_bindings(tmp_path, mutation):
    png, original, base, supplement = graph_inputs()
    if mutation == 'rewrite_text':
        supplement['original_text'] = '重写题干'
    elif mutation == 'swap_id':
        supplement['figures'][0]['figure_id'] = 'figure-2'
    else:
        supplement['base_revision'] = '0' * 64
    provider = Responses(base, CONFIRMED, supplement)
    result = run_question_image(png, tmp_path, provider, problem_id='bad-binding', original_png=original,
                                read_graph_details=True)
    assert result['status'] == 'workflow.budget_exhausted' and result['public_candidate'] == base
    assert _present(result)['outcome'] == 'error'
    assert not result['source_reviewed'] and len(provider.requests) == 3
    assert not result.get('figure_binding')


def test_malformed_figure_review_is_a_system_failure_without_original_retry(tmp_path):
    png, original, base, supplement = graph_inputs()
    # 755a001ead7e returned this shape: the extraction prompt leaked an extra
    # base_revision into the review. Do not silently accept or strip the field.
    invalid_review = {'base_revision': revision(base), **CONFIRMED}
    provider = Responses(base, CONFIRMED, supplement, invalid_review, invalid_review)
    result = run_question_image(png, tmp_path, provider, problem_id='review-format',
                                original_png=original, read_graph_details=True)
    assert result['status'] == 'workflow.budget_exhausted'
    assert _present(result)['outcome'] == 'error'
    assert len(provider.requests) == 5 and len(result['figure_attempts']) == 1
    assert not result['source_reviewed'] and not result.get('figure_binding')
    assert result['public_candidate'] == base
    with pytest.raises(IdentityUnavailable):
        build_identity(result)


def test_figure_review_format_retry_reuses_same_candidate_and_crops(tmp_path):
    png, original, base, supplement = graph_inputs()
    invalid_review = {'base_revision': revision(base), **CONFIRMED}
    provider = Responses(base, CONFIRMED, supplement, invalid_review, CONFIRMED)
    result = run_question_image(png, tmp_path, provider, problem_id='review-format-retry',
                                original_png=original, read_graph_details=True)
    assert result['status'] == 'reviewed_candidate' and build_identity(result)
    assert len(provider.requests) == 5 and len(result['figure_attempts']) == 1
    first_review, retry = provider.requests[3:]
    first_payload, retry_payload = [json.loads(r.prompt.user_prefix) for r in (first_review, retry)]
    assert first_payload['candidate'] == retry_payload['candidate'] == supplement
    assert first_review.images == retry.images
    assert retry_payload['review_feedback'][0]['code'] == 'review.invalid_response'
    assert result['figure_attempts'][0]['content_calls'] == 1
    assert result['figure_attempts'][0]['review_calls'] == 2


@pytest.mark.parametrize('condition', ['missing', 'wrong_option', 'empty_box', 'absent_detection'])
def test_incomplete_inventory_cannot_pass_as_a_plain_question(tmp_path, condition):
    png, original, base, _ = graph_inputs()
    if condition == 'missing':
        base['public_content']['figure_detection'] = {'status': 'uncertain', 'regions': []}
    elif condition == 'wrong_option':
        base['public_content']['figure_detection']['regions'][0]['label'] = 'D'
    elif condition == 'empty_box':
        base['public_content']['figure_detection']['regions'][0]['box'] = [0, 0, 0, 1]
    else:
        base['public_content']['figure_detection'] = {'status': 'none', 'regions': []}
    provider = Responses(base)
    result = run_question_image(png, tmp_path, provider, problem_id='missing', original_png=original,
                                read_graph_details=True)
    assert result['status'] == 'needs_confirmation' and len(provider.requests) == 1
    assert not result['features_ok'] and not result.get('figure_binding')


def test_blank_drawing_area_does_not_trigger_graph_reading(tmp_path):
    base = public_candidate()
    base['public_content']['figure_detection'] = {'status': 'present', 'regions': [{
        'id': 'figure-1', 'role': 'workspace', 'target_ref': '/root/goals/0', 'box': [.1, .1, .9, .9]}]}
    provider = Responses(base, CONFIRMED)
    result = run_question_image((CORPUS / 'q01/source.png').read_bytes(), tmp_path, provider, problem_id='blank')
    assert result['status'] == 'reviewed_candidate' and len(provider.requests) == 2
    assert not result['figure_attempts']


def test_transport_cannot_drop_a_figure_crop(tmp_path):
    png, original, base, supplement = graph_inputs()
    class DroppedCrop(Responses):
        def prepare_request(self, request):
            if request.contract_version == 'search-figure-extraction/v1':
                request = replace(request, images=request.images[:-1])
            return super().prepare_request(request)
    provider = DroppedCrop(base, CONFIRMED, supplement, CONFIRMED)
    with pytest.raises(MultimodalProviderError, match='match evidence hashes and page order'):
        run_question_image(png, tmp_path, provider, problem_id='drop', original_png=original)
    assert not (tmp_path / 'result.json').exists() and not (tmp_path / 'question-figures.json').exists()


def test_ordinary_extraction_still_requires_complete_primary_image(tmp_path):
    png, _, _, _ = graph_inputs()
    request = build_text_request(png, ExtractionArtifactStore(tmp_path))
    images = tuple(replace(i, role='zoom') for i in request.images)
    request = replace(request, images=images)
    with pytest.raises(MultimodalProviderError, match='complete question image'):
        Responses().prepare_request(request)


def test_original_crops_obey_byte_budget_without_changing_box():
    _, _, base, _ = graph_inputs()
    base['public_content']['figure_detection']['regions'] = [dict(
        base['public_content']['figure_detection']['regions'][0], box=[0, 0, 1, 1])]
    noise = Image.effect_noise((1600, 1600), 100).convert('RGB')
    buffer = BytesIO()
    noise.save(buffer, format='PNG')
    view, content = crop_figures(buffer.getvalue(), base, source_kind='original')[0]
    assert view['box'] == [0, 0, 1, 1] and view['pixel_box'] == [0, 0, 1600, 1600]
    assert max(view['width'], view['height']) <= MAX_SIDE and len(content) <= MAX_IMAGE_BYTES
