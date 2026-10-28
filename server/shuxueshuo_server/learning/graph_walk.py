"""Versioned graph-walk grading; snapshots come from verified lesson projection.

This is a native contract adapter, separate from the legacy tutor lesson format.
AI playback never submits to this adapter: only student answer events are graded.
"""

from fastapi import HTTPException

SCHEMA = 'graph-walk-practice/v1'
EXACT_CHOICE = 'original_choice_exact_set'


def _single_original(decision):
    component = decision.get('interaction', {})
    return (decision.get('source') == 'original_choice' and component.get('type') == 'choice'
            and component.get('field') == 'original_choice')


def _comparison_answer_contract(decision):
    if not _single_original(decision):
        return exact_choice_contract(decision)
    expected = decision.get('expected_answer', {})
    options = decision['interaction'].get('options', [])
    if (not isinstance(expected, dict) or set(expected) != {'one_of'}
            or not isinstance(expected['one_of'], list) or len(expected['one_of']) != 1
            or not isinstance(expected['one_of'][0], str) or not isinstance(options, list)):
        raise ValueError('invalid original single-choice contract')
    labels = [option.get('value') for option in options if isinstance(option, dict)]
    if (len(labels) != len(options) or not labels
            or any(not isinstance(label, str) or not label for label in labels)
            or len(set(labels)) != len(labels) or expected['one_of'][0] not in labels):
        raise ValueError('invalid original single-choice labels')
    return {'correct_labels': expected['one_of'], 'option_labels': labels}


def exact_choice_contract(decision):
    """Original exam answers never inherit step-multi's optional choices."""
    expected = decision.get('expected_answer')
    options = decision.get('interaction', {}).get('options', [])
    if (decision.get('source') != 'original_choice'
            or decision.get('interaction', {}).get('type') != EXACT_CHOICE
            or not isinstance(expected, dict) or set(expected) != {'correct_labels', 'option_labels'}
            or not isinstance(options, list)):
        raise ValueError('invalid original-choice exact-set contract')
    labels = [item.get('value') for item in options if isinstance(item, dict)]
    for values in (labels, expected['correct_labels'], expected['option_labels']):
        if (not isinstance(values, list) or any(not isinstance(item, str) or not item for item in values)
                or len(set(values)) != len(values)):
            raise ValueError('invalid original-choice labels')
    if (len(labels) != len(options) or not labels or set(labels) != set(expected['option_labels'])
            or not set(expected['correct_labels']) <= set(labels)):
        raise ValueError('invalid original-choice label mapping')
    return expected


def option_requirements(contract, route, decision):
    """Validate a complete comparison lesson and return all prerequisite step ids."""
    required = decision.get('require_complete_options')
    if (not isinstance(required, list) or not required
            or any(not isinstance(item, str) or not item for item in required)
            or len(set(required)) != len(required) or decision.get('select_relation') not in {'equal', 'different'}
            or not isinstance(decision.get('target_ref'), str) or not decision['target_ref']):
        raise ValueError('invalid option-completion requirements')
    groups = {}
    prerequisites = []
    last = None
    for step in route_steps(contract, route):
        if step['id'] == decision['id']:
            break
        prerequisites.append(step['id'])
        context = step.get('option_context')
        if context is None:
            continue
        if (not isinstance(context, dict) or any(not isinstance(context.get(key), str) or not context[key]
                for key in ('option_id', 'label', 'target_ref', 'left_ref', 'right_ref'))
                or context.get('phase') not in {'evidence', 'verdict'} or context['target_ref'] != decision['target_ref']):
            raise ValueError('invalid comparison option context')
        option = context['option_id']
        if option not in required or option in groups and option != last:
            raise ValueError('invalid comparison option ordering')
        group = groups.setdefault(option, [])
        if group and (group[-1]['option_context']['phase'] == 'verdict' or any(
                group[0]['option_context'][key] != context[key]
                for key in ('label', 'target_ref', 'left_ref', 'right_ref'))):
            raise ValueError('invalid comparison option scope')
        group.append(step)
        last = option
    if list(groups) != required:
        raise ValueError('missing comparison options')
    correct = []
    labels = []
    for group in groups.values():
        final = group[-1]
        if (len(group) < 2 or final['option_context']['phase'] != 'verdict'
                or final['interaction']['type'] != 'choice'
                or final['expected_answer'].get('one_of') not in (['equal'], ['different'])
                or {item['value'] for item in final['interaction']['options']} != {'equal', 'different'}):
            raise ValueError('comparison option needs evidence and a single verdict choice')
        label = final['option_context']['label']
        labels.append(label)
        if final['expected_answer']['one_of'][0] == decision['select_relation']:
            correct.append(label)
    expected = _comparison_answer_contract(decision)
    if labels != expected['option_labels'] or set(correct) != set(expected['correct_labels']):
        raise ValueError('comparison verdicts disagree with original-choice polarity')
    return prerequisites


def ensure_option_prerequisites(contract, route, decision, passed_ids):
    if decision.get('interaction', {}).get('type') != EXACT_CHOICE and not decision.get('require_complete_options'):
        return
    try:
        required = option_requirements(contract, route, decision)
    except ValueError as error:
        raise HTTPException(409, '本题判断记录不完整，请重新开始练习。') from error
    if not set(required) <= set(passed_ids):
        raise HTTPException(409, '请先完成每个选项的证据步骤和判断，再提交原题答案。')


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
            if ((step.get('require_complete_options') or step.get('source') == 'original_choice'
                 and step['interaction']['type'] == 'multi') and step['interaction']['type'] != EXACT_CHOICE
                    and not _single_original(step)):
                raise ValueError('original multiple choice requires its independent grader')
            if step['interaction']['type'] not in {'read', 'choice', 'multi', 'checklist', 'fill', 'plane', 'grid', EXACT_CHOICE}:
                raise ValueError('unsupported graph-walk interaction')
            if 'expected_answer' not in step:
                raise ValueError('graph-walk step has no grading contract')
            if step['interaction']['type'] == EXACT_CHOICE or step.get('require_complete_options'):
                if step is not steps[-1]:
                    raise ValueError('original-choice exact answer must finish the route')
                option_requirements(contract, route, step)


def grade(decision, answer, route):
    """Mirror walk-state.gradeDecision, without trusting a client correctness flag."""
    if set(answer) != {'value'}:
        raise HTTPException(422, '请提交当前图谱步骤的作答。')
    value = answer['value']
    component, expected = decision['interaction'], decision['expected_answer']
    kind = component['type']
    if ((decision.get('require_complete_options') or decision.get('source') == 'original_choice' and kind == 'multi')
            and kind != EXACT_CHOICE and not _single_original(decision)):
        raise HTTPException(422, '原题多选必须使用独立的精确评分。')
    if _single_original(decision) and decision.get('require_complete_options'):
        try:
            _comparison_answer_contract(decision)
        except ValueError as error:
            raise HTTPException(422, '原题单选评分契约无效。') from error
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
    elif kind == EXACT_CHOICE:
        try:
            expected = exact_choice_contract(decision)
        except ValueError as error:
            raise HTTPException(422, '原题多选评分契约无效。') from error
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise HTTPException(422, '请提交原题选择的标签数组。')
        passed = (len(set(value)) == len(value) and set(value) <= set(expected['option_labels'])
                  and set(value) == set(expected['correct_labels']))
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
