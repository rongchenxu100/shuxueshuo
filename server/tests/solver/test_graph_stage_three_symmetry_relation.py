"""General symmetry -> recognition -> M5 -> interactive, verified export."""
import json
import subprocess

import pytest

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from tests.solver.test_graph_function_parity_recognition import recognize
from tests.solver.test_graph_symmetry_relation import (
    a10,
    candidate,
    compound_sum,
    two_axes,
)
from tools.export_graph_walk_course import export_course


def center():
    return candidate(['Dom(f)=ℝ', 'graph_symmetry(f,center,1,2)', 'f(0)=5'], 'f(2)',
                     text=r'已知函数 $f(x)$ 定义域为 $\mathbb R$，图像关于点 $(1,2)$ 中心对称，且 $f(0)=5$，求 $f(2)$ 的值。')


def center_pair():
    return candidate(['Dom(f)=ℝ', 'graph_symmetry(f,center,1,2)'], 'f(0)+f(2)',
                     text=r'已知函数 $f(x)$ 定义域为 $\mathbb R$，图像关于点 $(1,2)$ 中心对称，求 $f(0)+f(2)$ 的值。')


def known_values():
    return candidate(expression='2*f(1)+1',
                     text=r'已知函数 $f(x)$ 定义在 $\mathbb R$ 上，图像关于直线 $x=2$ 对称，且 $f(1)=3$，求 $2f(1)+1$ 的值。')


def local():
    return candidate(['Dom(f)=ℝ', '∀t∈(0,1): f(-t)=f(t)+1', 'f(-1/2)=3'], 'f(1/2)',
                     text=r'已知函数 $f(x)$ 定义域为 $\mathbb R$，对任意 $t\in(0,1)$，有 $f(-t)=f(t)+1$，且 $f(-1/2)=3$，求 $f(1/2)$ 的值。')


def unknown():
    value = candidate(expression='f(2)')
    value['original_text'] = value['original_text'].replace('求 $f(3)$', '求 $f(2)$')
    return value


def paired_axes():
    return two_axes(r'图像关于直线 $x=0$ 和 $x=3$ 对称')


def repeated_quantifiers():
    value = two_axes(r'对任意 $t\in\mathbb R$，有 $f(-t)=f(t)$；对任意 $t\in\mathbb R$，有 $f(6-t)=f(t)$')
    value['root']['facts'][1:3] = ['∀t∈ℝ: f(-t)=f(t)', '∀t∈ℝ: f(6-t)=f(t)']
    return value


def affine():
    return candidate(['Dom(f)=ℝ', '∀t∈ℝ: f(1-t/2)+f(3+t/2)=8', 'f(0)=5'], 'f(4)',
                     text=r'已知函数 $f(x)$ 定义域为 $\mathbb R$，对任意 $t\in\mathbb R$，有 $f(1-t/2)+f(3+t/2)=8$，且 $f(0)=5$，求 $f(4)$ 的值。')


def nominal_center():
    value = center()
    value['original_text'] = value['original_text'].replace('关于点 $(1,2)$ 中心对称', '的对称中心是 $(1,2)$')
    return value


@pytest.mark.parametrize('build,answer', [(candidate, '3'), (a10, '0'), (lambda: a10(True), '1'),
                                        (center, '-1'), (local, '2'), (unknown, None),
                                        (paired_axes, '7'), (repeated_quantifiers, '7'),
                                        (affine, '3'), (nominal_center, '-1'), (compound_sum, '11'),
                                        (known_values, '7'), (center_pair, '4')])
def test_general_symmetry_pipeline(build, answer, tmp_path):
    problem = build()
    _prepared, recognized = recognize(problem, tmp_path)
    g, = recognized['goals']
    assert g['primary'] == 'type-function-symmetry', g
    assert g['supported'] == ['type-function-symmetry']
    assert g['d1']['fragments'] and not g['d1']['diagnostics']
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    goal, = result['goals']
    assert goal['status'] == 'solved', goal
    if answer is None:
        assert goal['answer']['value'] is None and goal['answer']['status'] == 'insufficient_information'
    else:
        assert goal['answer']['value']['expression'] == answer
    snapshot = open_store(output).snapshot()
    assert snapshot['interaction_states']
    assert all(r['status'] == 'interactive' for r in snapshot['interaction_states']), snapshot['interaction_states']
    evidence = export_course(output, 'test-t5')
    assert evidence['lesson']['goals'][0]['walk']['bundle']['intro'][0]['id'] == 'D1'
    assert evidence['stream']['handoffs'][0]['answer'] == goal['answer']
    if build is compound_sum:
        rendered = json.dumps(evidence, ensure_ascii=False)
        assert json.dumps(r'\sum_{k=1}^{10}\left(f(k)+1\right)')[1:-1] in rendered
        assert json.dumps(r'\sum_{k=1}^{10}f(k)+1')[1:-1] not in rendered
    if build in (affine, compound_sum, known_values, center_pair):
        course_source = {'schemaVersion': 1, 'problemId': 't5-review', 'title': '对称关系 · 开发题',
                         'page': '/topics/function-parity/variant99/', 'topicHref': '/topics/function-parity/',
                         'targetRef': '/root/goals/0'}
        (tmp_path/'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False))
        (tmp_path/'source.json').write_text(json.dumps(course_source, ensure_ascii=False))
        rendered = subprocess.run(['node', str(ROOT/'tools/tests/fixtures/parity-parameter-course-check.mjs'),
                                   str(tmp_path/'evidence.json'), str(tmp_path/'source.json'), 'function-symmetry',
                                   *(['number-lines'] if build is not known_values else [])],
                                  capture_output=True, text=True, check=False)
        assert rendered.returncode == 0, rendered.stdout+rendered.stderr
    assert runner.resume_sample(output)['goals'][0]['answer'] == goal['answer']


@pytest.mark.parametrize('facts', [
    ['graph_symmetry(f,axis,2)', 'f(1)=3'],
    ['Dom(f)=ℝ', 'parity(f,odd)', 'graph_symmetry(f,axis,2)', 'graph_symmetry(f,axis,3)'],
    ['Dom(f)=ℝ', 'graph_symmetry(f,axis,a)', 'f(1)=3'],
])
def test_owned_but_unsupported_general_conditions_cannot_fall_back_to_t3(facts, tmp_path):
    _prepared, result = recognize(candidate(facts), tmp_path)
    goal, = result['goals']
    assert goal['primary'] is None and not goal['supported']


@pytest.mark.parametrize('fault', ['denominator', 'negated_quantifier', 'question', 'quoted_negation'])
def test_invalid_source_cannot_reach_a_solved_course(fault, tmp_path):
    if fault in ('denominator', 'negated_quantifier'):
        equation = 'f(2-t)=f(t)+t/t-1' if fault == 'denominator' else 'f(2-t)=f(t)'
        prefix = '并非' if fault == 'negated_quantifier' else ''
        problem = candidate(['Dom(f)=ℝ', '∀t∈ℝ: '+equation, 'f(0)=5'], 'f(2)',
                            text=r'已知函数 $f(x)$ 定义域为 $\mathbb R$，'+prefix+r'对任意 $t\in\mathbb R$，有 $'
                            +equation+r'$，且 $f(0)=5$，求 $f(2)$ 的值。')
    else:
        problem = candidate()
        old, new = ('对称，', '对称，对吗？') if fault == 'question' else ('$f(1)=3$', '“$f(1)=3$”，不成立')
        problem['original_text'] = problem['original_text'].replace(old, new)
    _prepared, result = recognize(problem, tmp_path)
    goal, = result['goals']
    assert goal['primary'] is None and not goal['supported']
    output = runner.run_sample(tmp_path/'stage-two/stage-two-result.json', tmp_path/'stage-three')
    assert all(g['status'] != 'solved' for g in output['goals'])
