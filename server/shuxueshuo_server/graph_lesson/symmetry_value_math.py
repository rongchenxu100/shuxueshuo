"""FP-T3 R2–R3: values of one or two parity functions at numeric inputs (M5, opposite-input subrange).

Every call F(c) is rewritten by F's given parity to one input of the pair {c, -c}.
An input inside the printed rule's range is substituted, and an odd F(0) is 0.
A stated identity Σ k·F(±x) = H(x) is used at each needed input and its opposite.
Any other value is an unknown, constrained only by these linear equations.
The target is determined iff its coefficient row is a combination of the
equations; otherwise two assignments with different targets witness that it is not.
"""
from copy import deepcopy

import sympy as sp

from . import function_cells, parity_compatibility
from . import parity_parameter_math as base
from .parity_extension_math import (
    ARGUMENT,
    SIGNS,
    _agree,
    _replace,
    local_rule,
    reflect,
    region,
    rule_expression,
    undefined_on,
    within_domain_scope,
)

VERSION = 'function-symmetry/r3-v2'
LIMITS = {'calls': 32, 'conditions': 32, 'unknowns': 32, 'functions': 2}
MODEL_KEYS = {'version', 'description', 'variable', 'signs', 'rule', 'rule_domain', 'calls', 'keys', 'equations',
              'target_coefficients', 'target_constant', 'multipliers', 'witnesses', 'value', 'status', 'borrow'}


def _function_calls(ast):
    if not isinstance(ast, list):
        return []
    if ast[:1] == ['function_call']:
        return [ast]
    return [call for child in ast[1:] for call in _function_calls(child)]


def _refs(ast):
    if not isinstance(ast, list):
        return []
    if ast[:1] == ['ref']:
        return [ast]
    return [node for child in ast[1:] for node in _refs(child)]


def _name(fn, names):
    if fn[0] != 'ref' or fn[1].rsplit(':', 1)[-1] not in names:
        raise ValueError('symmetry_value.other_function')
    return fn[1].rsplit(':', 1)[-1]


def _constant(ast, x):
    if 'ref' in str(ast) or 'bound' in str(ast):
        raise ValueError('symmetry_value.symbolic_input')
    value = rule_expression(ast, x)
    if value.free_symbols or not value.is_real or undefined_on(ast, value, x, sp.S.Reals):
        raise ValueError('symmetry_value.constant_required')
    return value


def _literal(t):
    """Exact AST for a real quadratic algebraic input (no floating-point reconstruction)."""
    t = function_cells.exact_point(sp.simplify(t))
    if t < 0:
        return ['neg', _literal(-t)]
    if t.is_Integer:
        return ['number', str(t)]
    if t.is_Rational:
        return ['/', ['number', str(t.p)], ['number', str(t.q)]]
    if t.is_Add or t.is_Mul:
        op, args = ('+' if t.is_Add else '*'), list(t.args)
        node = _literal(args[0])
        for arg in args[1:]:
            node = [op, node, _literal(arg)]
        return node
    if t.is_Pow and t.exp == sp.S.Half:
        return ['call', 'sqrt', _literal(t.base)]
    raise ValueError('symmetry_value.algebraic_input_form_unsupported')


def _combine(read, ast, names, x, scalar):
    """Linear combination of calls; `read(call)` gives its key, `scalar` the call-free parts."""
    if not _function_calls(ast):
        return {}, scalar(ast)
    op = ast[0]
    if op == 'function_call':
        return {read(ast): sp.S.One}, sp.S.Zero
    if op == 'neg':
        terms, constant = _combine(read, ast[1], names, x, scalar)
        return {k: -v for k, v in terms.items()}, -constant
    if op in ('+', '-'):
        (a, p), (b, q) = (_combine(read, side, names, x, scalar) for side in ast[1:3])
        sign = 1 if op == '+' else -1
        terms = dict(a)
        for k, v in b.items():
            terms[k] = terms.get(k, 0) + sign * v
        return {k: v for k, v in terms.items() if v != 0}, p + sign * q
    if op == '*':
        if not _function_calls(ast[1]):
            factor, inner = ast[1], ast[2]
        elif not _function_calls(ast[2]):
            factor, inner = ast[2], ast[1]
        else:
            raise ValueError('symmetry_value.nonlinear_value_relation')
        scale = scalar(factor)
        if scale.free_symbols:
            raise ValueError('symmetry_value.nonlinear_value_relation')
        terms, constant = _combine(read, inner, names, x, scalar)
        return {k: scale * v for k, v in terms.items() if scale * v != 0}, scale * constant
    if op == '/' and not _function_calls(ast[2]):
        d = scalar(ast[2])
        if d.free_symbols or d == 0:
            raise ValueError('symmetry_value.zero_denominator')
        terms, constant = _combine(read, ast[1], names, x, scalar)
        return {k: v / d for k, v in terms.items()}, constant / d
    raise ValueError('symmetry_value.nonlinear_value_relation')


def linear(ast, names, x):
    """({(F, c): coefficient}, constant) of a linear combination of calls F(c); repeated calls add up."""
    def read(call):
        c = _constant(call[2], x)
        function_cells.exact_point(c)
        return _name(call[1], names), c
    return _combine(read, ast, names, x, lambda node: _constant(node, x))


def _equation(ast, names, x):
    if ast[0] != '=' or len(ast) != 3:
        raise ValueError('symmetry_value.additional_condition_unsupported')
    (a, p), (b, q) = linear(ast[1], names, x), linear(ast[2], names, x)
    terms = dict(a)
    for k, v in b.items():
        terms[k] = terms.get(k, 0) - v
    return {k: v for k, v in terms.items() if v != 0}, q - p


def identity_form(ast, names, x):
    """({(F, σ): k}, H) with Σ k·F(σx) = H(x), σ = ±1 and constant k."""
    if ast[0] != '=' or len(ast) != 3:
        raise ValueError('symmetry_value.identity_equation_required')

    def read(call):
        sigma = {str(ARGUMENT): 1, str(['neg', ARGUMENT]): -1}.get(str(call[2]))
        if sigma is None:
            raise ValueError('symmetry_value.identity_argument_unsupported')
        return _name(call[1], names), sigma
    (a, p), (b, q) = (_combine(read, side, names, x, lambda node: rule_expression(node, x)) for side in ast[1:3])
    terms = dict(a)
    for k, v in b.items():
        terms[k] = terms.get(k, 0) - v
    # Printed zero coefficients may cancel every call: 0 = H then adds nothing or contradicts.
    if not _function_calls(ast):
        raise ValueError('symmetry_value.identity_without_function')
    return {k: v for k, v in terms.items() if v != 0}, sp.expand(q - p)


def target_ast(goal_ast):
    return goal_ast.get('value') if 'relation' in goal_ast else goal_ast.get('target')


def domain_of(desc):
    return sp.S.Reals if desc['domain_ast'] is None else region(desc['domain_ast'])


def signs(desc):
    return {F['name']: SIGNS[F['property']] for F in desc['functions']}


def names_of(desc):
    return [F['name'] for F in desc['functions']]


def rule_of(desc):
    """(rule, I) with I = D ∩ printed range; (None, ∅) without a printed rule."""
    if desc['rule_ast'] is None:
        return None, sp.S.EmptySet
    x = sp.Symbol(desc['variable'], real=True)
    return rule_expression(desc['rule_ast'], x), domain_of(desc) & region(desc['rule_domain_ast'])


def identity_range(desc, identity):
    """Where a stated identity applies: the shared domain, cut by its own printed range."""
    domain = domain_of(desc)
    return domain if identity['domain_ast'] is None else domain & region(identity['domain_ast'])


def _check_rule(desc):
    rule, known = rule_of(desc)
    if rule is None:
        return
    x, sign = sp.Symbol(desc['variable'], real=True), signs(desc)[desc['function']]
    if known == sp.S.EmptySet:
        raise ValueError('symmetry_value.rule_outside_domain')
    if undefined_on(desc['rule_ast'], rule, x, known):
        raise ValueError('symmetry_value.rule_undefined_on_range')
    if not _agree(rule.xreplace({x: -x}), sign * rule, known & reflect(known), x):
        raise ValueError('symmetry_value.overlap_conflict')
    if sign == -1 and known.contains(0) is sp.true and rule.subs(x, 0) != 0:
        raise ValueError('symmetry_value.overlap_conflict')


def globally_consistent(desc):
    """All identities must hold together on every input pair, not only at the target.

    A separate column represents each function. Range boundaries partition the
    positive half of D; on each cell both orientations give a constant matrix.
    Its left nullspace gives exactly the identities the right sides must satisfy.
    At zero odd functions vanish and the even functions remain separate unknowns.
    """
    x, names, sign_of = sp.Symbol(desc['variable'], real=True), names_of(desc), signs(desc)
    domain = domain_of(desc)
    rows = [(identity_form(i['ast'], names, x), identity_range(desc, i)) for i in desc['identities']]
    rule, known = rule_of(desc)
    if rule is not None:
        rows.append((({(desc['function'], 1): sp.S.One}, rule), known))
    if len(rows) > LIMITS['conditions']:
        raise ValueError('symmetry_value.budget')
    cuts = {p for _, applies in rows for p in applies.boundary if p.is_finite}
    zero_functions = {F['name'] for F in desc['functions'] if F['property'] == 'both'}
    for atom in parity_compatibility.fixed_atoms(domain, sp.S.EmptySet, [], cuts=[*cuts, *(-p for p in cuts)]):
        sample, cell = atom['representative'], atom['set']
        if sample < 0:
            continue
        matrix, rhs = [], []
        for (form, h), applies in rows:
            for flip in ((1,) if sample == 0 else (1, -1)):
                if applies.contains(flip * sample) is not sp.true:
                    continue
                vector = [sp.S.Zero] * len(names)
                for (name, sigma), coefficient in form.items():
                    if name in zero_functions or (sample == 0 and sign_of[name] == -1):
                        continue
                    vector[names.index(name)] += coefficient * (1 if sigma * flip == 1 else sign_of[name])
                matrix.append(vector)
                rhs.append(h.xreplace({x: flip * x}))
        if not matrix:
            continue
        for dependency in sp.Matrix(matrix).T.nullspace():
            residual = sum((c * h for c, h in zip(dependency, rhs)), sp.S.Zero)
            if not _agree(residual, sp.S.Zero, cell, x):
                return False
    return True


def _route(key, desc, chosen):
    """F(c) = factor * F(image): a substituted value, odd zero, or an unknown representative."""
    name, c = key
    rule, known = rule_of(desc)
    sign = signs(desc)[name]
    x = sp.Symbol(desc['variable'], real=True)
    row = {'function': name, 'input': c}
    if (c == 0 and sign == -1) or any(F['name'] == name and F['property'] == 'both' for F in desc['functions']):
        return {**row, 'route': 'zero', 'image': None, 'factor': sp.S.One, 'value': sp.S.Zero}
    if rule is not None and name == desc['function']:
        if known.contains(c) is sp.true:
            return {**row, 'route': 'rule', 'image': c, 'factor': sp.S.One, 'value': rule.subs(x, c)}
        if known.contains(-c) is sp.true:
            return {**row, 'route': 'mirrored_rule', 'image': -c, 'factor': sp.S(sign),
                    'value': sign * rule.subs(x, -c)}
    image = chosen.setdefault((name, abs(c)), c)
    return {**row, 'route': 'unknown', 'image': image, 'factor': sp.S.One if image == c else sp.S(sign),
            'value': None}


def needed_inputs(desc):
    """Inputs of the target and given values, each followed by its opposite."""
    x, names = sp.Symbol(desc['variable'], real=True), names_of(desc)
    inputs = [c for r in desc['value_equations'] for (_, c) in _equation(r['ast'], names, x)[0]]
    inputs += [c for (_, c) in linear(desc['target_ast'], names, x)[0]]
    return list(dict.fromkeys(t for c in inputs for t in (c, -c)))


def instances(desc):
    """(identity, t) for every needed input t inside the identity's range."""
    return [(identity, t) for identity in desc['identities'] for t in needed_inputs(desc)
            if identity_range(desc, identity).contains(t) is sp.true]


def _rows(desc):
    x, names = sp.Symbol(desc['variable'], real=True), names_of(desc)
    rows = [(r['source_ref'], None, *_equation(r['ast'], names, x)) for r in desc['value_equations']]
    for identity, t in instances(desc):
        rows.append((identity['source_ref'], t, *_equation(_replace(identity['ast'], ARGUMENT, _literal(t)), names, x)))
    return rows


def _system(desc):
    """Reduce the equations and target to unknown representative values."""
    x, names = sp.Symbol(desc['variable'], real=True), names_of(desc)
    rows = _rows(desc)
    terms, constant = linear(desc['target_ast'], names, x)
    chosen, routed = {}, {}
    # Equations name the representatives first, so the target is rewritten towards what is given.
    for key in [k for *_, t, _ in rows for k in t] + list(terms):
        routed.setdefault(key, _route(key, desc, chosen))
    keys = list(dict.fromkeys((r['function'], r['image']) for r in routed.values() if r['route'] == 'unknown'))

    def reduce(t, b):
        vector = [sp.S.Zero] * len(keys)
        for key, k in t.items():
            r = routed[key]
            if r['route'] == 'unknown':
                vector[keys.index((r['function'], r['image']))] += k * r['factor']
            else:
                b -= k * r['value']
        return vector, b

    equations = []
    for source_ref, at, t, b in rows:
        vector, rhs = reduce(t, b)
        equations.append({'source_ref': source_ref, 'instance': at, 'coefficients': vector,
                          'constant': sp.nsimplify(rhs)})
    target, rest = reduce(terms, sp.S.Zero)
    calls = [{**routed[key], 'coefficient': k} for key, k in terms.items()]
    return [list(k) for k in keys], equations, target, -rest + constant, calls


def _solve_linear(rows, columns, rhs):
    """A particular solution of rows·z = rhs, or None; free parameters are set to 0."""
    if columns == 0:
        return [] if all(v == 0 for v in rhs) else None
    if not rows:
        return [sp.S.Zero] * columns
    try:
        solution, params = sp.Matrix(rows).gauss_jordan_solve(sp.Matrix(rhs))
    except ValueError:
        return None
    return list(solution.subs({p: 0 for p in params}))


def _identity(source_ref, relation, variable_node, domain_ast):
    return {'source_ref': source_ref, 'ast': _replace(deepcopy(relation), variable_node, ARGUMENT),
            'domain_ast': deepcopy(domain_ast)}


def describe(goal, goal_ast, target_ref, entries, *, candidate=None):
    """Bind parity facts, an optional local rule or identity, and value equations to a numeric value target.

    Returns None when the target has no call of a parity function, or its inputs name anything
    but one scalar parameter of a stated domain; such targets keep their own route.
    A parameter input is fixed later by the borrowed domain-parameter subtask, never here.
    """
    facts = [r for r in entries if r['ast'][0] == 'function_parity']
    if goal.get('kind') != 'find_value' or not facts:
        return None
    target = target_ast(goal_ast)
    names = {r['ast'][1][1].rsplit(':', 1)[-1] for r in facts}
    calls = _function_calls(target)
    if not calls or not any(c[1][0] == 'ref' and c[1][1].rsplit(':', 1)[-1] in names for c in calls):
        return None
    inputs = {(node[1].rsplit(':', 1)[-1], node[2]) for c in calls for node in _refs(c[2])}
    parameter = None
    if inputs:
        # A goal that declares its own function scopes its names; the parameter is the stated domain's scalar.
        domains = [node for r in entries if r['ast'][0] == '=' and r['ast'][1][:2] == ['call', 'Dom']
                   for node in _refs(r['ast'][2]) if (node[1].rsplit(':', 1)[-1], node[2]) in inputs]
        if len(inputs) != 1 or next(iter(inputs))[1] != 'scalar' or len({node[1] for node in domains}) != 1:
            return None
        parameter = domains[0]
    desc = {'source': deepcopy(goal), 'target_ref': target_ref, 'structure_version': VERSION,
            'source_refs': [target_ref, *[r['source_ref'] for r in entries]],
            'given_entries': [{k: deepcopy(r[k]) for k in ('source_ref', 'expression', 'ast')} for r in entries],
            'structure_supported': False, 'reason': ''}
    try:
        if candidate is not None:
            scope = candidate['root']
            for segment in [*target_ref.strip('/').split('/')[1:-2], None]:
                if isinstance(scope, dict) and scope.get('uncertainties'):
                    raise ValueError('symmetry_value.unresolved_source')
                if segment is not None:
                    scope = scope[int(segment)] if isinstance(scope, list) else scope[segment]
        for row in entries:
            base._budget(row['ast'])
        base._budget(target)
        functions = []
        for row in facts:
            ref, prop = row['ast'][1][1], row['ast'][2]
            if prop not in SIGNS:
                raise ValueError('symmetry_value.property_unsupported')
            if any(F['name'] == ref.rsplit(':', 1)[-1] for F in functions):
                raise ValueError('symmetry_value.single_parity_fact_required')
            functions.append({'name': ref.rsplit(':', 1)[-1], 'ref': ref, 'property': prop,
                              'parity_source_ref': row['source_ref']})
        if len(functions) > LIMITS['functions']:
            raise ValueError('symmetry_value.budget')
        order = [c[1][1].rsplit(':', 1)[-1] for c in calls]
        functions.sort(key=lambda F: order.index(F['name']) if F['name'] in order else len(order))
        refs = {F['ref'] for F in functions}
        variable = goal.get('variable') or 'x'
        domain_rows, equations, identities = {}, [], []
        for row in entries:
            if row in facts:
                continue
            ast = row['ast']
            owner = next((side[2][1] for side in ast[1:3] if ast[0] == '=' and side[:2] == ['call', 'Dom']
                          and side[2][0] == 'ref' and side[2][1] in refs), None) if ast[0] == '=' else None
            if owner is not None:
                domain_rows.setdefault(owner, []).append((row, ast[2] if ast[1][0] == 'call' else ast[1]))
            elif ast[0] == 'quantifier' and ast[1] == '∀' and ast[4][0] == '=' and _function_calls(ast[4]):
                identities.append(_identity(row['source_ref'], ast[4], ['bound', ast[2]],
                                            within_domain_scope(ast[3], refs)))
            elif ast[0] == '=' and _function_calls(ast):
                scalars = {tuple(node) for node in _refs(ast) if node[2] == 'scalar'}
                # A printed relation in the function's argument is an identity
                # on its domain. Numeric point equations keep their own route;
                # additional parameters are never silently quantified.
                if (len(scalars) == 1 and next(iter(scalars))[1].rsplit(':', 1)[-1] == variable
                        and (parameter is None or next(iter(scalars))[1] != parameter[1])):
                    identities.append(_identity(row['source_ref'], ast, list(next(iter(scalars))), None))
                else:
                    equations.append({'source_ref': row['source_ref'], 'ast': deepcopy(ast)})
            else:
                raise ValueError('symmetry_value.additional_condition_unsupported')
        for i, ast in enumerate(goal_ast.get('additional_relations', [])):
            equations.append({'source_ref': f'{target_ref}/additional_relations/{i}', 'ast': deepcopy(ast)})
        if domain_rows and len(domain_rows) != len(functions):
            raise ValueError('symmetry_value.domain_per_function_unsupported')
        declared = [value for rows in domain_rows.values() for _, value in rows]
        if goal_ast.get('declared_domain') is not None:
            if len(functions) != 1:
                raise ValueError('symmetry_value.domain_per_function_unsupported')
            declared.append(goal_ast['declared_domain'])
        if (any(v != declared[0] for v in declared) if parameter is not None
                else any(region(v) != region(declared[0]) for v in declared)):
            raise ValueError('symmetry_value.one_declared_domain_required')
        rule_ast = None
        owner = goal.get('function') or functions[0]['name']
        if 'relation' in goal_ast:
            if 'function_type' in goal:
                raise ValueError('symmetry_value.additional_relation_unsupported')
            if goal_ast.get('relation_domain') is not None:
                rule_ast = local_rule(goal, goal_ast, owner)
            else:
                identities.append(_identity(f'{target_ref}/relation', goal_ast['relation'], goal_ast['target'][2], None))
        if owner not in [F['name'] for F in functions]:
            raise ValueError('symmetry_value.other_function')
        main = next(F for F in functions if F['name'] == owner)
        desc.update(functions=functions, function_ref=main['ref'], function=owner, variable=variable,
                    property=main['property'], parity_source_ref=main['parity_source_ref'],
                    rule_ast=rule_ast, relation_ast=deepcopy(goal_ast.get('relation')),
                    rule_domain_ast=deepcopy(goal_ast.get('relation_domain')),
                    domain_ast=deepcopy(declared[0]) if declared else None,
                    target_ast=deepcopy(target), value_equations=equations, identities=identities,
                    domain_source_refs=[r['source_ref'] for rows in domain_rows.values() for r, _ in rows] or
                                       ([target_ref] if declared else []), parameter=None)
        if parameter is not None:
            # The subtask reads the domain and parity facts; the parent keeps the rule and the target.
            if len(functions) != 1 or not domain_rows:
                raise ValueError('symmetry_value.parameter_single_function_required')
            name = parameter[1].rsplit(':', 1)[-1]
            outside = [desc['rule_ast'], desc['rule_domain_ast'], [r['ast'] for r in desc['value_equations']],
                       [r['ast'] for r in identities]]
            if any(node[1].rsplit(':', 1)[-1] == name and node[2] == 'scalar' for part in outside for node in _refs(part)):
                raise ValueError('symmetry_value.parameter_outside_domain_and_target')
            borrowed = {*desc['domain_source_refs'], functions[0]['parity_source_ref']}
            desc['parameter'] = {'ref': parameter[1], 'name': parameter[1].rsplit(':', 1)[-1],
                                 'source_refs': [r['source_ref'] for r in entries if r['source_ref'] in borrowed]}
        else:
            _check(desc)
        if candidate is not None:
            from .stage_two.fragments import _scope_ranges
            from .stage_two.symmetry_value_surface import source_spans
            if source_spans(candidate, target_ref, _scope_ranges(candidate, target_ref), desc) is None:
                raise ValueError('symmetry_value.source_not_bound')
        desc['structure_supported'] = True
    except (ValueError, TypeError, KeyError, IndexError, NotImplementedError) as exc:
        desc['reason'] = str(exc)
    return desc


def _check(desc):
    domain = domain_of(desc)
    if domain == sp.S.EmptySet or reflect(domain) != domain:
        raise ValueError('symmetry_value.domain_not_symmetric')
    _check_rule(desc)
    x, names = sp.Symbol(desc['variable'], real=True), names_of(desc)
    for identity in desc['identities']:
        applies = identity_range(desc, identity)
        if applies == sp.S.EmptySet:
            raise ValueError('symmetry_value.identity_range_empty')
        _form, h = identity_form(identity['ast'], names, x)
        if undefined_on(identity['ast'], h, x, applies):
            raise ValueError('symmetry_value.identity_undefined_on_range')
    if not globally_consistent(desc):
        raise ValueError('symmetry_value.conditions_inconsistent')
    inputs = []
    for ast in [desc['target_ast'], *(r['ast'] for r in desc['value_equations'])]:
        inputs.extend(_constant(call[2], x) for call in _function_calls(ast))
    if (len(inputs) > LIMITS['calls']
            or len(desc['value_equations']) + len(instances(desc)) > LIMITS['conditions']):
        raise ValueError('symmetry_value.budget')
    if any(domain.contains(c) is not sp.true for c in inputs):
        raise ValueError('symmetry_value.input_outside_domain')
    keys, equations, _, _, _ = _system(desc)
    if len(keys) > LIMITS['unknowns']:
        raise ValueError('symmetry_value.budget')
    if _solve_linear([e['coefficients'] for e in equations], len(keys), [e['constant'] for e in equations]) is None:
        raise ValueError('symmetry_value.conditions_inconsistent')


def instantiate(desc, value):
    """The statement with the parameter replaced by one returned value; checked like any numeric statement."""
    name, literal = desc['parameter']['name'], _literal(sp.Rational(value))

    def put(ast):
        if not isinstance(ast, list):
            return ast
        if ast[:1] == ['ref'] and ast[2] == 'scalar' and ast[1].rsplit(':', 1)[-1] == name:
            return deepcopy(literal)
        return [put(v) for v in ast]

    out = deepcopy(desc)
    out['target_ast'], out['domain_ast'] = put(out['target_ast']), put(out['domain_ast'])
    out['parameter'] = None
    return out


def _candidates(desc, borrowed):
    values = borrowed['parameter_set']
    if not isinstance(values, sp.FiniteSet):
        raise ValueError('symmetry_value.parameter_family_unsupported')  # noqa: TRY004 - mathematical capability gap
    if values == sp.S.EmptySet:
        raise ValueError('symmetry_value.conditions_inconsistent')
    if any(not v.is_Rational for v in values):
        raise ValueError('symmetry_value.rational_input_required')
    return sorted(values)


def _solve_borrowed(desc, borrowed):
    """Each returned parameter value is instantiated and solved; one shared value or an honest gap."""
    candidates = []
    for value in _candidates(desc, borrowed):
        instance = instantiate(desc, value)
        if borrowed['instantiated_domain'] is not None and region(instance['domain_ast']) != borrowed['instantiated_domain']:
            raise ValueError('symmetry_value.instantiated_domain_mismatch')
        _check(instance)
        candidates.append({'parameter_value': value, 'model': solve(instance)})
    models = [row['model'] for row in candidates]
    if any(m['status'] != 'determined' for m in models) or len({m['value'] for m in models}) != 1:
        raise ValueError('symmetry_value.parameter_candidates_disagree')
    return {**models[0], 'borrow': {'output': deepcopy(borrowed), 'candidates': candidates}}


def solve(desc):
    if not desc.get('structure_supported'):
        raise ValueError(desc.get('reason') or 'symmetry_value.unsupported')
    if desc.get('parameter'):
        if not desc.get('borrowed'):
            raise ValueError('symmetry_value.parameter_requires_borrow')
        return _solve_borrowed({k: v for k, v in desc.items() if k != 'borrowed'}, desc['borrowed'])
    keys, equations, target, constant, calls = _system(desc)
    rows = [e['coefficients'] for e in equations]
    rhs = [e['constant'] for e in equations]
    witness = _solve_linear(rows, len(keys), rhs)
    if keys:
        multipliers = _solve_linear(sp.Matrix(rows).T.tolist() if rows else [], len(rows), target)
    else:
        multipliers = [sp.S.Zero] * len(rows)
    witnesses, value = [witness], None
    if multipliers is not None:
        value = sp.nsimplify(sum((m * b for m, b in zip(multipliers, rhs)), sp.S.Zero) + constant)
    else:
        null = sp.Matrix(rows).nullspace() if rows else [sp.eye(len(keys))[:, i] for i in range(len(keys))]
        step = next(v for v in null if sum(t * n for t, n in zip(target, v)) != 0)
        witnesses.append([w + n for w, n in zip(witness, step)])
    rule, known = rule_of(desc)
    return {'version': VERSION, 'description': deepcopy(desc), 'variable': sp.Symbol(desc['variable'], real=True),
            'signs': signs(desc), 'rule': rule, 'rule_domain': known, 'calls': calls, 'keys': keys,
            'equations': equations, 'target_coefficients': target, 'target_constant': constant,
            'multipliers': multipliers, 'witnesses': witnesses, 'value': value,
            'status': 'determined' if value is not None else 'insufficient_information', 'borrow': None}


def _verify_borrowed(desc, model):
    """The returned subtask belongs to this target and facts, and every candidate gives the same value.

    The caller still binds the subtask to the frozen context with `verify_borrowed_parameter`.
    """
    borrow = model['borrow']
    output, parameter = borrow['output'], desc['parameter']
    if (output['status'] != 'verified_subtask' or output['parent_target_pending'] is not True
            or output['parent_target_ref'] != desc['target_ref'] or output['parameter_ref'] != parameter['ref']
            or output['processed_source_refs'] != parameter['source_refs']
            or set(output['remaining_source_refs']) != set(desc['source_refs'][1:]) - set(parameter['source_refs'])
            or output['parameter_set'] != output['proof']['feasible_set']
            or not base.verify(output['proof']['description'], output['proof'])):
        return False
    values = _candidates(desc, output)
    if [row['parameter_value'] for row in borrow['candidates']] != values:
        return False
    for row in borrow['candidates']:
        instance = instantiate(desc, row['parameter_value'])
        if output['instantiated_domain'] is not None and base._region(instance['domain_ast']) != output['instantiated_domain']:
            return False
        if row['model']['status'] != 'determined' or not verify(instance, row['model']):
            return False
    if len({row['model']['value'] for row in borrow['candidates']}) != 1:
        return False
    first = borrow['candidates'][0]['model']
    return all(model[k] == first[k] for k in MODEL_KEYS - {'borrow'})


def verify(desc, model):
    """Independent check from the original syntax: every rewrite, substitution, instance and the certificate."""
    try:
        if 'borrowed' in desc:
            if model.get('borrow') is None or desc['borrowed'] != model['borrow']['output']:
                return False
            desc = {k: v for k, v in desc.items() if k != 'borrowed'}
        if desc.get('parameter'):
            return (bool(desc.get('structure_supported')) and set(model) == MODEL_KEYS
                    and model['borrow'] is not None and _verify_borrowed(desc, model))
        if not desc.get('structure_supported') or model.get('description') != desc or model.get('borrow') is not None:
            return False
        if set(model) != MODEL_KEYS or model['version'] != VERSION:
            return False
        x = sp.Symbol(desc['variable'], real=True)
        names = [F['name'] for F in desc['functions']]
        sign_of = {F['name']: SIGNS[F['property']] for F in desc['functions']}
        domain = sp.S.Reals if desc['domain_ast'] is None else region(desc['domain_ast'])
        rule = None if desc['rule_ast'] is None else rule_expression(desc['rule_ast'], x)
        known = sp.S.EmptySet if rule is None else domain & region(desc['rule_domain_ast'])
        if model['variable'] != x or model['signs'] != sign_of or model['rule_domain'] != known:
            return False
        if (rule is None) != (model['rule'] is None) or (rule is not None and sp.simplify(model['rule'] - rule) != 0):
            return False
        if rule is not None and undefined_on(desc['rule_ast'], rule, x, known):
            return False
        t = sp.Symbol('t', real=True)
        if sp.imageset(sp.Lambda(t, -t), domain) != domain:
            return False
        if not globally_consistent(desc):
            return False
        keys = [tuple(k) for k in model['keys']]
        if len(set(keys)) != len(keys) or any(name not in names for name, _ in keys):
            return False

        def value_of(name, c):
            """F(c) as (constant, None) or (factor, key); each step checked against F's parity."""
            if domain.contains(c) is not sp.true:
                raise ValueError
            sign = sign_of[name]
            if (c == 0 and sign == -1) or any(F['name'] == name and F['property'] == 'both' for F in desc['functions']):
                return sp.S.Zero, None
            if rule is not None and name == desc['function']:
                if known.contains(c) is sp.true:
                    return rule.subs(x, c), None
                if known.contains(-c) is sp.true:
                    return sign * rule.subs(x, -c), None
            matches = [k for k in keys if k[0] == name and k[1] in (c, -c)]
            if len(matches) != 1 or (matches[0][1] == 0 and sign == -1):
                raise ValueError
            return (1 if matches[0][1] == c else sign), matches[0]

        def reduce(terms, b):
            vector = [sp.S.Zero] * len(keys)
            for (name, c), k in terms.items():
                a, key = value_of(name, c)
                if key is None:
                    b -= k * a
                else:
                    vector[keys.index(key)] += k * a
            return vector, b

        def same(u, v):
            return len(u) == len(v) and all(sp.simplify(a - b) == 0 for a, b in zip(u, v))

        # Rebuild every equation: given value relations, then each identity at each needed input and its opposite.
        given = [(r['source_ref'], None, r['ast']) for r in desc['value_equations']]
        inputs = []
        for _, _, ast in given:
            inputs += [c for (_, c) in _equation(ast, names, x)[0]]
        target_terms, d = linear(desc['target_ast'], names, x)
        inputs += [c for (_, c) in target_terms]
        needed = list(dict.fromkeys(s for c in inputs for s in (c, -c)))
        for identity in desc['identities']:
            applies = domain if identity['domain_ast'] is None else domain & region(identity['domain_ast'])
            _form, h = identity_form(identity['ast'], names, x)
            if applies == sp.S.EmptySet or undefined_on(identity['ast'], h, x, applies):
                return False
            for s in needed:
                if applies.contains(s) is sp.true:
                    instance = _replace(identity['ast'], ARGUMENT, _literal(s))
                    given.append((identity['source_ref'], s, instance))
        if len(model['equations']) != len(given):
            return False
        rows, rhs = [], []
        for row, (source_ref, at, ast) in zip(model['equations'], given):
            terms, b = _equation(ast, names, x)
            vector, b = reduce(terms, b)
            if (row['source_ref'] != source_ref or row['instance'] != at or not same(row['coefficients'], vector)
                    or sp.simplify(row['constant'] - b) != 0):
                return False
            rows.append(vector)
            rhs.append(b)
        target, rest = reduce(target_terms, sp.S.Zero)
        constant = d - rest
        if not same(model['target_coefficients'], target) or sp.simplify(model['target_constant'] - constant) != 0:
            return False
        for call in model['calls']:
            key = (call['function'], call['input'])
            a, image = value_of(*key)
            if call['coefficient'] != target_terms.get(key):
                return False
            if image is None and (call['route'] == 'unknown' or sp.simplify(call['value'] - a) != 0):
                return False
            if image is not None and (call['route'] != 'unknown' or call['image'] != image[1] or call['factor'] != a):
                return False
        if {(c['function'], c['input']) for c in model['calls']} != set(target_terms):
            return False
        # Every witness meets all equations; the rest of each function extends by the consistency test above.
        for w in model['witnesses']:
            if len(w) != len(keys) or any(sp.simplify(sum((a * z for a, z in zip(r, w)), sp.S.Zero) - b) != 0
                                          for r, b in zip(rows, rhs)):
                return False
        if not model['witnesses']:
            return False
        evaluate = lambda w: sp.simplify(sum((a * z for a, z in zip(target, w)), sp.S.Zero) + constant)
        if model['status'] == 'determined':
            m = model['multipliers']
            if m is None or len(model['witnesses']) != 1 or len(m) != len(rows):
                return False
            combined = [sum((mi * r[j] for mi, r in zip(m, rows)), sp.S.Zero) for j in range(len(keys))]
            value = sum((mi * b for mi, b in zip(m, rhs)), sp.S.Zero) + constant
            return (same(combined, target) and sp.simplify(model['value'] - value) == 0
                    and sp.simplify(evaluate(model['witnesses'][0]) - value) == 0)
        if model['status'] != 'insufficient_information' or model['value'] is not None or model['multipliers'] is not None:
            return False
        first, second = model['witnesses'] if len(model['witnesses']) == 2 else (None, None)
        return first is not None and sp.simplify(evaluate(first) - evaluate(second)) != 0
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, NotImplementedError):
        return False
