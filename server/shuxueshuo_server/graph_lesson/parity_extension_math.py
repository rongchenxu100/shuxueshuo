"""FP-T3 R1: extend a local rule and given point values by a parity fact.

The interval rule is read inside the declared domain D: it carries values on
I = D ∩ (its printed range). Given point values f(c)=v are single-point rules.
Parity then determines the mirrors, and an odd function takes 0 at 0 ∈ D.
Overlaps and zero use the shared compatibility rules. Requested inputs that
stay free are reported as such (a rule family), never filled in.
"""
from copy import deepcopy

import sympy as sp

from . import function_cells
from . import parity_compatibility as compatibility
from . import parity_parameter_math as base

VERSION = 'parity-extension/r1-v3'
LIMITS = {'nodes': 256, 'depth': 24, 'bits': 128, 'degree': 4, 'radicals': 2, 'denominators': 2, 'points': 6}
SIGNS = {'even': 1, 'odd': -1, 'both': 1}
ARGUMENT = ['bound', 'function_argument']
_DUMMY = sp.Symbol('_unused_parameter', real=True)
MODEL_KEYS = {'version', 'description', 'variable', 'rule', 'domain', 'rule_domain', 'requested_domain',
              'mirrored_domain', 'mapped_domain', 'sign', 'substituted', 'expression', 'zero_status',
              'branches', 'answer_expression', 'determined_domain', 'free_domain', 'domain_identity', 'status'}


def _replace(ast, before, after):
    if ast == before:
        return deepcopy(after)
    return [_replace(v, before, after) if isinstance(v, list) else v for v in ast]


def _has_radical(ast):
    return isinstance(ast, list) and (ast[:2] == ['call', 'sqrt'] or any(_has_radical(v) for v in ast[1:]))


def _has_special(ast):
    return isinstance(ast, list) and (ast[:2] in (['call', 'sqrt'], ['call', 'abs'])
                                     or any(_has_special(v) for v in ast[1:]))


def property_signs(prop):
    return [1, -1] if prop == 'both' else [SIGNS[prop]]


def source_radicands(ast, x):
    """Read guards before SymPy can cancel roots or turn their product into a polynomial."""
    if not isinstance(ast, list):
        return []
    own = [rule_polynomial(ast[2], x)] if ast[:2] == ['call', 'sqrt'] else []
    return own + [r for child in ast[1:] for r in source_radicands(child, x)]


def rule_polynomial(ast, x):
    """Exact polynomial of the original rule body; no cancellation of denominators."""
    expr = base.polynomial(ast, x, _DUMMY, None, maximum=LIMITS['degree'])
    poly = sp.Poly(expr, x)
    if poly.degree() > LIMITS['degree'] or not all(c.is_Rational for c in poly.all_coeffs()):
        raise ValueError('parity_ext.polynomial_budget')
    return sp.expand(expr)


def _polynomial_denominator(exc):
    return 'constant_denominator_required' in str(exc)


def rule_denominators(ast, x):
    """Every non-constant printed denominator, read before any cancellation."""
    if not isinstance(ast, list):
        return []
    found = [d for child in ast[1:] for d in rule_denominators(child, x)]
    if ast[0] == '/' and len(ast) == 3 and not _has_radical(ast[2]):
        d = rule_polynomial(ast[2], x)
        if d.free_symbols:
            found.append(d)
    if len(found) > LIMITS['denominators']:
        raise ValueError('parity_ext.denominator_budget')
    return found


def undefined_on(ast, expr, x, s):
    """Whether the printed rule fails somewhere on s: a negative radicand or a zero printed denominator."""
    if any(sp.solveset(r < 0, x, s) != sp.S.EmptySet for r in source_radicands(ast, x)):
        return True
    return any(sp.solveset(sp.Eq(d, 0), x, s) != sp.S.EmptySet for d in rule_denominators(ast, x))


def rule_expression(ast, x):
    """A polynomial, or polynomial pieces combined by +, −, ×, ÷ (at most two polynomial denominators)
    with at most two square roots of polynomials. Denominators are kept as printed, never cancelled here."""
    if not _has_special(ast):
        try:
            return rule_polynomial(ast, x)
        except ValueError as exc:
            if not _polynomial_denominator(exc):
                raise
    count = [0]
    rule_denominators(ast, x)

    def read(node):
        if not _has_special(node):
            try:
                return rule_polynomial(node, x)
            except ValueError as exc:
                if not _polynomial_denominator(exc):
                    raise
        op = node[0]
        if node[:2] == ['call', 'sqrt'] and len(node) == 3 and not _has_special(node[2]):
            count[0] += 1
            return sp.sqrt(rule_polynomial(node[2], x))
        if node[:2] == ['call', 'abs'] and len(node) == 3 and not _has_special(node[2]):
            value = rule_polynomial(node[2], x)
            if sp.Poly(value, x).degree() > 2:
                raise ValueError('parity_ext.absolute_value_budget')
            return sp.Abs(value)
        if op == 'neg':
            return -read(node[1])
        if op in ('+', '-', '*'):
            a, b = read(node[1]), read(node[2])
            return {'+': a + b, '-': a - b, '*': a * b}[op]
        if op == '/' and not _has_radical(node[2]):
            d = rule_polynomial(node[2], x)
            if d == 0:
                raise ValueError('parity_ext.zero_denominator')
            return sp.Mul(read(node[1]), sp.Pow(d, -1, evaluate=False), evaluate=False) if d.free_symbols \
                else read(node[1]) / d
        raise ValueError('parity_ext.rule_form_unsupported')

    expr = read(ast)
    if count[0] > LIMITS['radicals']:
        raise ValueError('parity_ext.radical_budget')
    return expr


def radicands(expr):
    return [p.base for p in expr.atoms(sp.Pow) if p.exp == sp.S.Half]


def _constant(ast, x):
    value = rule_expression(ast, x)
    if value.free_symbols or not value.is_real or undefined_on(ast, value, x, sp.S.Reals):
        raise ValueError('parity_ext.point_value_not_constant')
    return value


def _legal(ast):
    """A printed interval needs left < right; it is never read as empty or a point."""
    if ast[0] == 'interval' and not function_cells.input_set(ast).measure > 0:
        raise ValueError('parity_ext.invalid_interval')
    for child in ast[1:]:
        if isinstance(child, list) and child and isinstance(child[0], str):
            _legal(child)


def region(ast):
    _legal(ast)
    return function_cells.input_set(ast)


def reflect(value):
    if isinstance(value, sp.Interval):
        return sp.Interval(-value.end, -value.start, value.right_open, value.left_open)
    t = sp.Symbol('t', real=True)
    return sp.imageset(sp.Lambda(t, -t), value)


def within_domain_scope(ast, function_refs):
    """Remove redundant Dom(F) intersections; every local rule is already read inside D.

    Only intersections are normalized. A domain in a union, complement or a
    different function's scope must retain its meaning and cannot become ℝ.
    The original quantified fact remains in given_entries for verification.
    """
    if (ast[:2] == ['call', 'Dom'] and len(ast) == 3
            and ast[2][:1] == ['ref'] and ast[2][1] in function_refs):
        return ['real']
    if ast[0] == '∩':
        a, b = (within_domain_scope(part, function_refs) for part in ast[1:])
        return b if a == ['real'] else a if b == ['real'] else ['∩', a, b]
    return deepcopy(ast)


def symbols(desc):
    return sp.Symbol(desc['variable'], real=True)


def points(desc):
    """Given point values {c: v}; a repeated point must repeat its value."""
    x, values = symbols(desc), {}
    for row in desc['point_rules']:
        c, v = _constant(row['argument_ast'], x), _constant(row['value_ast'], x)
        function_cells.exact_point(c)
        if c in values and sp.simplify(values[c] - v) != 0:
            raise ValueError('parity_ext.overlap_conflict')
        values[c] = v
    return values


def rule_rows(desc):
    rows = desc.get('local_rules') or [{'rule_ast': desc['rule_ast'], 'domain_ast': desc['rule_domain_ast'],
                                      'source_ref': desc['target_ref'] + '/relation'}]
    unique = []
    for row in rows:
        same = next((r for r in unique if r['rule_ast'] == row['rule_ast']
                     and r['domain_ast'] == row['domain_ast']), None)
        if same is None:
            unique.append({**row, 'source_refs': [row['source_ref']]})
        else:
            same['source_refs'].append(row['source_ref'])
    return unique


def rules(desc):
    x = symbols(desc)
    domain = sp.S.Reals if desc['domain_ast'] is None else region(desc['domain_ast'])
    return [(domain & region(row['domain_ast']), rule_expression(row['rule_ast'], x), row['rule_ast'])
            for row in rule_rows(desc)]


def combined_rule(desc):
    """The known rule, with each original range retained; overlap is checked before this is used."""
    rows, x = rules(desc), symbols(desc)
    known = sp.Union(*(s for s, _, _ in rows))
    if len(rows) == 1:
        return rows[0][1], known
    return sp.Piecewise(*((e, s.as_relational(x)) for s, e, _ in rows)), known


def rule_boundaries(desc):
    return {p for s, _, _ in rules(desc) for p in s.boundary if p.is_finite}


def on_region(expr, s):
    if isinstance(expr, sp.Piecewise):
        rest = s
        for value, condition in expr.args:
            here = rest if condition is sp.true else rest & condition.as_set()
            if here == s:
                return value
            rest -= here
    return expr


def ranges(desc):
    """D, I = D ∩ printed rule range, the requested J, and J's part mirrored from I.

    Without a printed domain, D stays the abstract symmetric domain required by
    the parity fact. Sets are then computed on ℝ and every one is read as "∩ D".
    """
    domain = sp.S.Reals if desc['domain_ast'] is None else region(desc['domain_ast'])
    _, known = combined_rule(desc)
    requested = domain if desc['requested_domain_ast'] is None else region(desc['requested_domain_ast'])
    given = known | sp.FiniteSet(*points(desc))
    return domain, known, requested, (requested & reflect(known)) - given


def _value_at(t, x, rule, known, values):
    found = ([rule.subs(x, t)] if known.contains(t) is sp.true else []) + ([values[t]] if t in values else [])
    if any(sp.simplify(v - found[0]) != 0 for v in found[1:]):
        raise ValueError('parity_ext.overlap_conflict')
    return found[0] if found else None


def atoms(desc):
    domain, known, requested, _ = ranges(desc)
    keys = list(points(desc))
    given = known | sp.FiniteSet(*keys)
    bounds = rule_boundaries(desc)
    return [a for a in compatibility.fixed_atoms(domain, given, property_signs(desc['property']),
                                                 cuts=[*requested.boundary, *keys, *(-c for c in keys),
                                                       *bounds, *(-p for p in bounds)])
            if a['set'].is_subset(requested)]


def _check(desc):
    domain, known, requested, mirrored = ranges(desc)
    if domain == sp.S.EmptySet or reflect(domain) != domain:
        raise ValueError('parity_ext.domain_not_symmetric')
    if known == sp.S.EmptySet:
        raise ValueError('parity_ext.rule_outside_domain')
    if requested == sp.S.EmptySet or not requested.is_subset(domain):
        raise ValueError('parity_ext.requested_outside_domain')
    x = symbols(desc)
    rule, _ = combined_rule(desc)
    values, signs = points(desc), property_signs(desc['property'])
    if len(values) > LIMITS['points']:
        raise ValueError('parity_ext.point_budget')
    if any(domain.contains(c) is not sp.true for c in values):
        raise ValueError('parity_ext.point_outside_domain')
    rows = rules(desc)
    if len(rows) > 6:
        raise ValueError('parity_ext.rule_budget')
    for i, (s, expr, ast) in enumerate(rows):
        if s == sp.S.EmptySet:
            raise ValueError('parity_ext.rule_outside_domain')
        if undefined_on(ast, expr, x, s):
            raise ValueError('parity_ext.rule_undefined_on_range')
        if any(not _agree(expr, other, s & t, x) for t, other, _ in rows[:i]):
            raise ValueError('parity_ext.overlap_conflict')
    if mirrored == sp.S.EmptySet and desc['property'] != 'both':
        raise ValueError('parity_ext.requested_range_not_mirrored')
    given = known | sp.FiniteSet(*values)
    keys = list(values)
    bounds = rule_boundaries(desc)
    for atom in compatibility.fixed_atoms(domain, given, signs,
                                          cuts=[*keys, *(-c for c in keys), *bounds, *(-p for p in bounds)]):
        if not compatibility.constrained(signs, atom['role']):
            continue
        if atom['kind'] == 'open':
            residual = compatibility.pair_residual(rule, rule.subs(x, -x, simultaneous=True), signs)
            ok = _agree(residual, sp.S.Zero, atom['set'], x)
        else:
            t = atom['representative']
            here = _value_at(t, x, rule, known, values)
            mirror = _value_at(-t, x, rule, known, values)
            ok = sp.simplify(compatibility.pair_residual(here, sp.S.Zero if mirror is None else mirror, signs)) == 0
        if not ok:
            raise ValueError('parity_ext.overlap_conflict')
    for c in values:
        _value_at(c, x, rule, known, values)
    if all(a['role'] == 'free' for a in atoms(desc)):
        raise ValueError('parity_ext.requested_value_free')


def _point_rows(rows, name, function_ref=None):
    found = []
    for source_ref, ast in rows:
        if ast[0] != '=':
            return None
        call, value = (ast[1], ast[2]) if ast[1][:1] == ['function_call'] else (ast[2], ast[1])
        fn = call[1] if call[:1] == ['function_call'] else None
        if (fn is None or fn[0] != 'ref' or fn[1].rsplit(':', 1)[-1] != name
                or (function_ref is not None and fn[1] != function_ref)
                or 'ref' in str(call[2]) or 'ref' in str(value) or 'bound' in str(call[2]) + str(value)):
            return None
        found.append({'argument_ast': deepcopy(call[2]), 'value_ast': deepcopy(value), 'source_ref': source_ref})
    return found


def local_rule(goal, goal_ast, name):
    """The printed f(x)=p(x) with its range, as p over the bound function argument."""
    if goal_ast.get('relation_domain') is None:
        raise ValueError('parity_ext.rule_range_required')
    relation = goal_ast['relation']
    if relation[0] != '=':
        raise ValueError('parity_ext.rule_equation_required')
    calls = [side for side in relation[1:] if side[:1] == ['function_call']]
    if len(calls) != 1:
        raise ValueError('parity_ext.single_rule_call_required')
    call, = calls
    body = relation[2] if relation[1] is call else relation[1]
    fn, argument = call[1], call[2]
    if (fn[0] != 'ref' or fn[1].rsplit(':', 1)[-1] != name or argument[:1] != ['ref']
            or argument[-1] != 'scalar' or argument[1].rsplit(':', 1)[-1] != goal.get('variable')):
        raise ValueError('parity_ext.rule_must_use_function_argument')
    rule_ast = _replace(body, argument, ARGUMENT)
    rule_expression(rule_ast, sp.Symbol(goal['variable'], real=True))
    return rule_ast


def quantified_rule(ast, source_ref, function_ref):
    """A local rule is an ordinary quantified equality, using the existing notation contract."""
    if ast[0] != 'quantifier' or ast[1] != '∀' or ast[4][0] != '=':
        return None
    relation = ast[4]
    call = ['function_call', ['ref', function_ref, 'function'], ['bound', ast[2]]]
    if call not in relation[1:]:
        return None
    body = relation[2] if relation[1] == call else relation[1]
    rule = _replace(body, ['bound', ast[2]], ARGUMENT)
    return {'rule_ast': rule, 'domain_ast': within_domain_scope(ast[3], {function_ref}), 'source_ref': source_ref}


def _parity_identity(ast, function_ref, variable, prop):
    """An exact restatement of the bound parity premise adds no new condition."""
    refs = [n for n in function_cells.walk(ast) if n[0] == 'ref' and n[-1] == 'scalar']
    if not refs or any(n[1].rsplit(':', 1)[-1] != variable or n != refs[0] for n in refs):
        return False
    functions = [n for n in function_cells.walk(ast) if n[0] == 'ref' and n[-1] == 'function']
    if not functions or any(n[1].rsplit(':', 1)[-1] != function_ref.rsplit(':', 1)[-1]
                            or n != functions[0] for n in functions):
        return False
    # Formula goal fields have their own lexical scope, as does local_rule().
    call = ['function_call', functions[0], refs[0]]
    reflected = ['function_call', call[1], ['neg', refs[0]]]
    for sign in property_signs(prop):
        value = call if sign == 1 else ['neg', call]
        if ast in (['=', reflected, value], ['=', value, reflected]):
            return True
    return False


def describe(goal, goal_ast, target_ref, entries, *, candidate=None):
    """Bind a parity fact and local rules to a requested-range formula target.

    Returns None when this is not a parity extension target, so ordinary
    function-formula routes keep their own contracts.
    """
    facts = [r for r in entries if r['ast'][0] == 'function_parity']
    if goal.get('kind') != 'find_function_formula' or not facts:
        return None
    name = goal.get('function')
    if not any(r['ast'][1][1].rsplit(':', 1)[-1] == name for r in facts):
        return None
    desc = {'source': deepcopy(goal), 'target_ref': target_ref, 'structure_version': VERSION,
            'source_refs': [target_ref, *[r['source_ref'] for r in entries]],
            'given_entries': [{k: deepcopy(r[k]) for k in ('source_ref', 'expression', 'ast')} for r in entries],
            'structure_supported': False, 'reason': ''}
    try:
        if candidate is not None:
            scope = candidate['root']
            for segment in [*target_ref.strip('/').split('/')[1:-2], None]:
                if isinstance(scope, dict) and scope.get('uncertainties'):
                    raise ValueError('parity_ext.unresolved_source')
                if segment is not None:
                    scope = scope[int(segment)] if isinstance(scope, list) else scope[segment]
        for row in entries:
            base._budget(row['ast'])
        if goal_ast.get('relation') is not None:
            base._budget(goal_ast['relation'])
        refs = {r['ast'][1][1] for r in facts}
        if len(refs) != 1 or len(facts) != 1:
            raise ValueError('parity_ext.single_parity_fact_required')
        function_ref, = refs
        prop = facts[0]['ast'][2]
        if prop not in SIGNS:
            raise ValueError('parity_ext.property_unsupported')
        sibling_refs = set()
        if candidate is not None:
            from .stage_two.parity_extension_surface import sibling_question_fact_refs
            sibling_refs = sibling_question_fact_refs(candidate, target_ref, entries,
                                                      {'function': name, 'variable': goal['variable']})
        domain_rows, point_rows, local_rows = [], [], []
        for row in entries:
            if row is facts[0] or row['source_ref'] in sibling_refs:
                continue
            ast = row['ast']
            if ast[0] == '=' and ['call', 'Dom', ['ref', function_ref, 'function']] in ast[1:]:
                domain_rows.append((row, ast[2] if ast[1][0] == 'call' else ast[1]))
            elif (local := quantified_rule(ast, row['source_ref'], function_ref)) is not None:
                local_rows.append(local)
            else:
                found = _point_rows([(row['source_ref'], ast)], name, function_ref)
                if found is None:
                    raise ValueError('parity_ext.additional_condition_unsupported')
                point_rows.extend(found)
        extra = _point_rows([(f'{target_ref}/additional_relations/{i}', ast)
                             for i, ast in enumerate(goal_ast.get('additional_relations', []))
                             if not _parity_identity(ast, function_ref, goal['variable'], prop)], name)
        if extra is None:
            raise ValueError('parity_ext.additional_relation_unsupported')
        point_rows.extend(extra)
        declared = [value for _, value in domain_rows]
        if goal_ast.get('declared_domain') is not None:
            declared.append(goal_ast['declared_domain'])
        if any(region(v) != region(declared[0]) for v in declared):
            raise ValueError('parity_ext.one_declared_domain_required')
        if 'function_type' in goal:
            raise ValueError('parity_ext.additional_relation_unsupported')
        if goal_ast.get('relation') is not None:
            rule_ast = local_rule(goal, goal_ast, name)
            relation = goal_ast['relation']
            rule_domain = goal_ast['relation_domain']
            primary = {'rule_ast': rule_ast, 'domain_ast': deepcopy(rule_domain),
                       'source_ref': target_ref + '/relation'}
            local_rows = [primary, *local_rows]
        elif local_rows:
            primary = local_rows[0]
            rule_ast, rule_domain = primary['rule_ast'], primary['domain_ast']
            relation = next(r['ast'][4] for r in entries if r['source_ref'] == primary['source_ref'])
        else:
            raise ValueError('parity_ext.rule_required')
        desc.update(function_ref=function_ref, function=name, variable=goal['variable'],
                    property=prop, rule_ast=rule_ast, relation_ast=deepcopy(relation),
                    rule_domain_ast=deepcopy(rule_domain),
                    requested_domain_ast=deepcopy(goal_ast.get('requested_domain')),
                    domain_ast=deepcopy(declared[0]) if declared else None, point_rules=point_rows,
                    parity_source_ref=facts[0]['source_ref'],
                    domain_source_refs=([r['source_ref'] for r, _ in domain_rows] or
                                        [target_ref if declared else facts[0]['source_ref']]))
        if len(local_rows) > 1 or goal_ast.get('relation') is None:
            desc['local_rules'] = local_rows
        if sibling_refs:
            desc['sibling_question_refs'] = sorted(sibling_refs)
        _check(desc)
        if candidate is not None:
            from .stage_two.fragments import _scope_ranges
            from .stage_two.parity_extension_surface import source_spans
            if source_spans(candidate, target_ref, _scope_ranges(candidate, target_ref), desc) is None:
                raise ValueError('parity_ext.source_not_bound')
        desc['structure_supported'] = True
    except (ValueError, TypeError, KeyError, IndexError, NotImplementedError) as exc:
        desc['reason'] = str(exc)
    return desc


def _zero_status(domain, given, prop):
    if 0 not in domain:
        return 'not_in_domain'
    if 0 in given:
        return 'known'
    return 'forced_zero' if prop in ('odd', 'both') else 'free'


def _merge(pieces, x):
    """Union pieces with one expression; a lone point joins a touching piece only if values agree."""
    groups = []
    for s, expr, origin in pieces:
        if isinstance(s, sp.FiniteSet):
            continue
        same = next((g for g in groups if sp.simplify(g['expression'] - expr) == 0), None)
        if same:
            same['set'], same['origins'] = same['set'] | s, sorted({*same['origins'], origin})
        else:
            groups.append({'set': s, 'expression': expr, 'origins': [origin]})
    for s, expr, origin in pieces:
        if not isinstance(s, sp.FiniteSet):
            continue
        point, = s
        touching = [g for g in groups if point in g['set'].closure
                    and sp.simplify(g['expression'].subs(x, point) - expr.subs(x, point)) == 0]
        # A point the printed rule covers stays with that rule's piece.
        same = next((g for g in touching if origin in g['origins']), touching[0] if touching else None)
        if same:
            same['set'], same['origins'] = same['set'] | s, sorted({*same['origins'], origin})
        else:
            groups.append({'set': s, 'expression': expr, 'origins': [origin]})
    return sorted(groups, key=lambda g: (g['set'].inf, g['set'].sup))


def _answer_expression(branches, rule, x, prop):
    if len(branches) == 1:
        return branches[0]['expression']
    if prop == 'even':
        folded = sp.expand(rule.subs(x, sp.Abs(x)))
        if all(_agree(folded, b['expression'], b['set'], x) for b in branches):
            return folded
    return sp.Piecewise(*((b['expression'], b['set'].as_relational(x)) for b in branches))


def solve(desc):
    if not desc.get('structure_supported'):
        raise ValueError(desc.get('reason') or 'parity_ext.unsupported')
    x = symbols(desc)
    rule, _ = combined_rule(desc)
    values = points(desc)
    domain, known, requested, mirrored = ranges(desc)
    given = known | sp.FiniteSet(*values)
    sign = SIGNS[desc['property']]
    # The checks proved every printed denominator nonzero on the rule's range and its mirror, so cancelling there is exact.
    rational = len(rule_rows(desc)) == 1 and bool(rule_denominators(desc['rule_ast'], x)) and not radicands(rule)
    tidy = (lambda e: sp.cancel(sp.together(e))) if rational else (lambda e: e)
    substituted = rule.subs(x, -x, simultaneous=True)
    substituted = sp.expand(substituted) if not radicands(rule) and not rational else substituted
    expression = tidy(sp.expand(sign * substituted)) if not rational else tidy(sign * substituted)
    pieces, free = [], sp.S.EmptySet
    for atom in atoms(desc):
        role, s = atom['role'], atom['set']
        t = atom['representative']
        if role in ('known', 'overlap'):
            value = tidy(rule) if atom['kind'] == 'open' or known.contains(t) is sp.true else values[t]
            pieces.append((s, on_region(value, s), 'given'))
        elif role == 'mirrored':
            value = expression if atom['kind'] == 'open' or known.contains(-t) is sp.true else sign * values[-t]
            pieces.append((s, on_region(value, s), 'mirrored'))
        elif role == 'forced_zero':
            pieces.append((s, sp.S.Zero, 'zero'))
        else:
            free |= s
    branches = _merge(pieces, x)
    determined = (domain if desc['property'] == 'both' else
                  given | reflect(given) | (domain & sp.FiniteSet(0) if sign == -1 else sp.S.EmptySet))
    return {'version': VERSION, 'description': deepcopy(desc), 'variable': x, 'rule': rule,
            'domain': domain, 'rule_domain': known, 'requested_domain': requested,
            'mirrored_domain': mirrored, 'mapped_domain': reflect(mirrored), 'sign': sign,
            'substituted': substituted, 'expression': expression,
            'zero_status': _zero_status(domain, given, desc['property']), 'branches': branches,
            'answer_expression': _answer_expression(branches, tidy(rule), x, desc['property']),
            'determined_domain': determined, 'free_domain': free,
            'domain_identity': 'declared_symmetric_domain' if desc['domain_ast'] is None else 'explicit',
            'status': 'insufficient_information' if free != sp.S.EmptySet else 'determined_on_domain'}


def _components(s):
    return list(s.args) if isinstance(s, sp.Union) else [s]


def _agree(a, b, s, x):
    """Exact identities on complete cells; absolute values use their own arguments' signs.

    In particular |x-1| cannot be replaced by x-1 just because x is positive.
    Piecewise branches are intersected with s before comparing, retaining holes.
    """
    if s == sp.S.EmptySet:
        return True
    difference = sp.piecewise_fold((a - b).rewrite(sp.Piecewise))
    rows = difference.args if isinstance(difference, sp.Piecewise) else [(difference, sp.true)]
    rest = s
    for expr, cond in rows:
        here = rest if cond is sp.true else rest & cond.as_set()
        for part in _components(here):
            if part == sp.S.EmptySet:
                continue
            if isinstance(part, sp.FiniteSet):
                if any(sp.simplify(expr.subs(x, p)) != 0 for p in part):
                    return False
            elif not isinstance(part, sp.Interval) or sp.simplify(expr) != 0:
                return False
        rest -= here
    return rest == sp.S.EmptySet


def _agree_answer(answer, expr, s, x):
    if not isinstance(answer, sp.Piecewise):
        return _agree(answer, expr, s, x)
    rest = s
    for piece, cond in answer.args:
        here = rest & cond.as_set()
        if here != sp.S.EmptySet and not _agree(piece, expr, here, x):
            return False
        rest -= here
    return rest == sp.S.EmptySet


def verify(desc, model):
    """Independent set-level check from the original syntax; never calls ``solve`` or the cell partition."""
    try:
        if not desc.get('structure_supported') or model.get('description') != desc:
            return False
        if set(model) != MODEL_KEYS or model['version'] != VERSION:
            return False
        x = sp.Symbol(desc['variable'], real=True)
        sign = SIGNS[desc['property']]
        rule, known = combined_rule(desc)
        if model['variable'] != x or model['sign'] != sign or not _agree(model['rule'], rule, known, x):
            return False
        abstract = desc['domain_ast'] is None
        if model['domain_identity'] != ('declared_symmetric_domain' if abstract else 'explicit'):
            return False
        # An abstract domain is symmetric by the parity premise; its sets are read on ℝ and then ∩ D.
        domain = sp.S.Reals if abstract else region(desc['domain_ast'])
        requested = domain if desc['requested_domain_ast'] is None else region(desc['requested_domain_ast'])
        given = {}
        for row in desc['point_rules']:
            c, v = rule_expression(row['argument_ast'], x), rule_expression(row['value_ast'], x)
            if c in given and sp.simplify(given[c] - v) != 0:
                return False
            given[c] = v
        t = sp.Symbol('t', real=True)
        neg = lambda s: sp.imageset(sp.Lambda(t, -t), s)
        if (neg(domain) != domain or model['domain'] != domain or model['rule_domain'] != known
                or model['requested_domain'] != requested or not requested.is_subset(domain)
                or any(domain.contains(c) is not sp.true for c in given)):
            return False
        original_rows = rules(desc)
        for i, (s, expr, ast) in enumerate(original_rows):
            if s == sp.S.EmptySet or undefined_on(ast, expr, x, s):
                return False
            if any(not _agree(expr, other, s & t, x) for t, other, _ in original_rows[:i]):
                return False
        if desc['property'] == 'both' and (not _agree(rule, sp.S.Zero, known, x) or any(v != 0 for v in given.values())):
            return False
        reflected = rule.xreplace({x: -x})
        mirror = neg(known)
        # f(-x) = s f(x) wherever both values are given, including between a point value and the rule.
        if not _agree(reflected, sign * rule, known & mirror, x):
            return False
        for c, v in given.items():
            if known.contains(c) is sp.true and sp.simplify(rule.subs(x, c) - v) != 0:
                return False
            if known.contains(-c) is sp.true and sp.simplify(rule.subs(x, -c) - sign * v) != 0:
                return False
            if -c in given and sp.simplify(given[-c] - sign * v) != 0:
                return False
        points_set = sp.FiniteSet(*given)
        all_given = known | points_set
        mirrored = (requested & mirror) - all_given
        if ((mirrored == sp.S.EmptySet and desc['property'] != 'both') or model['mirrored_domain'] != mirrored
                or model['mapped_domain'] != neg(mirrored) or not neg(mirrored).is_subset(known)):
            return False
        if (not _agree(model['substituted'], reflected, mirror, x)
                or not _agree(model['expression'], sign * reflected, mirror, x)):
            return False
        zero_in = domain.contains(0) is sp.true
        expected_zero = ('not_in_domain' if not zero_in else 'known' if all_given.contains(0) is sp.true
                         else 'forced_zero' if desc['property'] in ('odd', 'both') else 'free')
        if model['zero_status'] != expected_zero:
            return False
        determined = (domain if desc['property'] == 'both' else
                      all_given | neg(all_given) | (sp.FiniteSet(0) if sign == -1 and zero_in else sp.S.EmptySet))
        free = requested - determined
        if model['determined_domain'] != determined or model['free_domain'] != free or free == requested:
            return False
        if model['status'] != ('insufficient_information' if free != sp.S.EmptySet else 'determined_on_domain'):
            return False
        covered = sp.S.EmptySet
        for branch in model['branches']:
            s, e = branch['set'], branch['expression']
            if s == sp.S.EmptySet or (covered & s) != sp.S.EmptySet:
                return False
            covered |= s
            if not _agree(e, rule, s & known, x) or not _agree(e, sign * reflected, (s & mirror) - all_given, x):
                return False
            for c in s & points_set if isinstance(s & points_set, sp.FiniteSet) else []:
                if sp.simplify(e.subs(x, c) - given[c]) != 0:
                    return False
            for c in (s & neg(points_set)) - all_given if isinstance(s & neg(points_set), sp.FiniteSet) else []:
                if sp.simplify(e.subs(x, c) - sign * given[-c]) != 0:
                    return False
            rest = s - all_given - mirror - neg(points_set)
            if rest != sp.S.EmptySet:
                if desc['property'] == 'both':
                    if not _agree(e, sp.S.Zero, rest, x):
                        return False
                elif rest != sp.FiniteSet(0) or sign != -1 or e.subs(x, 0) != 0:
                    return False
            if not _agree_answer(model['answer_expression'], e, s, x):
                return False
        return covered == requested - free
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, NotImplementedError):
        return False
