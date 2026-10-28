"""Real failed photo IR through the shared solver and both interaction layers.

The recorded source was reviewed but unsupported. These are deterministic offline
regressions, not a replacement for a newly reviewed live photo-search run.
"""

import json
import subprocess
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
import sympy as sp
from fastapi import HTTPException
from PIL import Image, ImageChops

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.equality_runtime import verify_result
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.learning import graph_walk
from shuxueshuo_server.search.question_image import question_png
from tests.solver.test_graph_stage_three_execution import constructed_upstream, store
from tools.export_graph_walk_course import export_course

ROOT = Path(__file__).resolve().parents[3]
SOURCES = ROOT / 'internal/senior-high/source-images/function-equality-domain-first'
FIXTURE = Path(__file__).parent / 'fixtures/function-equality/domain-first-photo-public-candidate.json'
TARGET = '/root/goals/0'
PROBLEM_ID = 'function-equality-domain-first-test'


def test_archived_photo_is_the_actual_upload_crop_and_sent_image():
    manifest = json.loads((SOURCES / 'manifest.json').read_text())
    for name, metadata in manifest['files'].items():
        assert sha256((SOURCES / name).read_bytes()).hexdigest() == metadata['sha256']
    assert sha256(FIXTURE.read_bytes()).hexdigest() == manifest['candidate_sha256']
    with (Image.open(SOURCES / 'source-upload.png') as upload,
          Image.open(SOURCES / 'source-page.png') as page,
          Image.open(SOURCES / 'source-crop.png') as crop):
        assert ImageChops.difference(upload.rotate(270, expand=True), page).getbbox() is None
        assert ImageChops.difference(page.crop(manifest['crop']['xyxy']), crop).getbbox() is None
        assert question_png(crop) == (SOURCES / 'question.png').read_bytes()
    assert manifest['historical_result']['recognition_status'] == 'reviewed_candidate'
    assert manifest['historical_result']['target_status'] == 'unsupported'
    assert manifest['historical_result']['primary'] is None


@pytest.fixture(scope='module', params=['single', 'unspecified'])
def executed(tmp_path_factory, request):
    directory = tmp_path_factory.mktemp('domain-first-photo-offline')
    public = json.loads(FIXTURE.read_text())
    candidate = {key: deepcopy(public[key]) for key in ('original_text', 'root')}
    # Keep the real historical source intact. The second parameter probes the
    # newly admitted source mode without claiming it was that historical output.
    candidate['root']['goals'][0]['selection_mode'] = request.param
    source = constructed_upstream(directory, candidate)
    classified = json.loads(source.read_text())
    assert classified['goals'][0]['primary'] == 'type-function-equality', classified['goals'][0]
    output = directory / 'run'
    result = runner.run_sample(source, output)
    assert result['status'] == 'completed', result
    assert result['goals'][0]['status'] == 'solved', result['goals'][0]
    snapshot = store(output).snapshot()
    route = result['goals'][0]['routes'][0]['route_id']
    state = store(output).checkpoint(TARGET, route)['driver_state']
    comparison = decode_value(state['result'])['comparison_result']
    context = build_context(candidate, TARGET)
    assert verify_result(context, comparison)['status'] == 'verified'
    return directory, output, candidate, result, snapshot, state, comparison


def test_photo_four_verdicts_use_original_domains_then_correspondence(executed):
    _, _, candidate, result, snapshot, state, comparison = executed
    mode = candidate['root']['goals'][0]['selection_mode']
    assert comparison['selection_mode'] == mode
    assert comparison['correct_labels'] == ['C']
    rows = {row['label']: row['result'] for row in comparison['options']}
    assert {label: row['relation'] for label, row in rows.items()} == {
        'A': 'different', 'B': 'different', 'C': 'equal', 'D': 'different'}
    assert {label: row['reason'] for label, row in rows.items()} == {
        'A': 'outputs_differ', 'B': 'domains_differ',
        'C': 'same_domain_and_correspondence', 'D': 'domains_differ'}
    assert rows['A']['left']['domain'] == rows['A']['right']['domain'] == sp.Interval(-sp.oo, 0)
    witness = rows['A']['counterexample']
    point = witness['point']
    assert point < 0
    assert sp.simplify(witness['left_value'] - sp.sqrt(-2 * point**3)) == 0
    assert sp.simplify(witness['right_value'] - point * sp.sqrt(-2 * point)) == 0
    assert witness['left_value'] != witness['right_value']
    assert rows['B']['left']['domain'] == sp.S.Reals
    assert rows['B']['right']['domain'] == sp.Complement(sp.S.Reals, sp.FiniteSet(0))
    assert rows['B']['counterexample']['point'] == 0
    assert rows['C']['left']['domain'] == rows['C']['right']['domain'] == sp.S.Reals
    assert rows['D']['left']['domain'] == sp.Interval(1, sp.oo)
    assert rows['D']['right']['domain'] == sp.Union(sp.Interval(-sp.oo, -1), sp.Interval(1, sp.oo))
    assert rows['D']['counterexample']['point'] in rows['D']['right']['domain']
    assert rows['D']['counterexample']['point'] not in rows['D']['left']['domain']
    # Both nontrivial original domains must survive simplification/cancellation.
    borrowed = [call for step in state['trajectory']['steps'] for call in step['calls']
                if call['capability'] == 'submethod']
    assert len(borrowed) == 8
    assert all(call['public_ref'] == 'method-domain-intersection' for call in borrowed)
    correspondence = [step for step in snapshot['math_steps']
                      if step['display_unit'] == 'equality_correspondence']
    assert [step['option_context']['label'] for step in correspondence] == ['A', 'C']
    parts = [part for chunk in snapshot['interactions'] for part in chunk['parts']]
    verdicts = [part for part in parts if part['option_context']['phase'] == 'verdict']
    assert [part['option_context']['label'] for part in verdicts] == list('ABCD')
    assert all(part['interaction']['type'] == 'choice' for part in verdicts)
    assert [part['expected_answer']['one_of'] for part in verdicts] == [
        ['different'], ['different'], ['equal'], ['different']]
    assert all(part['option_context']['target_ref'] == TARGET for part in parts)
    assert len({part['option_context']['left_ref'] for part in verdicts}) == 4
    assert len({part['option_context']['right_ref'] for part in verdicts}) == 4
    handoff, = snapshot['handoffs']
    choice = handoff['original_choice']
    assert choice['kind'] == ('single_choice' if mode == 'single' else 'multiple_choice')
    assert choice['selection_mode'] == mode
    assert choice['correct_labels'] == ['C']
    assert len(choice['option_verdicts']) == 4
    assert result['goals'][0]['answer']['correct_labels'] == ['C']
    assert candidate['root']['goals'][0]['options'][2]['functions'][1]['definition'].startswith('g(t)=')


def test_photo_actual_export_replays_both_layers_and_server_enforces_all_evidence(executed):
    directory, output, _, _, snapshot, _, _ = executed
    assert runner.resume_sample(output)['goals'][0]['status'] == 'solved'
    assert store(output).snapshot()['handoffs'] == snapshot['handoffs']
    evidence = export_course(output, PROBLEM_ID)
    path = directory / 'evidence.json'
    path.write_text(json.dumps(evidence, ensure_ascii=False))
    result = subprocess.run(
        ['node', str(ROOT / 'tools/tests/graph-walk-domain-first-acceptance.mjs'), str(path)],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=45)
    assert result.returncode == 0, result.stderr or result.stdout
    native = json.loads(result.stdout)
    graph_walk.validate_contract(native, PROBLEM_ID)
    route, = native['routes']
    steps = native['routes'][route]['steps']
    final = steps[-1]
    mode = evidence['stream']['handoffs'][0]['original_choice']['selection_mode']
    if mode == 'single':
        assert final['interaction']['type'] == 'choice'
        assert final['expected_answer'] == {'one_of': ['C']}
        correct, wrong_answers, invalid_answers = 'C', list('ABD'), (['C'], ['C', 'D'], [], None, 'Z')
    else:
        assert mode == 'unspecified'
        assert final['interaction']['type'] == 'original_choice_exact_set'
        assert final['expected_answer'] == {'correct_labels': ['C'], 'option_labels': list('ABCD')}
        correct = ['C']
        wrong_answers, invalid_answers = ([], ['A'], ['C', 'D'], ['C', 'C'], ['Z']), ('C', None, 1)
    assert graph_walk.grade(final, {'value': correct}, route) == 'passed'
    for wrong in wrong_answers:
        assert graph_walk.grade(final, {'value': wrong}, route) == 'wrong'
    for invalid in invalid_answers:
        with pytest.raises(HTTPException) as error:
            graph_walk.grade(final, {'value': invalid}, route)
        assert error.value.status_code == 422
    all_evidence = [step['id'] for step in [*native['intro'], *steps[:-1]]]
    for omitted in all_evidence:
        with pytest.raises(HTTPException) as error:
            graph_walk.ensure_option_prerequisites(native, route, final,
                                                   [item for item in all_evidence if item != omitted])
        assert error.value.status_code == 409
    graph_walk.ensure_option_prerequisites(native, route, final, all_evidence)
