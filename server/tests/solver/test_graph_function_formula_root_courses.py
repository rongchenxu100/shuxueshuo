"""Source binding and range preservation for the last two FR-T1 courses."""

import json
from hashlib import sha256
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.function_formula import recover, verify
from shuxueshuo_server.graph_lesson.function_matching import recover_matching, verify_matching
from shuxueshuo_server.graph_lesson.stage_one.authored import prepare_authored
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
from shuxueshuo_server.graph_lesson.stage_two.contracts import validate_input

ROOT = Path(__file__).resolve().parents[3]
TARGET = '/root/goals/0'


@pytest.mark.parametrize('name,endpoint', [('w04', 1), ('w11', -2)])
def test_original_root_course_binds_source_and_preserves_both_method_ranges(name, endpoint):
    record = json.loads((ROOT/f'internal/senior-high/authored-courses/function-formula-roots-20261101/{name}.json').read_text())
    source = record['sources'][0]
    assert sha256((ROOT/source['reference']).read_bytes()).hexdigest() == source['sha256']
    candidate = record['candidate']
    prepared = prepare_authored(candidate, run_id='root-course-'+name, sources=record['sources'], reviewer=record['reviewer'])
    assert validate_input(prepared, admission='authored_topic')['ok']
    assert prepared['statuses']['source_reviewed'] is False  # authored input is not photo-model verification
    description = build_context(candidate, TARGET)['formula_goal']
    selection = evaluate_goal(candidate, TARGET, [], 'type-function-formula')
    assert {option['method'] for option in selection['d4']['options']} == {
        'method-function-matching', 'method-function-substitution',
    }
    assert not selection['d3'].get('prerequisites')
    for solve, check in [(recover, verify), (recover_matching, verify_matching)]:
        result = solve(description)
        t = result['variable']
        expected = sp.sympify(record['expected']['expression'], locals={'t': t})
        assert sp.expand(result['expression']-expected) == 0
        assert result['source_domain'] == sp.Interval(0, sp.oo)
        assert result['determined_domain'] == sp.Interval(endpoint, sp.oo)
        assert result['declared_domain'] is None
        assert check(description, result)
        for wrong_domain in [sp.S.Reals, sp.Interval(0, sp.oo), sp.Interval.open(endpoint, sp.oo)]:
            assert not check(description, {**result, 'determined_domain': wrong_domain})
