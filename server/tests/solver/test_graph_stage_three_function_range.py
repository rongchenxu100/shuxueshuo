"""R0 passes the real lesson driver, source reading and interactive export."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import runner
from tests.solver.test_graph_function_range import candidate
from tests.solver.test_graph_stage_three_execution import constructed_upstream, store
from tools.export_graph_walk_course import export_course


@pytest.mark.parametrize('expression,domain,expected', [
    ('x^2-2*x+2', '[0,3]', sp.Interval(1, 5)),
    ('x^2-2*x+3', '[0,3]', sp.Interval(2, 6)),
    ('-2*x+1', '(-1,2]', sp.Interval.Ropen(-3, 3)),
    ('5', '(0,1)', sp.FiniteSet(5)),
    ('x^2', '[-2,2)', sp.Interval(0, 4)),
    ('x^2', '[0,0]', sp.FiniteSet(0)),
    ('-3*(x-1)^2+7', '[-2,4)', sp.Interval(-20, 7)),
    ('-3*x+2', '(-∞,-1)', sp.Interval.open(5, sp.oo)),
    ('x^2', '[0,1+1/2]', sp.Interval(0, sp.Rational(9, 4))),
    ('(x-1)^2+2', '[2,3]', sp.Interval(3, 6)),
    ('sqrt(-x^2-6*x-5)', '(-∞,+∞)', sp.Interval(0, 2)),
    ('sqrt(x)-1', '(-∞,+∞)', sp.Interval(-1, sp.oo)),
    ('3-2*sqrt(1-x)', '(0,1]', sp.Interval.Lopen(1, 3)),
    ('0*sqrt(x-1)', '(1,3)', sp.FiniteSet(0)),
    ('sqrt(2-x^2)', '(-sqrt(2),sqrt(2))', sp.Interval.Lopen(0, sp.sqrt(2))),
    ('2-sqrt(x^2-2)', '[-2,2]', sp.Interval(2-sp.sqrt(2), 2)),
])
def test_range_lesson_completes_with_exact_image_and_graphs(tmp_path, expression, domain, expected):
    upstream = constructed_upstream(tmp_path, candidate(expression, domain))
    output = tmp_path / 'run'
    result = runner.run_sample(upstream, output)
    assert result['status'] == 'completed', result
    goal = result['goals'][0]
    assert goal['status'] == 'solved', result
    assert sp.sympify(goal['answer']['set']['expression']) == expected
    snapshot = store(output).snapshot()
    assert snapshot['interaction_states']
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
    evidence = export_course(output, 'function-concepts-range-q03')
    lesson = evidence['lesson']['goals'][0]
    assert lesson['d1']['rows'] and not lesson['d1'].get('diagnostics')
    assert lesson['walk'] is not None
