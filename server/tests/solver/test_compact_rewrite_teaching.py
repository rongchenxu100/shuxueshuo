"""Compact teaching follows verified expression structure, not problem IDs."""
import json
from pathlib import Path

import pytest
import sympy as sp
from test_organize_expressions import run

from shuxueshuo_server.solver.explanation.expression_rewrite import (
    build_rewrite_presentation,
)
from shuxueshuo_server.solver.runtime.inequality_teaching_evidence import (
    existing_square_latex,
)
from shuxueshuo_server.solver.visual.teaching_diagrams import (
    quadratic,
    validate_diagram_block,
)


@pytest.mark.parametrize('x,z,k', [('a','c',5), ('u','v',3)])
def test_square_already_visible_uses_two_rows(x,z,k):
    symbols = {s: sp.Symbol(s, real=True) for s in (x,z)}
    rest = f'{x}^2+4/{x}^2'
    source = f'({x}-{k}*{z})^2+{rest}'
    # The certificate can use a different center/coefficient spelling.
    square = f'{k*k}*({z}-{x}/{k})^2'
    existing = existing_square_latex(source, square, rest, symbols)
    assert existing is not None
    d = {'square_latex': 'certified square', 'existing_square_latex': existing,
         'teaching_effect': {'before_latex': source, 'after_latex': rest}}
    visual = quadratic(d)
    rows = visual['organization']['expressionFlow']
    assert len(rows) == 2
    assert rows[0]['parts'][0]['highlight']
    assert rows[1]['relation'] == '≥'
    expanded = f'2*{x}^2-{2*k}*{x}*{z}+{k*k}*{z}^2+4/{x}^2'
    assert existing_square_latex(expanded, square, rest, symbols) is None
    d['existing_square_latex'] = None
    assert len(quadratic(d)['organization']['expressionFlow']) == 3
    assert existing_square_latex(source, square, rest+'+1', symbols) is None


def test_saved_m01_keeps_two_changes_and_drops_tautological_display_rows():
    path = Path(__file__).parent/'fixtures/basic-inequality-stage5c/original-expression-plan.json'
    steps = json.loads(path.read_text())['root_scope']['goals'][0]['steps'][0]['parameters']['steps']
    result = run({'symbols': ['a','b','c'],
                  'expression': '2*a^2+1/(a*b)+1/(a*(a-b))-10*a*c+25*c^2',
                  'conditions': {'c1':'a>b','c2':'b>c','c3':'c>0'},
                  'call': {'parameters': {'steps':steps}}})
    trace = result.trace_fragments[0]
    count = len(trace['transitions'])
    presentation = build_rewrite_presentation(trace)
    assert presentation['visual']['presentation'] == 'compact'
    assert [t['label'] for t in presentation['visual']['transitions']] == ['通分','配方']
    assert len(presentation['derive']) == 3
    assert len(trace['transitions']) == count  # Keep proof/audit rows intact.
    block = {'spec_id':'expression.rewrite','spec_version':1,
             'visual_kind':'teaching_diagram','component_id':'expression-rewrite',
             'component_version':1,'source_step_ids':['organize'],
             'evidence_refs':['verified-rewrite'],'data':presentation['visual']}
    validate_diagram_block(block)
    block['data']['presentation'] = 'unknown'
    with pytest.raises(ValueError, match='presentation_invalid'):
        validate_diagram_block(block)
