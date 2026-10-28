"""Independent frozen structural pairs; not new photo/provider evidence."""

import json
from hashlib import sha256
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.function_equality import compare_pair, verify_pair
from shuxueshuo_server.problem_understanding.notation_function_comparison import (
    compile_comparison,
)

FIXTURE = Path(__file__).parent / 'fixtures/function-equality/domain-first-heldout-frozen.json'
FROZEN_SHA256 = 'fe4b36f579d3265c37f3ca2163e5d24d4e6b10a9f30c920648c7f7be9944248b'
FROZEN = json.loads(FIXTURE.read_text())


def _descriptors(row):
    functions = [{'id': side, 'definition': f'{name}(x)={row[side]}'}
                 for side, name in [('left', 'f'), ('right', 'g')]]
    if row['domain'] is not None:
        for function in functions:
            function['domain'] = row['domain']
    goal = {'kind': 'compare_functions', 'mode': 'pair', 'select_relation': None,
            'selection_mode': 'none', 'completeness': 'complete', 'shared_functions': [],
            'options': [{'id': 'pair', 'label': 'A', 'text': '比较两个函数', 'functions': functions,
                         'left': 'local:left', 'right': 'local:right'}]}
    option, = compile_comparison(goal, 'r.goals[0]')['options']
    return option['left'], option['right']


def _gold_set(text):
    value = sp.sympify(text, locals={'Interval': sp.Interval, 'Union': sp.Union,
                                    'oo': sp.oo, 'Reals': sp.S.Reals})
    return sp.FiniteSet(*value) if isinstance(value, set) else value


def test_structural_gold_was_frozen_before_comparator_execution():
    assert sha256(FIXTURE.read_bytes()).hexdigest() == FROZEN_SHA256
    assert len(FROZEN['cases']) == 8
    assert FROZEN['contract'] == 'independent-structural-holdout/v1'


@pytest.mark.parametrize('row', FROZEN['cases'], ids=lambda row: row['id'])
def test_unseen_coefficients_domains_and_rational_forms(row):
    left, right = _descriptors(row)
    result = compare_pair(left, right)
    assert result['relation'] == row['relation'], result
    assert result['left']['domain'] == _gold_set(row['left_domain'])
    assert result['right']['domain'] == _gold_set(row['right_domain'])
    assert verify_pair(left, right, result)['status'] == 'verified'
    reverse = compare_pair(right, left)
    assert reverse['relation'] == row['relation'], reverse
    assert verify_pair(right, left, reverse)['status'] == 'verified'
