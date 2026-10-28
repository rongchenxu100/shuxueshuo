"""Compile abstract-function domain goals without inventing a concrete body.

The original known and requested calls are bound without simplifying them.
Structural admission separately checks identity/invertible-affine known calls
and targets with at most one concrete denominator. No solving happens here.
"""

import re

from .notation_compile import Report, Scope, typecheck
from .notation_parser import NotationError, clean, definition, parse


ABSTRACT_GOAL_KINDS = (
    'find_abstract_domain', 'find_abstract_domain_parameter', 'find_abstract_range',
)


def _names(ast):
    if not isinstance(ast, list) or not ast:
        return set()
    if ast[0] == 'name':
        return {ast[1]}
    return set().union(*(_names(child) for child in ast[1:]))


def _bind_argument(ast, variable):
    """Alpha-rename only a function's bound argument, never its free parameters."""
    if not isinstance(ast, list):
        return ast
    if ast == ['name', variable]:
        return ['bound', 'target_argument']
    return [_bind_argument(child, variable) for child in ast]


def target_naming_aliases(source, path, env):
    """Recognize a redundant target name without admitting extra conditions.

    This is deliberately syntax-preserving: no cancellation or algebraic
    simplification may erase restrictions from the original expression. A
    naming equation must match every goal in this scope, and its name must not
    be used elsewhere (including descendants). All other equations retain the
    ordinary declaration/fact compiler and its fail-closed admission checks.
    """
    goals = source.get('goals', [])
    if not goals or any(goal['kind'] not in ABSTRACT_GOAL_KINDS for goal in goals):
        return {}
    try:
        targets = []
        abstract_names = set()
        for goal in goals:
            known, target = parse(clean(goal['known_call'])), parse(clean(goal['target_call']))
            if known[0] != 'call' or len(known) != 3:
                return {}
            abstract_names.add(known[1])
            if goal['kind'] == 'find_abstract_domain_parameter':
                variable = goal['variable']
            else:
                names = _names(target) or _names(known[2])
                if len(names) != 1:
                    return {}
                variable = next(iter(names))
            targets.append(_bind_argument(target, variable))
        rows = []
        for field in ('definitions', 'facts'):
            for index, text in enumerate(source[field]):
                rows.append((f'{path}.{field}[{index}]', text, definition(text)))
    except (NotationError, RecursionError):
        return {}

    def mentioned(name, value):
        if isinstance(value, str):
            return re.search(rf'(?<!\w){re.escape(name)}(?!\w)', value) is not None
        if isinstance(value, dict):
            return any(mentioned(name, item) for key, item in value.items() if key != 'label')
        if isinstance(value, list):
            return any(mentioned(name, item) for item in value)
        return False

    result = {}
    for name in {ast[1] for _, _, ast in rows if ast[0] == 'function_definition'}:
        if name in abstract_names or env.lookup(name):
            continue
        named = [row for row in rows if row[2][:2] == ['function_definition', name]]
        if any(_bind_argument(ast[3], ast[2]) != target
               for _, _, ast in named for target in targets):
            continue
        if any(mentioned(name, text) for _, text, ast in rows
               if ast[:2] != ['function_definition', name]):
            continue
        if mentioned(name, goals) or mentioned(name, source.get('children', [])):
            continue
        for location, text, ast in named:
            result[location] = {
                'scope': path, 'path': location, 'source': text,
                'name': name, 'variable': ast[2],
                'target_refs': [_pointer(f'{path}.goals[{index}]') for index in range(len(goals))],
            }
    return result


def _pointer(path):
    from ..graph_lesson.stage_one.function_domain import source_pointer

    return source_pointer(path)


def _domain_ast(env, text, path):
    domain = env.bind(parse(text))
    if domain[0] == "tuple":
        domain = ["interval", False, False, *domain[1:]]
    if typecheck(domain) not in ("domain", "set"):
        raise NotationError("abstract_domain.declared_domain_required", path=path)
    return domain


def _declare_scalars(env, ast):
    if not isinstance(ast, list) or not ast:
        return
    if ast[0] == "name":
        env.declare(ast[1], "scalar")
        return
    for child in ast[1:]:
        _declare_scalars(env, child)


def _bind_call(env, text, path, *, introduce_function=False, function_scope=None):
    raw = parse(clean(text))
    if raw[0] != "call" or len(raw) != 3:
        raise NotationError("abstract_domain.function_call_required", path=path)
    name, argument = raw[1], raw[2]
    if introduce_function:
        (function_scope or env).declare(name, "function", local=True)
        # Placeholder identity only gates call binding; it is never a concrete body.
        env.functions[name] = ["function_definition", name, "_", ["number", "0"]]
    if name not in env.functions:
        raise NotationError("abstract_domain.unknown_function", path=path)
    # Free names in the argument become outer scalars for this goal.
    _declare_scalars(env, argument)
    bound = env.bind(raw)
    if bound[0] != "function_call":
        raise NotationError("abstract_domain.function_call_required", path=path)
    return bound


def _bind_target(env, text, path, function_ref):
    """Retain the entire original expression; admission decides its supported shape."""
    raw = parse(clean(text))
    _declare_scalars(env, raw)
    bound = env.bind(raw)
    if typecheck(bound) != "scalar":
        raise NotationError("abstract_domain.scalar_target_required", path=path)

    def check_calls(ast):
        if not isinstance(ast, list) or not ast:
            return
        if ast[0] == "function_call" and ast[1] != function_ref:
            raise NotationError("abstract_domain.function_identity_mismatch", path=path)
        for child in ast[1:]:
            check_calls(child)

    check_calls(bound)
    return bound


def compile_abstract_domain(goal, path):
    """Return a bound abstract-domain goal; pointers stay candidate-local."""
    pointer = _pointer(path)
    parameter_goal = goal['kind'] == 'find_abstract_domain_parameter'
    if goal.get("strength") != "exact" and not parameter_goal:
        raise NotationError("abstract_domain.exact_strength_required",
                            path=f"{pointer}/strength")
    report = Report()
    # Only the function identity is shared by goals in this source scope.
    # Variables remain goal-local; no abstract declaration enters the general
    # fact environment or invents a concrete body for another goal.
    function_scope = Scope(report, _pointer(path.rsplit('.goals[', 1)[0]))
    env = Scope(report, pointer, parent=function_scope)
    known = _bind_call(env, goal["known_call"], f"{pointer}/known_call",
                       introduce_function=True, function_scope=function_scope)
    if parameter_goal:
        if goal['variable'] == goal['parameter']:
            raise NotationError('abstract_domain.distinct_variable_parameter_required', path=pointer)
        for name in (goal['variable'], goal['parameter']):
            env.declare(name, 'scalar')
    target = _bind_target(env, goal["target_call"], f"{pointer}/target_call", known[1])
    domain = _domain_ast(env, goal["known_domain"], f"{pointer}/known_domain")
    result = {
        "kind": goal['kind'],
        "target": target,
        "known_call": known,
        "known_domain": domain,
        "strength": goal['strength'],
        "function_ref": known[1],
        "target_ref": pointer,
    }
    if parameter_goal:
        result.update(variable=env.reference(goal['variable'], 'scalar'),
                      parameter=env.reference(goal['parameter'], 'scalar'),
                      quantifier=goal['quantifier'])
    if "input_domain" in goal:
        result["input_domain"] = _domain_ast(
            env, goal["input_domain"], f"{pointer}/input_domain")
    if "known_range" in goal:
        result["known_range"] = _domain_ast(
            env, goal["known_range"], f"{pointer}/known_range")
    return result


def validate_abstract_knowledge(goals):
    """Repeated exact facts about the same visible call may not conflict.

    This does not derive ranges, borrow a missing range from a sibling, or
    identify different composite calls. It only checks repeated source claims,
    allowing a change of the known call's dummy variable and equivalent sets.
    """
    import sympy as sp

    from .notation_semantics import Canonical

    def set_value(ast):
        if ast[0] == 'real':
            return sp.S.Reals
        if ast[0] == 'interval':
            endpoints = [sp.oo * part[1] if part[0] == 'infinity'
                         else Canonical().expr(part) for part in ast[3:]]
            return sp.Interval(*endpoints, left_open=not ast[1], right_open=not ast[2])
        if ast[0] == 'set':
            return sp.FiniteSet(*(Canonical().expr(part) for part in ast[1:]))
        # Other valid set notation stays structural until its family is enabled.
        return Canonical().tree(ast)

    def bind_known_argument(ast):
        refs = set()

        def collect(value):
            if not isinstance(value, list):
                return
            if value[:1] == ['ref'] and value[2] == 'scalar':
                refs.add(tuple(value))
                return
            for child in value:
                collect(child)

        collect(ast)

        def rewrite(value):
            if not isinstance(value, list):
                return value
            if len(refs) == 1 and tuple(value[:3]) == next(iter(refs)):
                return ['bound', 'known_argument']
            return [rewrite(child) for child in value]

        return rewrite(ast)

    seen = {}
    for goal in goals:
        if goal['kind'] not in ABSTRACT_GOAL_KINDS:
            continue
        values = {field: set_value(goal[field]) for field in ('known_domain', 'known_range')
                  if field in goal}
        if (isinstance(values['known_domain'], sp.Set)
                and values['known_domain'].is_empty is False
                and values.get('known_range') == sp.S.EmptySet):
            # A nonempty collection of legal inputs must produce some output.
            # This validates the source claim; it does not restrict inputs by
            # intersecting the domain with the supplied output range.
            raise NotationError('abstract_domain.empty_range_for_nonempty_domain',
                                path=f"{goal['target_ref']}/known_range")
        call_key = repr([goal['function_ref'], bind_known_argument(goal['known_call'][2])])
        for field in ('known_domain', 'known_range'):
            if field not in goal or (field == 'known_domain' and goal['strength'] != 'exact'):
                continue
            key = (call_key, field)
            value = values[field]
            if key in seen and seen[key] != value:
                raise NotationError('abstract_domain.conflicting_known_fact',
                                    path=f"{goal['target_ref']}/{field}")
            seen[key] = value


def canonical_abstract_domain(goal):
    """Content identity for abstract calls; never expands an unknown body."""

    def syntax(value):
        if isinstance(value, list):
            if value and value[0] == "ref":
                return ["ref", value[1].rsplit(":", 1)[-1], value[2]]
            return [syntax(child) for child in value]
        return value

    value = {
        "kind": goal['kind'],
        "known_call": syntax(goal["known_call"]),
        "known_domain": syntax(goal["known_domain"]),
        "strength": goal["strength"],
        "target": syntax(goal["target"]),
    }
    if goal['kind'] == 'find_abstract_domain_parameter':
        value.update(variable=syntax(goal['variable']), parameter=syntax(goal['parameter']),
                     quantifier=goal['quantifier'])
    if "input_domain" in goal:
        value["input_domain"] = syntax(goal["input_domain"])
    if "known_range" in goal:
        value["known_range"] = syntax(goal["known_range"])
    return value
