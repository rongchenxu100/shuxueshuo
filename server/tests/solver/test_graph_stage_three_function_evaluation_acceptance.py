"""Five independent T4 lessons through source, driver, export and interactions."""

import json
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.search.identity import build_identity
from tests.solver.test_graph_stage_three_execution import constructed_upstream, store
from tools.export_graph_walk_course import export_course

FIXTURES = Path(__file__).parent / 'fixtures/function-evaluation'


@pytest.mark.parametrize('name,count', [('q28a', 2), ('q28b', 2), ('q28c', 2), ('q28d', 1), ('q29b', 2)])
def test_all_targets_complete_with_reading_and_interaction_evidence(tmp_path, name, count):
    candidate = json.loads((FIXTURES / f'{name}-candidate.json').read_text())
    mathematical = {key: candidate[key] for key in ('original_text', 'root')}
    identity = build_identity({
        'status': 'reviewed_candidate', 'source_reviewed': True,
        'output_contract': 'search-problem-extraction/v1',
        'public_candidate': candidate, 'candidate': mathematical,
        'reviewed_candidate_revision': revision(candidate),
    })
    assert identity['fingerprint'] and identity['statement']
    candidate.pop('public_content', None)
    source = constructed_upstream(tmp_path, candidate)
    output = tmp_path / 'run'
    result = runner.run_sample(source, output)
    assert result['status'] == 'completed', result
    assert len(result['goals']) == count
    assert all(goal['status'] == 'solved' for goal in result['goals']), result
    answers = [goal['answer'] for goal in result['goals']]
    if name in ('q28a', 'q28b', 'q29b'):
        expected = {'q28a': ['2', '1/3'], 'q28b': ['-1/4', '1'], 'q29b': ['3', '603/2']}[name]
        assert [answer['value']['expression'] for answer in answers] == expected
    if name in ('q28c', 'q28d'):
        x = sp.Symbol('x', real=True)
        expected = [3*x*x-6*x+2, x/(x+1)] if name == 'q28c' else [3/(x+2)**2-1]
        domains = [sp.S.Reals, sp.S.Reals-sp.FiniteSet(-1, 0)] if name == 'q28c' else [sp.S.Reals-sp.FiniteSet(-2)]
        for answer, expression, domain in zip(answers, expected, domains, strict=True):
            assert sp.cancel(sp.sympify(answer['expression']['expression'], locals={'x': x})-expression) == 0
            assert sp.sympify(answer['domain']['expression']) == domain
    if name == 'q29b':
        assert answers[0]['kind'] == 'check_constant' and answers[0]['is_constant'] is True
        assert answers[1]['kind'] == 'finite_sum'
    snapshot = store(output).snapshot()
    assert len(snapshot['handoffs']) == count
    assert all(row['available'] for row in snapshot['handoffs'])
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
    evidence = export_course(output, f'function-concepts-{name}')
    assert len(evidence['lesson']['goals']) == count
    for goal in evidence['lesson']['goals']:
        assert goal['d1']['rows'] and not goal['d1'].get('diagnostics'), goal['d1']
        assert goal['walk'] is not None
        assert goal['d1']['interaction'] == 'choice'
    (tmp_path / f'{name}.evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n')


@pytest.mark.parametrize(('candidate', 'expected'), [
    ({'original_text': r'已知函数 $f(x)=x^2$，定义域为 $[1,2]$，求 $f(1)+f(2)$。',
      'root': {'definitions': ['f(x)=x^2'], 'facts': ['Dom(f)=[1,2]'],
               'goals': [{'kind': 'finite_sum', 'terms': [{'expression': 'f(1)'}, {'expression': 'f(2)'}]}]}}, '5'),
    ({'original_text': r'已知函数 $f(x)=x$，求 $\sum_{n=2}^{1} f(n)$。',
      'root': {'definitions': ['f(x)=x'],
               'goals': [{'kind': 'finite_sum', 'terms': [{'expression': 'f(n)', 'index': 'n', 'lower': 2, 'upper': 1}]}]}}, '0'),
])
def test_domain_limited_and_empty_sums_complete_with_interactions(tmp_path, candidate, expected):
    source = constructed_upstream(tmp_path, candidate)
    output = tmp_path / 'run'
    result = runner.run_sample(source, output)
    assert result['status'] == 'completed', result
    assert result['goals'][0]['status'] == 'solved', result
    assert result['goals'][0]['answer']['value']['expression'] == expected
    snapshot = store(output).snapshot()
    assert snapshot['interaction_states'] and all(row['status'] == 'interactive'
                                                 for row in snapshot['interaction_states'])
    evidence = export_course(output, 'function-evaluation-boundary')
    assert evidence['lesson']['goals'][0]['walk'] is not None
