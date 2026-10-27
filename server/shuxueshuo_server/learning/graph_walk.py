"""Versioned graph-walk grading; snapshots come from verified lesson projection.

This is a native contract adapter, separate from the legacy tutor lesson format.
AI playback never submits to this adapter: only student answer events are graded.
"""

from fastapi import HTTPException

SCHEMA = 'graph-walk-practice/v1'


def snapshot(attempt):
    return attempt['problem_context'].get('_graph_walk')


def route_steps(contract, route):
    return contract['intro'] + contract['routes'][route]['steps']


def validate_contract(contract, problem_id):
    if (contract.get('schema') != SCHEMA or contract.get('problemId') != problem_id
            or not contract.get('bundleVersion') or not contract.get('routes')):
        raise ValueError('invalid graph-walk practice identity')
    for route in contract['routes']:
        steps = route_steps(contract, route)
        if not steps or len({step['id'] for step in steps}) != len(steps):
            raise ValueError('invalid graph-walk practice steps')
        for step in steps:
            if step['interaction']['type'] not in {'read', 'choice', 'multi', 'checklist', 'fill', 'plane', 'grid'}:
                raise ValueError('unsupported graph-walk interaction')
            if 'expected_answer' not in step:
                raise ValueError('graph-walk step has no grading contract')


def grade(decision, answer, route):
    """Mirror walk-state.gradeDecision, without trusting a client correctness flag."""
    if set(answer) != {'value'}:
        raise HTTPException(422, '请提交当前图谱步骤的作答。')
    value = answer['value']
    component, expected = decision['interaction'], decision['expected_answer']
    kind = component['type']
    if kind == 'read':
        passed = value == 'read'
        if decision.get('route_by_answer'):
            passed = passed and decision['route_by_answer'].get('read') == route
    elif kind == 'choice':
        if not isinstance(value, str) or value not in {item['value'] for item in component['options']}:
            raise HTTPException(422, '选项不属于本步。')
        passed = value in expected['one_of']
        if decision.get('route_by_answer'):
            passed = passed and decision['route_by_answer'].get(value) == route
    elif kind == 'multi':
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise HTTPException(422, '请提交本步选择的各项。')
        passed = (len(set(value)) == len(value) and set(value) <= set(expected['allowed'])
                  and set(expected['required']) <= set(value))
    elif kind in {'checklist', 'fill'}:
        slots = component.get('slots')
        choices = ([{item['value'] for item in slot['options']} for slot in slots]
                   if slots is not None else [set(component['terms'])] * len(expected['terms']))
        if (not isinstance(value, list) or len(value) != len(choices)
                or any(not isinstance(item, str) or item not in choices[index] for index, item in enumerate(value))):
            raise HTTPException(422, '请按顺序提交本步提供的选项。')
        passed = value == expected['terms']
    elif kind in {'plane', 'grid'}:
        if (not isinstance(value, list) or len(value) != (3 if kind == 'plane' else 2)
                or any(not isinstance(item, str) for item in value)):
            raise HTTPException(422, '请提交适用位置与方法。')
        if any(value[index] not in {item['value'] for item in component[axis]['options']}
               for index, axis in enumerate(('x', 'y'))):
            raise HTTPException(422, '位置不属于本步。')
        passed = value[:2] == expected['cell']
        if kind == 'plane':
            method = next((item for item in component['methods'] if item['value'] == value[2]), None)
            if method is None:
                raise HTTPException(422, '方法不属于本步。')
            passed = passed and value[:2] in method['cells']
            if passed and value[2] in decision.get('alternatives', {}):
                return 'uncovered'
            passed = passed and method.get('route') == route
            if expected.get('method') is not None:
                passed = passed and value[2] == expected['method']
    else:
        raise HTTPException(422, '本步交互尚未支持。')
    return 'passed' if passed else 'wrong'
