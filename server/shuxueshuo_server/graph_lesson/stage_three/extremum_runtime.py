"""FM-T2 execution and source-bound finalization shared by both course entrances."""
from copy import deepcopy

from ..extremum_math import numeric_model, parameter_model, verify_numeric, verify_parameter
from .capabilities import CapabilityGap, LocalCheckFailed, result
from .trajectory import decode_value, encode_value

METHODS = {'direct': 'method-monotonicity-extremum', 'quantified': 'method-quantified-range-comparison',
           'specified': 'method-extremum-condition-parameter', 'recurrence': 'method-monotonicity-extremum'}
LABELS = {'direct': '单调性求最值法', 'quantified': '量词比较求参法', 'specified': '指定最值求参法',
          'recurrence': '单调性求最值法'}


def admitted(context, task=None):
    d = context.get('extremum_goal', {})
    entries = [{k: r[k] for k in ('source_ref', 'expression')} for r in context.get('entries', [])]
    return bool(d.get('structure_supported') and d['source'] == context['goal']
                and d['given_definitions'] == entries and (task is None or d['task'] == task
                    or task == 'direct' and d['task'] == 'recurrence'))


def analyze(context):
    if not admitted(context):
        raise CapabilityGap('extremum.unsupported_source')
    d = context['extremum_goal']
    try:
        if d['task'] == 'recurrence':
            from ..recurrence_extremum import solve
            m = solve(d)
        else:
            m = numeric_model(d) if d['task'] == 'direct' else parameter_model(d)
    except (ValueError, NotImplementedError) as exc:
        raise CapabilityGap(str(exc)) from exc
    if not verify(d, m):
        raise LocalCheckFailed('extremum.certificate_failed')
    return result({'extremum_result': m, 'description': deepcopy(d)}, ['extremum_bounds'],
                  [{'kind': 'original_domain_global_bound_and_attainment', 'passed': True}])


def prepare_children(description, extremum_result):
    cases = []
    for i, child in enumerate(extremum_result.get('children', [])):
        d = child['description']
        cases.append({'id': f'term-{i+1}', 'domain': child['model']['effective_domain'], 'condition': True,
                      'context': {'goal': d['source'], 'target_ref': d['target_ref'], 'entries': [], 'monotonicity_goal': d}})
    return result({'branch_cases': cases}, ['extremum_bounds'])


def bind_child(branch_case):
    return result({'child_context': branch_case['context']}, ['extremum_bounds'])


def confirm_children(description, extremum_result, branch_results):
    expected = extremum_result.get('children', [])
    if len(branch_results) != len(expected):
        raise LocalCheckFailed('extremum.missing_child')
    from ..function_monotonicity import verify as verify_mono
    for child, returned in zip(expected, branch_results, strict=True):
        if not verify_mono(child['description'], returned['outputs']['model']):
            raise LocalCheckFailed('extremum.child_direction_invalid')
    if not verify(description, extremum_result):
        raise LocalCheckFailed('extremum.operations_invalid')
    return result({'extremum_result': extremum_result}, ['extremum_operations'],
                  [{'kind': 'common_domain_order_operations', 'passed': True}])


def verify(description, model):
    if description['task'] == 'recurrence':
        from ..recurrence_extremum import verify as verify_recurrence
        return verify_recurrence(description, model)
    return verify_numeric(description, model) if description['task'] == 'direct' else verify_parameter(description, model)


def confirm(description, extremum_result):
    if not verify(description, extremum_result):
        raise LocalCheckFailed('extremum.statement_invalid')
    return result({'extremum_result': extremum_result}, ['extremum_bounds'])


def check_ranges(description, extremum_result):
    """Borrow the established range/parameter classifiers, retaining their checks."""
    import sympy as sp
    from ..extremum_math import bound_cases, condition_set
    from .capabilities.ranges import quadratic_interval_range, reciprocal_range
    from .capabilities.parametric import partition_interval_cases, parametric_interval_extremum
    p = extremum_result['parameter']
    checks, operations = [], []
    for cert in (extremum_result['universal'], extremum_result['existential']):
        for index, proof in enumerate(cert['proofs']):
            x, expr, b = proof['variable'], proof['expression'], proof['bounds']
            candidates = {**cert, 'candidates': [c for c in cert['candidates'] if c['proof'] == index]}
            moving = b['low'].has(p) or b['high'].has(p)
            region = sp.Interval(0, 1) if moving else sp.Interval(b['low'], b['high'], not b['left_closed'], not b['right_closed'])
            if proof['family'] == 'cubic':
                # The admitted family is A*x^3+C, not a general cubic.
                a = sp.Poly(expr, x).nth(3)
                checks.append({'kind': 'cubic_order_identity', 'passed': bool(a.is_real and not a.free_symbols),
                               'coefficient': a, 'source': expr, 'domain': region})
                operations.append('extremum_cubic_order')
                continue
            if isinstance(region, sp.FiniteSet):
                continue
            if proof['family'] == 'polynomial' and not moving and not (expr.free_symbols-{x}):
                shared = quadratic_interval_range(expr, x, region)
                records = [(sp.S.Reals, shared['outputs']['range'])]
                operations.extend(shared['operations']); checks.extend(shared['checks'])
            elif proof['family'] == 'polynomial':
                # The affine map covers a moving nonempty closed interval,
                # including its singleton degeneration, with t in [0,1].
                transformed = sp.expand(expr.subs(x, b['low']+(b['high']-b['low'])*x)) if moving else expr
                if moving and not (b['left_closed'] and b['right_closed']):
                    raise CapabilityGap('extremum.closed_moving_range_required')
                records = []
                for bound in ('inf', 'sup'):
                    policy = {'bound': bound}
                    partition = partition_interval_cases(transformed, x, p, region, policy)
                    operations.extend(partition['operations']); checks.extend(partition['checks'])
                    for case in partition['outputs']['cases']:
                        shared = parametric_interval_extremum(transformed, x, p, region, policy, case)
                        operations.extend(shared['operations']); checks.extend(shared['checks'])
                        records.append((case['domain'], shared['outputs']['range']))
            elif proof['family'] == 'reciprocal_sum':
                offset = sp.expand(expr).coeff(x, 0)
                shared = reciprocal_range(sp.expand(expr-offset), x, region)
                r = deepcopy(shared['outputs']['range'])
                r.update(inf=r['inf']+offset, sup=r['sup']+offset)
                records = [(sp.S.Reals, r)]
                operations.extend(shared['operations']); checks.extend(shared['checks'])
            else:
                raise CapabilityGap('extremum.range_family_not_borrowable')
            for branch, value_range in records:
                for key in ('inf', 'sup'):
                    if key not in value_range:
                        continue
                    valid = sp.Union(*(c['parameter_set'] & condition_set(sp.Eq(c['value'], value_range[key]), p)
                                       & (c['attained'] if value_range[key+'_attained'] else sp.S.Reals-c['attained'])
                                       for c in bound_cases(candidates, p, key == 'sup')))
                    if not (branch & cert['nonempty'] & extremum_result['allowed']).is_subset(valid):
                        raise LocalCheckFailed('extremum.shared_range_mismatch')
    confirm(description, extremum_result)
    return result({'extremum_result': extremum_result}, list(dict.fromkeys(operations)), checks)


def prepare_parameter_children(description, extremum_result):
    """M8 splits the specified-extremum condition into per-piece universal subproblems."""
    import sympy as sp
    if extremum_result['task'] != 'specified':
        raise CapabilityGap('extremum.specified_children_required')
    cases = []
    for i, proof in enumerate(extremum_result['certificate']['proofs']):
        b = proof['bounds']
        domain = sp.Interval(b['low'], b['high'], not b['left_closed'], not b['right_closed'])
        if proof['family'] not in ('polynomial', 'reciprocal_sum') or not isinstance(domain, sp.Interval):
            raise CapabilityGap('extremum.specified_child_family')
        cases.append({'id': f'piece-{i+1}', 'domain': domain, 'condition': True,
                      'proof': proof, 'index': i, 'kind': proof['family']})
    return result({'piece_cases': cases}, ['extremum_bounds'])


def _open_trivial_residual_ends(domain, residual, variable):
    """Open endpoints where the residual is identically 0 so separation divisors stay strict."""
    import sympy as sp
    if not isinstance(domain, sp.Interval):
        return domain
    left_open, right_open = domain.left_open, domain.right_open
    if not left_open and domain.left.is_finite and sp.simplify(residual.subs(variable, domain.left)) == 0:
        left_open = True
    if not right_open and domain.right.is_finite and sp.simplify(residual.subs(variable, domain.right)) == 0:
        right_open = True
    return sp.Interval(domain.left, domain.right, left_open, right_open)


LATEX_RELATION = {'<=': r'\le ', '>=': r'\ge '}


def _source_latex(ast):
    """The piece as written in the problem; the solver's cancelled form is not shown."""
    import sympy as sp

    from ..stage_one.function_domain import expression_latex
    from .math_values import latex

    names = {}

    def bind(node):
        if not isinstance(node, list):
            return node
        if node[0] == 'name':
            names[node[1]] = latex(sp.Symbol(node[1]))
            return ['ref', node[1]]
        if node[0] == 'number':
            return node
        return [node[0], *map(bind, node[1:])]

    return expression_latex(bind(ast), '', names=names)


def bind_parameter_child(branch_case, extremum_result):
    import sympy as sp
    from . import capabilities
    from .capabilities import relation as make_relation
    from .math_values import latex
    proof = branch_case['proof']
    specified = extremum_result['specified_value']
    parameter = extremum_result['parameter']
    variable = proof['variable']
    expression = proof['expression']
    # min ⇒ expression ≥ specified; max ⇒ expression ≤ specified.
    operator = '<=' if extremum_result['quantity'] == 'max' else '>='
    residual = sp.expand(expression - specified)
    relation = make_relation(expression, operator, specified)
    domain = branch_case['domain']
    piece_kind = branch_case['kind']
    # Prefer separation when the problem parameter appears and separates cleanly
    # (B08 both pieces). Param-free pieces (B14 right) must not treat a numeric
    # side as "already separated" — that collapses policy distractors.
    separation_domain = _open_trivial_residual_ends(domain, residual, variable)
    if parameter not in relation.free_symbols:
        if branch_case['kind'] != 'polynomial':
            raise CapabilityGap('extremum.specified_child_family')
        piece_kind = 'independent'
    else:
        try:
            capabilities.inspect_separation(relation, parameter, variable, separation_domain)
            piece_kind = 'separable'
            domain = separation_domain
        except CapabilityGap:
            if branch_case['kind'] != 'polynomial':
                raise
            piece_kind = 'polynomial'
    # Shared quantified-subproblem entry; independent pieces skip borrowed methods.
    borrowed = {
        'separable': 'method-separation',
        'polynomial': 'method-interval-extremum',
        'independent': 'method-interval-extremum',
    }[piece_kind]
    shown = _source_latex(proof['source_ast']) if proof.get('source_ast') else latex(expression)
    caption = (
        f'本步条件来自分段式 ${shown}$'
        f'（${latex(variable)}\\in {latex(domain)}$）：'
        f'要求 ${shown}{LATEX_RELATION[operator]}{latex(specified)}$。'
    )
    return result({
        'piece_expression': expression,
        'piece_variable': variable,
        'piece_domain': domain,
        'piece_kind': piece_kind,
        'interval_function': residual,
        # The borrowed interval contract compares parameter_expression (0)
        # on the left with interval_function on the right.
        'interval_operator': '>=' if extremum_result['quantity'] == 'max' else '<=',
        'parameter': parameter,
        'zero': sp.S.Zero,
        'goal': {'kind': 'find_range', 'symbol': str(parameter)},
        'relation': relation,
        'expression': residual,
        'strict': operator in ('>', '<'),
        'quantifier': '∀',
        'constraint_context': {},
        'relation_kind': 'inequality',
        'function_name': 'h',
        # Aliases for the shared quantified_subproblem template / borrow plane.
        'x': variable,
        'domain': domain,
        'universal_statement': relation,
        'borrowed_method': borrowed,
        'subproblem_context': caption,
    }, ['extremum_bounds'])


def reciprocal_parameter_piece(expression, variable, domain, extremum_result):
    from .capabilities.ranges import reciprocal_range
    from .capabilities.parametric import solve_interval_conditions
    import sympy as sp
    offset = sp.expand(expression).coeff(variable, 0)
    base = sp.expand(expression-offset)
    shared = reciprocal_range(base, variable, domain)
    bound = 'sup' if extremum_result['quantity'] == 'max' else 'inf'
    value = shared['outputs']['range'][bound]+offset
    relation = sp.Le(value, extremum_result['specified_value']) if bound == 'sup' else sp.Ge(value, extremum_result['specified_value'])
    solved = solve_interval_conditions([relation], 'all', extremum_result['parameter'], sp.S.Reals)
    return result({'piece_solution': solved['outputs']['solution']},
                  [*shared['operations'], *solved['operations']], [*shared['checks'], *solved['checks']])


def independent_parameter_piece(relation, variable, domain, parameter):
    """Param-free universal piece: verify the inequality, then contribute ℝ or ∅."""
    import sympy as sp
    from . import judgments
    from .capabilities import execute

    if parameter in relation.free_symbols:
        raise LocalCheckFailed('extremum.independent_piece_has_parameter')
    if variable not in relation.free_symbols:
        raise CapabilityGap('extremum.independent_piece_variable_required')
    # Prefer ranging the side that depends on x against a numeric bound.
    if relation.lhs.has(variable) and not relation.rhs.has(variable):
        expression, bound, operator = relation.lhs, relation.rhs, relation.rel_op
    elif relation.rhs.has(variable) and not relation.lhs.has(variable):
        expression, bound, operator = relation.rhs, relation.lhs, {
            '>=': '<=', '>': '<', '<=': '>=', '<': '>',
        }[relation.rel_op]
    else:
        raise CapabilityGap('extremum.independent_piece_bound_required')
    if bound.free_symbols:
        raise CapabilityGap('extremum.independent_piece_numeric_bound_required')
    skill = judgments.range_skill(expression, variable, domain)
    capability = {
        'linear': 'linear_range', 'quadratic': 'quadratic_interval_range',
        'reciprocal': 'reciprocal_range', 'constant': 'linear_range',
    }.get(skill['choice'])
    if capability is None:
        raise CapabilityGap('extremum.independent_piece_range_unavailable')
    shared = execute(capability, {
        'expression': expression, 'variable': variable, 'domain': domain,
    })
    values = shared['outputs']['range']
    key = 'sup' if operator in ('<=', '<') else 'inf'
    comparison = sp.simplify(values[key] - bound)
    if operator == '<=':
        holds = comparison.is_nonpositive is True
    elif operator == '<':
        holds = comparison.is_negative is True or (
            comparison == 0 and not values[key + '_attained'])
    elif operator == '>=':
        holds = comparison.is_nonnegative is True
    elif operator == '>':
        holds = comparison.is_positive is True or (
            comparison == 0 and not values[key + '_attained'])
    else:
        raise CapabilityGap('extremum.independent_piece_operator')
    solution = sp.S.Reals if holds else sp.S.EmptySet
    slope = shared['outputs'].get('slope')
    if slope is None and skill['choice'] in ('linear', 'constant'):
        slope = sp.S.Zero if skill['choice'] == 'constant' else sp.Poly(
            sp.expand(expression), variable).nth(1)
    return result({
        'piece_solution': solution,
        'independent_range': values,
        'independent_holds': holds,
        'independent_expression': expression,
        'independent_bound': bound,
        'independent_operator': operator,
        'independent_slope': slope,
        'independent_bound_key': key,
    }, [*shared['operations']], [*shared['checks'], {
        'kind': 'independent_piece_universal', 'passed': True,
        'holds': holds, 'solution': solution,
    }])


def accept_parameter_children(description, extremum_result, piece_results):
    import sympy as sp
    solutions = extremum_result['piece_solutions']
    if len(solutions) != len(piece_results):
        raise LocalCheckFailed('extremum.missing_piece_subproblem')
    for expected, returned in zip(solutions, piece_results, strict=True):
        if expected != returned['outputs']['solution'] & extremum_result['allowed']:
            raise LocalCheckFailed('extremum.child_parameter_mismatch')
    if sp.Intersection(*(r['outputs']['solution'] for r in piece_results)) & extremum_result['allowed'] != extremum_result['feasible_set']:
        raise LocalCheckFailed('extremum.piece_intersection_mismatch')
    return confirm(description, extremum_result)


def answer(m):
    from .goals import _exact_math, finalize_goal_with_evidence
    if m['task'] in ('quantified', 'specified'):
        return finalize_goal_with_evidence({'kind': 'find_range'}, m['feasible_set'])[0]
    # Same public answer protocol as a quantity extracted from a full image,
    # but the mathematical input here is the verified extremum certificate.
    status = 'attained' if m['attained'] else 'not_attained' if m['value'].is_finite else 'unbounded'
    field = 'value' if m['attained'] else 'bound'
    return {'kind': 'derived_answer', 'request_kind': 'extremum', 'quantity': m['quantity'],
            'status': status, field: _exact_math(m['value'])}


def verify_frozen(candidate, target_ref, context, encoded_result):
    from .context import build_context
    current = build_context(candidate, target_ref)
    valid = current == context and admitted(current) and verify(current['extremum_goal'], decode_value(encoded_result))
    return {'status': 'verified' if valid else 'math_failed',
            'checks': [{'kind': 'original_extremum_statement', 'passed': valid}],
            'processing': [{'source_ref': row['source_ref'], 'kind': 'original_extremum_condition', 'status': 'processed'}
                           for row in current['entries']] if valid else [],
            'diagnostics': [] if valid else [{'code': 'extremum.independent_verification_failed'}]}


def finish(state, context, previous):
    m = decode_value(state['extremum_result_exact'])
    if not verify(context['extremum_goal'], m):
        raise LocalCheckFailed('extremum.finalization_failed')
    final = answer(m)
    consistency = 'conflict' if any(r['status'] == 'verified' and r.get('answer') != final for r in previous) else 'consistent'
    output = {'state': deepcopy(state), 'answer': final, 'extremum_result_exact': encode_value(m), 'consistency': consistency}
    if m['task'] in ('quantified', 'specified'):
        from .goals import _exact_math
        output['feasible_set'] = _exact_math(m['feasible_set'])
    return output


def select(context, contract, primary):
    task = context['extremum_goal']['task']
    choices = ['recurrence'] if task == 'recurrence' else ['direct', 'quantified', 'specified']
    # Use the existing method-card protocol; eligibility is specific to the goal.
    if not admitted(context):
        return {'status': 'no_applicable_method', 'selection': {'kind': 'method_cards', 'rule': contract['rule'], 'branches': [],
                'recommendation_rule': None, 'recommendation_checks': []}, 'd3': None, 'd4': None,
                'diagnostics': [{'code': context['extremum_goal']['reason']}]}
    notes = {'direct': '根据同一区间内的增减，选择最值位置，再检查能否取到。',
             'quantified': '先分清谁随便取、谁负责配合，再比较两边能取到的值或最值。',
             'specified': '先算出指定点的函数值，再检查定义域里其他点都不越过它。',
             'recurrence': '先用递推关系连接各段，比较整段最小值，再找第一次越过下界的位置。'}
    # Cue titles name what students see in the stem; notes say the first action, not the full solution.
    cue_labels = {
        'direct': '给出函数，求最大值或最小值',
        'quantified': '一边随便取，另一边都能配上',
        'specified': '指定某一点已经是最大或最小',
        'recurrence': '给出递推关系，要求整个左侧区间都满足下界',
    }
    cue_notes = {
        'direct': notes['direct'],
        'recurrence': notes['recurrence'],
        'quantified': r'题面常见「对任意 $x_1$，存在 $x_2$，使 $f(x_1)\le g(x_2)$」：左边每一个函数值，右边都能找到配合。先分清谁随便取、谁负责配合，再比较两边的取值范围（或最值），求出使条件成立的参数。',
        'specified': r'例如已知 $f(0)$ 是最小值：先算出这个值，再要求定义域里其他点都不比它更小；若是最大值，则其他点都不比它更大。不必要求只在这一点取到。',
    }
    branch = {'branch': task, 'target': METHODS[task], 'route_id': METHODS[task].removeprefix('method-'),
              'trigger': 'triggered', 'applicability': 'applicable', 'recommendation': 'preferred',
              'route_plan': 'capability_gap', 'missing_capabilities': ['execution:'+METHODS[task]],
              'checks': [{'check_id': 'original_extremum_goal', 'status': 'holds', 'source_refs': context['extremum_goal']['source_refs']}]}
    selected = {'status': 'no_verified_route',
            'selection': {'kind': 'method_cards', 'rule': contract['rule'], 'branches': [branch],
                          'recommendation_rule': 'extremum_goal', 'recommendation_checks': []},
            'd3': {'id': 'D3', 'title': '选择解题方法', 'question': '结合本题的目标，选择解题方法。',
                   'query': {'op': 'methods', 'from': primary},
                   'interaction': {'type': 'method_cards', 'layout': 'connections', 'facts': [], 'method_notes': {},
                                   'checks': [{'id': 'goal', 'question': '这道题需要完成什么？',
                                               'options': [{'value': t, 'label': cue_labels[t], 'note': cue_notes[t]} for t in choices],
                                               'resolved': LABELS[task], 'feedback': notes[task]}],
                                   'method_choices': [{'value': t, 'label': LABELS[t]} for t in choices],
                                   'connections': [{'cue': t, 'method': t} for t in choices],
                                   'source_refs': context['extremum_goal']['source_refs']},
                   'expected_answer': {'checks': {'goal': task}},
                   'verdicts': {t: {'value': 'fit' if t == task else 'unfit', 'message': notes[t] if t == task else '请先核对题目所求的目标。'} for t in choices},
                   'submit_label': '确认选法'},
            'd4': {'id': 'D4', 'title': '按所选方法解题', 'options': [
                {'branch': task, 'method': METHODS[task], 'route_id': branch['route_id'],
                 'recommendation': 'preferred', 'route_plan': 'capability_gap', 'message': LABELS[task]}]}, 'diagnostics': []}
    if task == 'recurrence':
        # One admitted route uses the existing read/confirm protocol. A method
        # choice requires at least two genuine choices, not invented distractors.
        selected['d3'] = {'id': 'D3', 'title': '选择解题方法', 'question': notes[task],
                          'query': {'op': 'methods', 'from': primary}, 'interaction': {'type': 'read'},
                          'expected_answer': {}, 'verdicts': {}, 'submit_label': '用单调性求最值法解题'}
    return selected
