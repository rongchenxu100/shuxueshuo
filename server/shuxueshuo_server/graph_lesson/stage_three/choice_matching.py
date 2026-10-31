"""Match printed choices to an already verified answer using exact mathematics.

Call this optional capability in a bounded worker after mathematical completion.
Printed alternatives are never appended to the problem's conditions, and neither
display strings nor numerical sampling decide which label is correct.
"""

import sympy as sp

from ...problem_understanding.notation_compile import Report, Scope, typecheck
from ...problem_understanding.notation_parser import NotationError, parse
from .choice_source import choice_source, option_expression
from .context import build_context
from .goals import _answer_value, verify_goal_answer
from .math_values import math_value
from .route_constraints import _condition_set, _relation_domain, _RouteArithmetic
from .trajectory import decode_value
from .verification import VerificationGap, _set_mismatch, _supported_set

_SETS = {"real", "empty_set", "interval", "tuple", "set", "set_builder", "∪", "∩"}
_RELATIONS = {"=", "!=", "<", "<=", ">", ">=", "∈", "∉", "and", "or"}
_SET_GOALS = {"find_range", "find_domain", "match_domain", "find_abstract_domain", "find_abstract_domain_parameter", "find_abstract_range", "find_translation_range"}


def _domain(ast):
    """Validate set syntax, including unions of the parser's interval domains."""
    kind = ast[0]
    if kind in ("∪", "∩"):
        return [kind, *[_domain(child) for child in ast[1:]]]
    if kind == "tuple":
        ast = ["interval", False, False, *ast[1:]]
    if kind == "set_builder":
        return [kind, ast[1], _domain(ast[2]), _condition(ast[3])]
    if typecheck(ast) not in ("domain", "set"):
        raise NotationError("choice.set_required")
    return ast


def _condition(ast):
    kind = ast[0]
    if kind in ("and", "or"):
        return [kind, *[_condition(child) for child in ast[1:]]]
    if kind == "default_domain":
        ast = ["∈", ast[1], ["real"]]
        kind = "∈"
    if kind in ("∈", "∉"):
        if typecheck(ast[1]) != "scalar":
            raise NotationError("choice.scalar_required")
        return [kind, ast[1], _domain(ast[2])]
    if kind not in _RELATIONS or any(typecheck(part) != "scalar" for part in ast[1:]):
        raise NotationError("choice.parameter_condition_required")
    return ast


def _option_set(expression, parameter_name, goal_kind):
    """Interpret one alternative in a fresh scope containing only the target."""
    ast = parse(expression)
    report = Report()
    scope = Scope(report, "choice")
    symbol = scope.declare(parameter_name, "scalar")
    parameter = ["ref", symbol["ref"], "scalar"]
    algebra = _RouteArithmetic({"goal_ast": {"kind": "find_range", "target": parameter},
                                "symbols": [symbol]})
    if ast[0] in _SETS:
        if goal_kind != "find_range":
            raise NotationError("choice.scalar_answer_required")
        # Open intervals are parsed as tuples. Bind each domain before checking
        # its type, without treating a tuple as an arithmetic expression.
        bound = ["∈", parameter, _domain(scope.bind(ast))]
    elif ast[0] in _RELATIONS:
        bound = _condition(scope.bind(ast))
    elif goal_kind != "find_range":
        value = scope.bind(ast)
        if typecheck(value) != "scalar":
            raise NotationError("choice.scalar_answer_required")
        bound = ["=", parameter, value]
    else:
        raise NotationError("choice.parameter_condition_required")
    result = _condition_set(bound, algebra)
    for divisor in algebra.guards:
        result &= _relation_domain(divisor, "!=", algebra.parameter)
    _supported_set(result)
    if goal_kind != "find_range" and not isinstance(result, sp.FiniteSet):
        raise NotationError("choice.scalar_answer_required")
    if goal_kind != "find_range" and len(result) != 1:
        raise NotationError("choice.scalar_answer_required")
    return result


def _match_converted(source, target_ref, answer, feasible):
    """Match the result type, independently of the original solving method."""
    base = {'status': 'unavailable', 'target_ref': target_ref}
    set_result = answer['status'] == 'set'
    if not set_result and source['selection_mode'] == 'multiple':
        return {**base, 'reason': 'choice.multiple_selection_unsupported'}
    if set_result:
        wanted = feasible
    elif answer['status'] == 'boolean':
        wanted = answer['value']
    elif 'value' in answer:
        wanted = sp.FiniteSet(_answer_value(answer, 'value'))
    else:
        return {**base, 'reason': 'choice.unattained_answer_unsupported'}
    options, matches = [], []
    for option in source['options']:
        if answer['status'] == 'boolean':
            stated = option['text'].strip().strip('$').strip().rstrip('。')
            booleans = {'是': True, '正确': True, '成立': True, '否': False, '错误': False, '不成立': False}
            if stated not in booleans:
                return {**base, 'reason': 'choice.unsupported_option'}
            matches_value = booleans[stated] is wanted
        else:
            expression = option_expression(option['text'], real_parameter='result') if set_result else option['expression']
            if not isinstance(expression, str):
                return {**base, 'reason': 'choice.unsupported_option'}
            actual = _option_set(expression, 'result', 'find_range' if set_result else 'find_value')
            matches_value = _set_mismatch(actual, wanted) is None
        options.append({'label': option['label'], 'text': option['text']})
        if matches_value:
            matches.append(option['label'])
    mode = source['selection_mode']
    if (mode == 'single' or not set_result) and len(matches) != 1:
        return {**base, 'reason': 'choice.ambiguous_match' if matches else 'choice.no_match'}
    return {'status': 'matched', 'kind': 'multiple_choice' if set_result and mode != 'single' else 'single_choice',
            'target_ref': target_ref, 'options': options, 'correct_labels': matches,
            **({'matching': 'set_equality', 'selection_mode': mode} if set_result else {})}


def match_original_choice(candidate, target_ref, answer, feasible_set_exact=None):
    """Return certified original labels, or an explicit unavailable reason.

    Range answers have a legacy display-only set, so their separately verified
    exact feasible set is required. Unsupported, incomplete, or ambiguous
    alternatives disable only this optional final exercise. Set-answer choices
    use exact set equality; unspecified selection mode is nonexclusive.
    """
    source = choice_source(candidate, target_ref)
    if source["status"] == "not_choice":
        return None
    base = {"status": "unavailable", "target_ref": target_ref}
    if source["status"] != "recognized":
        return {**base, "reason": source["reason"]}
    try:
        context = build_context(candidate, target_ref)
        goal, goal_ast = context["goal"], context["goal_ast"]
        if 'answer_request' in goal:
            if feasible_set_exact is None:
                return {**base, 'reason': 'choice.exact_answer_required'}
            feasible = decode_value(feasible_set_exact)
            verify_goal_answer(goal, feasible, answer)
            return _match_converted(source, target_ref, answer, feasible)
        if goal['kind'] == 'select_range_domain':
            if feasible_set_exact is None:
                return {**base, 'reason': 'choice.exact_answer_required'}
            verify_goal_answer(goal, decode_value(feasible_set_exact), answer)
            from ...search.identity import _surface
            shown = [(row['label'], _surface(row['text'])) for row in source['options']]
            original = [(row['label'], _surface(row['text'])) for row in goal['options']]
            if shown != original or source['selection_mode'] != goal['selection_mode']:
                return {**base, 'reason': 'choice.option_identity_mismatch'}
            return {'status': 'matched', 'kind': 'single_choice' if goal['selection_mode'] == 'single' else 'multiple_choice',
                    'matching': 'range_domain_options', 'selection_mode': goal['selection_mode'],
                    'target_ref': target_ref, 'options': [{'label': row['label'], 'text': row['text']} for row in source['options']],
                    'correct_labels': answer['correct_labels']}
        set_goal = goal["kind"] in _SET_GOALS
        if (not set_goal and goal["kind"] not in ("find_minimum", "find_maximum", 'find_extrema_expression')
                or not isinstance(answer, dict) or answer.get("kind") != goal["kind"]):
            return {**base, "reason": "choice.unsupported_goal"}
        if not set_goal and source["selection_mode"] == "multiple":
            return {**base, "reason": "choice.multiple_selection_unsupported"}
        if feasible_set_exact is not None:
            feasible = decode_value(feasible_set_exact)
            _supported_set(feasible)
            verify_goal_answer(goal, feasible, answer)
        elif set_goal or goal['kind'] == 'find_extrema_expression':
            return {**base, "reason": "choice.exact_answer_required"}
        if set_goal:
            if answer["set"].get("expression") != math_value(feasible)["expression"]:
                return {**base, "reason": "choice.answer_mismatch"}
            expected = feasible
        elif answer.get("status") == "attained" or (goal['kind'] == 'find_extrema_expression' and answer.get('status') == 'value'):
            expected = sp.FiniteSet(_answer_value(answer, "value"))
        else:
            return {**base, "reason": "choice.unattained_answer_unsupported"}
        if goal['kind'] == 'find_extrema_expression':
            parameter_name = 'result'
        elif goal["kind"] == "find_abstract_domain_parameter":
            parameter_name = goal["parameter"]
        elif goal["kind"] in ("find_abstract_range", "find_translation_range"):
            parameter_name = "y"
        elif goal["kind"] == "find_abstract_domain":
            parameter_name = context["abstract_domain_goal"]["variable"]
        elif goal["kind"] == "find_domain":
            parameter_name = context["domain_goal"]["variable"]
        elif goal["kind"] == "match_domain":
            parameter_name = context["domain_goal"]["parameter"]
        else:
            if goal_ast["target"][0] != "ref":
                return {**base, "reason": "choice.unsupported_goal"}
            parameter_name = next(symbol["name"] for symbol in context["symbols"]
                                  if symbol["ref"] == goal_ast["target"][1])
        option_sets = []
        for option in source["options"]:
            expression = option_expression(option["text"], real_parameter=parameter_name) if set_goal else option["expression"]
            if not isinstance(expression, str):
                return {**base, "reason": "choice.unsupported_option"}
            option_sets.append(_option_set(expression, parameter_name,
                                           "find_range" if set_goal else goal["kind"]))
        matches = [option["label"] for option, value in zip(source["options"], option_sets, strict=True)
                   if _set_mismatch(value, expected) is None]
    except (NotationError, VerificationGap, ValueError, TypeError, KeyError,
            StopIteration, IndexError, RecursionError, ZeroDivisionError):
        return {**base, "reason": "choice.unverifiable_options"}
    if (not set_goal or source["selection_mode"] == "single") and len(matches) != 1:
        return {**base, "reason": "choice.ambiguous_match" if matches else "choice.no_match"}
    mode = source["selection_mode"]
    return {"status": "matched", "kind": "multiple_choice" if set_goal and mode != "single" else "single_choice", "target_ref": target_ref,
            **({"matching": "set_equality", "selection_mode": mode} if set_goal else {}),
            "options": [{"label": option["label"], "text": option["text"]}
                        for option in source["options"]], "correct_labels": matches}


def dispatch(payload):
    """Independent worker entry; does not share mathematical fault hooks/budget."""
    return match_original_choice(payload["candidate"], payload["target_ref"],
                                 payload["answer"], payload["feasible_set_exact"])
