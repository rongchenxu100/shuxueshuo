"""Real FR-T1 photos: source pixels, recorded workflow and method admission.

These are development regressions, not unseen-photo claims. No model or
database is opened by these tests; recorded replies drive the real workflow.
"""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.problem_understanding.notation_function_formula import (
    canonical_function_formula,
    compile_function_formula,
)
from shuxueshuo_server.search.lesson import present_lesson, stage_one_result
from shuxueshuo_server.search.question_image import question_png
from tests.search.function_equality_recording import (
    RecordedWorkflowProvider,
    forbidden,
    replay_recording,
)

ROOT = Path(__file__).resolve().parents[3]
RECORDINGS = Path(__file__).parent/'fixtures/function-formula/photo-matrix-20261101'
SOURCES = ROOT/'internal/senior-high/source-images'
CASES = [
    row for batch in ('function-formula-photo-20261101', 'function-formula-photo-extra-20261101')
    for row in json.loads((SOURCES/batch/'manifest.json').read_text())['cases']
    if not row.get('original_photo_only')
]


def normalized(goal):
    return canonical_function_formula(compile_function_formula(goal, '/root'))


def expected_methods(name, goal_index):
    if name in {'w04', 'w11', 'b05', 'w02', 'w09'}:
        return {'method-function-substitution', 'method-function-matching'}
    if name == 'b05-v1':
        return {'method-function-substitution'}
    if name == 'b05-v3':
        return {'method-function-evaluation' if goal_index == 0 else 'method-function-matching'}
    if name in {'b04', 'w10', 'w01', 'w12', 'b04-v'}:
        return {'method-function-coefficients'}
    if name in {'b07', 'b07-v'}:
        return {'method-function-assignment'}
    return {'method-function-equation-system'}


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_photo_source_and_frozen_gold_bind_original_pixels(case):
    recording = RECORDINGS/case['id']
    meta = json.loads((recording/'recording.json').read_text())
    source = ROOT/meta['source']
    assert sha256(source.read_bytes()).hexdigest() == meta['source_manifest_sha256']
    photographed = next(row for row in json.loads(source.read_text())['cases'] if row['id'] == case['id'])
    assert meta['usage'] == 'development_regression_not_unseen_holdout'
    page = ROOT/case['page']['file']
    assert sha256(page.read_bytes()).hexdigest() == case['page']['sha256']
    gold = ROOT/case['gold']['file']
    assert sha256(gold.read_bytes()).hexdigest() == case['gold']['sha256']
    crop = photographed['crop']
    with Image.open(page) as original, Image.open(recording/'original.png') as saved:
        box = crop['xyxy']
        region = original.convert('RGB').crop(box)
        mask = Image.new('L', region.size, 0)
        ImageDraw.Draw(mask).polygon([(x-box[0], y-box[1]) for x, y in crop['source_polygon']], fill=255)
        expected = Image.composite(region, Image.new('RGB', region.size, 'white'), mask)
        if crop['rotate_ccw']:
            assert crop['rotate_ccw'] == 90
            expected = expected.transpose(Image.Transpose.ROTATE_90)
        assert saved.convert('RGB').tobytes() == expected.tobytes()
        assert question_png(saved) == (recording/'question.png').read_bytes()
    assert sha256((recording/'original.png').read_bytes()).hexdigest() == crop['sha256']


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_photo_workflow_keeps_original_goals_conditions_and_selectable_methods(case, tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    result = replay_recording(tmp_path/'replay', RECORDINGS/case['id'])
    candidate = result['candidate']
    root = candidate['root']
    assert not root.get('definitions') and not root.get('facts') and not root.get('children')
    assert [normalized(goal) for goal in root['goals']] == [normalized(goal) for goal in case['gold']['goals']]
    assert not any(label in candidate['original_text'] for label in ('解析：', '解法1：', '答案：'))
    stage_two = run_result(stage_one_result(result, 'photo-'+case['id']), tmp_path/'stage-two',
                           admission='student_upload', provider=forbidden)
    assert stage_two['status'] == 'completed', stage_two
    lesson = present_lesson(stage_two, result['features'], candidate['original_text'], candidate=candidate)
    assert len(lesson['goals']) == len(case['gold']['goals'])
    for index, goal in enumerate(lesson['goals']):
        assert goal['status'] == 'resolved' and not goal['d1'].get('diagnostics'), goal
        selected = evaluate_goal(candidate, goal['target_ref'], [], goal['primary'])
        assert {option['method'] for option in selected['d4']['options']} == expected_methods(case['id'], index)
        assert not selected['d3'].get('prerequisites')
        assert goal['walk']['bundle']['intro']


@pytest.mark.parametrize('name,status', [
    ('w01', 'workflow.oscillation'), ('w05', 'needs_confirmation'),
    ('w12', 'needs_confirmation'), ('w07', 'needs_confirmation'),
])
def test_rejected_photos_retain_diagnostics_and_never_become_reviewed(name, status, tmp_path, monkeypatch):
    from shuxueshuo_server.search.identity import IdentityUnavailable, build_identity
    from shuxueshuo_server.search.stage_one import run_question_image

    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    recording = RECORDINGS/'rejected'/name
    meta = json.loads((recording/'recording.json').read_text())
    for filename, expected in meta['files'].items():
        assert sha256((recording/filename).read_bytes()).hexdigest() == expected
    ledger = json.loads((recording/'workflow/ledger.json').read_text())
    png = (recording/'question.png').read_bytes()
    provider = RecordedWorkflowProvider(recording, ledger, sha256(png).hexdigest())
    result = run_question_image(png, tmp_path/'rejected', provider,
                                problem_id=ledger['identity']['binding']['problem_id'])
    assert result['status'] == meta['expected_status'] == status
    assert not result['source_reviewed'] and provider.position == len(ledger['calls'])
    with pytest.raises(IdentityUnavailable):
        build_identity(result)
    if name == 'w07':
        goal, = result['candidate']['root']['goals']
        assert goal['relation_domain'] == 'ℝ'
        assert '任意实数' in result['candidate']['original_text']
        assert result['confirmation_diagnostics']
        corrected = json.loads((ROOT/'internal/senior-high/authored-courses/function-formula-c-20261101/w07.json').read_text())
        assert corrected['candidate']['root']['goals'][0]['relation_domain'] == 'ℝ∖{0}'
        assert corrected['usage'] == 'development_source_checked_transcription_not_unseen_photo'


@pytest.mark.parametrize('name,before,after', [
    ('w01', 'f[f(x)]', 'g[f(x)]'),
    ('w01', 'f[f(x)]', 'f[f(x)+1]'),
    ('w03', '定义在 $R$ 上', '设实常数 $R$'),
    ('w03', '$R$', '$Q$'),
    ('b07', r'\forall', r'\exists'),
    ('b07', r'\mathbf{R}', r'\mathbf{Q}'),
    ('b07', r'x,y\in', r'x\in'),
    ('b06-v', r'(x\neq 0)', r'(x>0)'),
    ('b06-v', r'(x\neq 0)', ''),
    ('b06-v', '，则', r'，且 $f(0)=1$，则'),
])
def test_source_spelling_adapters_do_not_hide_changed_math_or_missing_conditions(name, before, after):
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    from shuxueshuo_server.graph_lesson.stage_two.formula_surface import formula_source_spans
    from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches

    candidate = json.loads((RECORDINGS/name/'result.json').read_text())['candidate']
    target = '/root/goals/0'
    desc = build_context(candidate, target)['formula_goal']

    def locate(value):
        return formula_source_spans(value, target, [(0, len(value['original_text']))],
                                    desc, _abstract_formula_matches)

    assert locate(candidate)
    changed = deepcopy(candidate)
    assert before in changed['original_text']
    changed['original_text'] = changed['original_text'].replace(before, after)
    assert locate(changed) is None
