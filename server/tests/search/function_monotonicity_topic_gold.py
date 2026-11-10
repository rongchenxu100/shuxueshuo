"""Printed-photo answers, solved independently; never used by extraction/solver."""

import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.problem_understanding.notation_parser import definition, parse

I, R, oo = sp.Interval, sp.Rational, sp.oo
INTERVALS = {
    'a01': [I(-oo, -1), I(0, 1)], 'a02': [I(-R(3, 2), R(1, 4))],
    'a03': [I(0, 2)], 'a04': [I.open(-oo, -1)],
    'a12': [I(-oo, -1)], 'a15': [I(1, 2)],
}
SETS = {
    'a05': I(-oo, 2), 'a06': I.Lopen(-2, R(4, 5)), 'a07': I.Lopen(0, 2),
    'a08': I.Lopen(0, R(5, 3)), 'a09': I(5, oo), 'a10': I(-1, -R(1, 2)),
    'a11': I(-oo, 0), 'a13': I(R(1, 2), 1), 'a17': I.Ropen(R(1, 6), R(1, 3)),
    'a18': I.Lopen(0, 2), 'b01': I.open(0, 1), 'b02': I.Lopen(R(1, 2), R(2, 3)),
    'b03': I.open(-R(3, 2), 2), 'b04': I.open(-1, 3), 'b05': I.Ropen(R(1, 2), R(2, 3)),
    'b07': I.open(1, 4), 'b08': I(0, 2), 'b09': I.open(1, 4),
    'b10': I.open(2 + sp.sqrt(7), oo), 'b11': I(-oo, -4) | I(2, oo),
    'b12': I.open(-1, sp.sqrt(2) - 1), 'b13': I.Ropen(R(1, 2), R(2, 3)),
    'b14': I(-oo, -2) | I((3 + sp.sqrt(13)) / 2, oo), 'b16': I.open(-oo, -1),
}
VALUES = {'a14': sp.Integer(3), 'a16': sp.Integer(1), 'b09': sp.Integer(15), 'b15': R(9, 2)}
KEYS = [*(f'a{i:02d}' for i in range(1, 19)), *(f'b{i:02d}' for i in range(1, 17))]
FUNCTIONS = {
    'a01': ['f(x)=-x^2+2*abs(x)+3'],
    'a02': ['f(x)=sqrt(-2*x^2+x+6)'],
    'a03': ['f(x)=-x^2+4*x+3'],
    'a04': ['f(x)=1/sqrt(x^2-5*x-6)'],
    'a05': ['f(x)=x^2-m*x+5'],
    'a06': ['f(x)=piecewise(x^2-a*x+a/2,x>=1,(2*a+4)*x-5,x<1)'],
    'a07': ['g(x)=a*x+1', 'f(x)=x^2+2*x'],
    'a08': ['f(x)=piecewise(-x^2+a*x-a,x>2,1-a*x,x<=2)'],
    'a09': ['f(x)=x^2-2*(a-1)*x+2'],
    'a10': ['f(x)=piecewise(a/x,0<x<=1,x-a/x-2,x>1)'],
    'a11': ['f(x)=a*x^2-2*x+3'],
    'a12': ['f(x)=sqrt(x^2-2*x-3)'],
    'a13': ['f(x)=sqrt(a*x^2+2*x-5*a+5)'],
    'a14': ['f(x)=sqrt(1-2*x)+2*x^2-5*x+5'],
    'a15': ['f(x)=sqrt(-x^2+4*x-3)'],
    'a16': ['f(x)=(2*x+1)/(x+3)'],
    'a17': ['f(x)=piecewise((3*a-1)*x+4*a,x<1,a/x,x>=1)'],
    'a18': ['f(x)=piecewise(-x^3+2,x<0,-x+3,x>=0)', 'g(x)=k*x+5-2*k'],
    'b03': ['f(x)=piecewise(2*x-1,x<1,x^2,x>=1)'],
    'b07': ['f(x)=piecewise(3*x,x>=3,-x^2+6*x,x<3)'],
    'b08': ['f(x)=piecewise((x-a)^2,x<=0,x+1/x+a,x>0)'],
    'b09': ['f(x)=piecewise(3*x,x>=3,-x^2+6*x,x<3)'],
    'b10': ['f(x)=-1/x+x', 'g(x)=x^2-4*x-3'],
    'b11': ['f(x)=x^2-2*x', 'g(x)=a*x-1'],
    'b12': ['f(x)=piecewise(x^2+1,x>=0,1,x<0)'],
    'b14': ['f(x)=piecewise(-(x-a)^2+a+5/2,x<1,-1/2*x+1,x>=1)'],
}


def assert_function_transcription(key, candidate):
    """Compare printed formula structure, so a wrong OCR root cannot pass by luck."""
    definitions = [definition(v) for v in candidate['root'].get('definitions', [])]
    for text in FUNCTIONS.get(key, []):
        expected = definition(text)
        matches = [v for v in definitions if v[:2] == expected[:2]]
        if not matches and key in ('a03', 'a11'):
            # A printed y=… and its named function describe the same output.
            matches = [[*expected[:3], v[2]] for v in definitions if v[:2] == ['=', ['name', 'y']]]
        assert matches == [expected], (key, definitions, expected)
    if key == 'a03':
        assert parse(candidate['root']['goals'][0]['input_domain']) == parse('[0,3]')


def exact(value):
    if isinstance(value, dict) and 'exact' in value:
        return decode_value(value['exact'])
    if isinstance(value, dict) and '$math' in value:
        return decode_value(value)
    # Older snapshot families only expose a trusted local, generated expression.
    if isinstance(value, dict) and 'expression' in value:
        return sp.sympify(value['expression'])
    raise AssertionError(f'Missing exact mathematical result: {value!r}')


def assert_answers(key, snapshot):
    assert key != 'b06', 'The printed B06 does not determine the complete solution set.'
    goals = list(snapshot['goals'].values())
    assert len(goals) == (2 if key == 'b09' else 1)
    assert all(g['available'] and g['status'] == 'solved' for g in goals)
    if key in INTERVALS:
        answer = goals[0]['answer']
        direction = 'decreasing' if key == 'a12' else 'increasing'
        assert answer['direction'] == direction
        actual = [decode_value(v) for v in answer['interval_families'][direction]]
        assert actual == INTERVALS[key], (key, actual)
    if key in SETS:
        sets = [exact(g['feasible_set']) for g in goals if g.get('feasible_set')]
        assert sets == [SETS[key]], (key, sets)
    if key in VALUES:
        values = [exact(g['answer']['value']) for g in goals if 'value' in g['answer']]
        assert values == [VALUES[key]], (key, values)
