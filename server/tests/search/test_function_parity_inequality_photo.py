"""FP-T4 original-photo provenance and deterministic course integration regression."""
import json
import re
import subprocess
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
import sympy as sp
from PIL import Image

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.graph_lesson.stage_three.storage import storage_context
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.search.lesson import present_lesson, stage_one_result
from shuxueshuo_server.search.question_image import expected_image_hashes
from shuxueshuo_server.search.stage_one import run_question_image
from tests.search.function_equality_recording import RecordedWorkflowProvider, forbidden, read
from tests.search.support import session_for
from tools.export_graph_walk_course import export_course

ROOT = Path(__file__).resolve().parents[3]
RECORDINGS = Path(__file__).parent / 'fixtures/function-parity-inequality'
# Mathematical gold is checked after extraction; it is never a model input.
GOLD = {
    'a02': [('set', 'Interval(-3, 3)', None)],
    'a05': [('formula', '-x**2+2*x', 'Interval.open(-2, 0)'),
            ('set', 'Interval.open(-1, Rational(1, 2))', None)],
    'a11': [('formula', '-x**2+x', 'Interval.open(-oo, 0)'),
            ('set', 'Interval.open(2, oo)', None)],
    'a18': [('set', 'Interval(1, Rational(3, 2))', None)],
    'a19': [('set', 'Union(Interval.open(-1, 0), Interval.open(1, 3))', None)],
    'a20': [('set', 'Interval(-1, Rational(1, 3))', None)],
}
FINAL_ATTEMPTS = {'a02': 'final', 'a05': 'fixed', 'a11': 'recheck',
                  'a18': 'final', 'a19': 'initial', 'a20': 'initial'}


def recording_for(key):
    return RECORDINGS / FINAL_ATTEMPTS[key] / key


def initial_candidate(key):
    return read(RECORDINGS / 'initial' / key / 'result.json')['candidate']


@pytest.mark.parametrize('key', ['a02', 'a05', 'a11', 'a18'])
def test_initial_live_failures_are_solved_without_rewriting_model_output(key):
    from shuxueshuo_server.graph_lesson import parity_extension_math as ext, parity_inequality_math as ineq
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    from shuxueshuo_server.problem_understanding.review_contract import pointer
    candidate = initial_candidate(key)
    for i, goal in enumerate(candidate['root']['goals']):
        extension = goal['kind'] == 'find_function_formula'
        context = build_context(candidate, f'/root/goals/{i}')
        desc = context['parity_extension_goal' if extension else 'parity_inequality_goal']
        assert desc['structure_supported'], desc['reason']
        assert desc['source'] == goal
        math = ext if extension else ineq
        model = math.solve(desc)
        assert math.verify(desc, model)
        if extension:
            assert model['expression'] == sp.sympify(GOLD[key][i][1], locals={'x': sp.Symbol(desc['variable'], real=True)})
        else:
            assert model['solution'] == sp.sympify(GOLD[key][i][1])
            assert pointer(candidate, desc['relation_source_ref'])
        rules = desc if extension else desc.get('extension', desc.get('direction_source', {}).get('extension'))
        if rules:
            assert all(pointer(candidate, row['source_ref']) for row in ext.rule_rows(rules))


def test_fact_based_rule_and_target_are_not_tied_to_function_or_variable_names():
    from shuxueshuo_server.graph_lesson.parity_inequality_math import solve, verify
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context

    def rename(value):
        if isinstance(value, dict):
            return {k: rename(v) for k, v in value.items()}
        if isinstance(value, list):
            return [rename(v) for v in value]
        return (re.sub(r'\bf\b', 'h', re.sub(r'(?<![A-Za-z_])x(?![A-Za-z_])', 't', value))
                if isinstance(value, str) else value)

    desc = build_context(rename(initial_candidate('a02')), '/root/goals/0')['parity_inequality_goal']
    assert desc['structure_supported'], desc['reason']
    assert solve(desc)['solution'] == sp.Interval(-3, 3) and verify(desc, solve(desc))


@pytest.mark.parametrize('target', [0, 1])
@pytest.mark.parametrize('extra', ['且 $x<0$。', '且 $f(x)>0$。'])
def test_bare_sibling_target_never_owns_an_extra_condition(target, extra):
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    candidate = initial_candidate('a05')
    candidate['original_text'] += extra
    candidate['root']['facts'].append(extra.split('$')[1])
    context = build_context(candidate, f'/root/goals/{target}')
    desc = context['parity_extension_goal' if target == 0 else 'parity_inequality_goal']
    # The formula subtask must reject an unconsumed extra condition. A scalar
    # restriction on the asked range is instead consumed and intersected.
    if target == 1 and extra == '且 $x<0$。':
        from shuxueshuo_server.graph_lesson.parity_inequality_math import solve
        assert desc['structure_supported'], desc['reason']
        assert solve(desc)['solution'] == sp.Interval.open(-1, 0)
    else:
        assert not desc['structure_supported']


@pytest.mark.parametrize('replacement', [
    '∀x_1,x_2∈[-2,2]: (f(x_1)-f(x_2))/(x_1-x_2)<0',
    '∃x_1,x_2∈[-2,2], x_1≠x_2: (f(x_1)-f(x_2))/(x_1-x_2)<0',
    '∀x_1,x_2∈[-2,2], x_1≠x_2: (f(x_1)-f(x_2))/(x_1-x_2)<=0',
])
def test_direction_inference_requires_strict_universal_distinct_inputs(replacement):
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    candidate = initial_candidate('a18')
    candidate['root']['facts'][2] = replacement
    desc = build_context(candidate, '/root/goals/0').get('parity_inequality_goal', {})
    assert not desc.get('structure_supported')


def test_real_scalar_declaration_binds_to_printed_real_variable():
    from shuxueshuo_server.graph_lesson.parity_inequality_math import solve, verify
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    candidate = read(RECORDINGS / 'fixed/a18/result.json')['candidate']
    desc = build_context(candidate, '/root/goals/0')['parity_inequality_goal']
    assert desc['structure_supported'], desc['reason']
    assert solve(desc)['solution'] == sp.Interval(1, sp.Rational(3, 2)) and verify(desc, solve(desc))
    candidate['root']['facts'][-1] = 'a∈ℤ'
    # Integer domains are outside the notation contract and must not be
    # silently widened to the real declaration accepted above.
    with pytest.raises(ValueError, match='context.invalid_candidate'):
        build_context(candidate, '/root/goals/0')


@pytest.mark.parametrize('identity,accepted', [('f(-x)=-f(x)', True), ('f(-x)=f(x)', False),
                                             ('g(-x)=-g(x)', False), ('f(-x)=-f(x)+1', False)])
def test_only_an_exact_restatement_of_parity_is_redundant(identity, accepted):
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    candidate = initial_candidate('a11')
    candidate['root']['goals'][0]['additional_relations'] = [identity]
    desc = build_context(candidate, '/root/goals/0')['parity_extension_goal']
    assert desc['structure_supported'] is accepted, desc['reason']


@pytest.mark.parametrize('printed,accepted', [('x_1', True), ('x_{1}', True), ('x_3', False)])
def test_quantified_input_subscript_spelling_keeps_the_same_input(printed, accepted):
    from shuxueshuo_server.graph_lesson.parity_inequality_math import solve, verify
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    candidate = read(RECORDINGS / 'recheck/a18/result.json')['candidate']
    candidate['original_text'] = candidate['original_text'].replace('x_1', printed)
    desc = build_context(candidate, '/root/goals/0')['parity_inequality_goal']
    assert desc['structure_supported'] is accepted, desc['reason']
    if accepted:
        assert solve(desc)['solution'] == sp.Interval(1, sp.Rational(3, 2)) and verify(desc, solve(desc))


@pytest.mark.parametrize('attempt,key', [('fixed', 'a02'), ('fixed', 'a11'), ('recheck', 'a02')])
def test_exhausted_review_attempt_is_retained_and_never_published(attempt, key):
    recording = RECORDINGS / attempt / key
    result, api = read(recording / 'result.json'), read(recording / 'api-final.json')
    assert result['status'] == 'workflow.budget_exhausted' and not result['source_reviewed']
    assert api['recognition_status'] == 'failed' and api['lesson_status'] == 'not_started'
    assert not (recording / 'snapshot.json').exists()


def assert_answers(key, goals):
    assert set(goals) == {f'/root/goals/{i}' for i in range(len(GOLD[key]))}
    x = sp.Symbol('x', real=True)
    for i, (kind, expression, requested) in enumerate(GOLD[key]):
        goal = goals[f'/root/goals/{i}']
        assert goal['status'] == 'solved'
        answer = goal['answer']
        if kind == 'set':
            assert sp.sympify(answer['set']['expression']) == sp.sympify(expression)
        else:
            assert answer['kind'] == 'find_function_formula' and answer['status'] == 'determined_on_domain'
            assert sp.simplify(sp.sympify(answer['expression']['expression'], locals={'x': x})
                               - sp.sympify(expression, locals={'x': x})) == 0
            assert (answer.get('requested_domain') or {}).get('expression') == requested


def test_source_photos_and_all_real_attempts_are_immutable():
    attempts = sorted(RECORDINGS.glob('*/summary.json'))
    assert attempts
    recorded = set()
    for summary_file in attempts:
        directory = summary_file.parent
        for upload in read(directory / 'uploads.json'):
            assert sha256((ROOT / upload['source']).read_bytes()).hexdigest() == upload['source_sha256']
            for name, digest in {upload['file']: upload['sha256'], **upload['artifacts']}.items():
                assert sha256((directory / name).read_bytes()).hexdigest() == digest
            assert len(upload['artifacts']) == 2
        for row in read(summary_file)['cases']:
            key = row['case']
            recording = directory / key
            manifest, source = read(recording / 'recording.json'), read(recording / 'source.json')
            for name, digest in manifest['files'].items():
                assert sha256((recording / name).read_bytes()).hexdigest() == digest
            assert sha256((ROOT / source['source']).read_bytes()).hexdigest() == source['source_sha256']
            raw = BytesIO()
            with Image.open(ROOT / source['source']) as image:
                image.crop(source['crop_pixels']).save(raw, format='PNG')
            assert raw.getvalue() == (recording / 'original.png').read_bytes()
            ledger = read(recording / 'workflow/ledger.json')
            assert ledger['calls'][0]['stage'] == 'extract'
            assert len(ledger['calls']) == manifest['historical_semantic_calls']
            assert sum(c['network_attempts'] for c in ledger['calls']) == manifest['historical_network_attempts']
            for call in ledger['calls']:
                name = 'workflow/' + call['response_file']
                response = read(recording / name)
                assert response['metadata']['provider'] == 'deepseek'
                assert response['raw_payload']['usage']['total_tokens'] > 0
                assert sha256(response['text'].encode()).hexdigest() == manifest['response_text_sha256'][name]
            if recording == recording_for(key):
                recorded.add(key)
                api = manifest['api_acceptance']
                assert api['source_located'] and api['interactions_ready']
                assert api['recognition_status'] == 'reviewed' and api['execution_status'] == 'completed'
                assert api['same_stream_on_reopen'] and api['same_snapshot_on_reopen']
                assert_answers(key, read(recording / 'snapshot.json')['goals'])
    assert recorded == set(GOLD)


def replay(recording, output):
    historical = read(recording / 'result.json')
    ledger = read(recording / 'workflow/ledger.json')
    provider = RecordedWorkflowProvider(recording, ledger, expected_image_hashes(historical))
    result = run_question_image((recording / 'question.png').read_bytes(), output, provider,
                               problem_id=ledger['identity']['binding']['problem_id'],
                               original_png=(recording / 'original.png').read_bytes())
    assert provider.position == len(ledger['calls'])
    assert result['candidate'] == historical['candidate']
    assert result['source_reviewed'] and result['features_ok']
    return result


@pytest.fixture(scope='module')
def execution_db(tmp_path_factory):
    return session_for(tmp_path_factory.mktemp('fp-t4-photo-regression')).repository.db


@pytest.mark.parametrize('key', GOLD)
@pytest.mark.stage_three_db
def test_real_transcription_executes_grades_and_resumes_all_goals(key, tmp_path, monkeypatch, execution_db):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    result = replay(recording_for(key), tmp_path / 'recognition')
    second = run_result(stage_one_result(result, key), tmp_path / 'stage-two', admission='student_upload',
                        provider=forbidden, unsupported_root=tmp_path / 'unsupported')
    shown = present_lesson(second, result['features'], result['candidate']['original_text'], candidate=result['candidate'])
    assert len(shown['goals']) == len(GOLD[key])
    assert all(g['d1']['rows'] and not g['d1'].get('diagnostics') for g in shown['goals'])
    output = tmp_path / 'stage-three'
    with storage_context(execution_db):
        executed = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
        assert executed['status'] == 'completed'
        assert_answers(key, {g['target_ref']: g for g in executed['goals']})
        snapshot = open_store(output).snapshot()
        assert snapshot['interaction_states']
        assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
        assert runner.resume_sample(output)['goals'] == executed['goals']
        assert open_store(output).snapshot()['handoffs'] == snapshot['handoffs']
    evidence = export_course(output, 'function-parity-' + key)
    (tmp_path / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False))
    staging = read(ROOT / 'internal/senior-high/authored-courses/function-parity-t4-staged-20261111/pending-topic.json')
    source = next(row['course_source'] for row in staging['pending'] if row['id'] == 'function-parity-' + key)
    assert (source.get('targetRefs') or [source['targetRef']]) == [g['target_ref'] for g in executed['goals']]
    (tmp_path / 'source.json').write_text(json.dumps(source, ensure_ascii=False))
    route = 'parity-extension' if GOLD[key][0][0] == 'formula' else 'parity-inequality'
    checked = subprocess.run(['node', str(ROOT / 'tools/tests/fixtures/parity-parameter-course-check.mjs'),
                              str(tmp_path / 'evidence.json'), str(tmp_path / 'source.json'), route],
                             capture_output=True, text=True, check=False)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert json.loads(checked.stdout)['targets'] == [g['target_ref'] for g in executed['goals']]
