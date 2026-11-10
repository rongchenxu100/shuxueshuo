"""FM-T5 execution: the definition method on an abstract function relation."""
from copy import deepcopy

import sympy as sp

from ..abstract_monotonicity_math import (
    _structure,
    construction,
    pair_symbols,
    verify,
    verify_construction,
)
from .capabilities import CapabilityGap, LocalCheckFailed, result
from .trajectory import decode_value, encode_value

METHOD = 'method-monotonicity-definition'
LABEL = '定义法'


def admitted(context):
    d = context.get('abstract_monotonicity_goal', {})
    return bool(d.get('structure_supported') and d['source'] == context.get('goal')
                and not context.get('entries'))


def _description(description):
    if description.get('family') != 'abstract' or not description.get('structure_supported'):
        raise CapabilityGap('abstract_mono.unsupported_source')
    return _structure(description['source'])


def prepare(context):
    """M1 domain step: the declared domain is given, so only the description is carried."""
    if not admitted(context):
        raise CapabilityGap('abstract_mono.unsupported_source')
    d = deepcopy(context['abstract_monotonicity_goal'])
    structure = _structure(d['source'])
    return result({
        'description': d, 'domain_context': None, 'needs_domain': False, 'plain_domain': False,
        'domain': structure['interval'], 'polynomial': None,
        'variable': sp.Symbol(d['variable'], real=True), 'quadratic': False,
    }, ['monotonicity_domain'], [{'kind': 'declared_domain_given', 'passed': True}])


def choose_pair(description):
    structure = _description(description)
    x1, x2 = pair_symbols(description['source'])
    pair = {'family': 'abstract', 'interval': structure['interval'], 'x1': x1, 'x2': x2}
    return result({'pair': pair}, ['abstract_arbitrary_pair'],
                  [{'kind': 'arbitrary_pair_covers_interval', 'passed': True}])


def choose_substitution(description, pair):
    structure = _description(description)
    x1, x2 = pair_symbols(description['source'])
    if pair != {'family': 'abstract', 'interval': structure['interval'], 'x1': x1, 'x2': x2}:
        raise LocalCheckFailed('abstract_mono.pair_mismatch')
    proof = construction(description)
    return result({'abstract_proof': proof}, ['abstract_substitution_choice'],
                  [{'kind': 'composite_input_is_target', 'passed': verify_construction(description, proof)}])


def instantiate_relation(description, abstract_proof):
    structure = _description(description)
    if not verify_construction(description, abstract_proof):
        raise LocalCheckFailed('abstract_mono.invalid_construction')
    scope = structure['relation_domain']
    return result({'abstract_proof': dict(abstract_proof, instantiated=True)},
                  ['abstract_relation_substitution'],
                  [{'kind': 'first_input_in_scope', 'passed': structure['interval'].is_subset(scope)},
                   {'kind': 'second_input_in_scope', 'passed': structure['key_range'].is_subset(scope)}])


def isolate_difference(description, abstract_proof):
    structure = _description(description)
    if not abstract_proof.get('instantiated') or not verify_construction(description, abstract_proof):
        raise LocalCheckFailed('abstract_mono.instance_missing')
    # A and B stand for f(anchor) and f(target); K stands for f(key).
    # The relation is B=A+K or B=A*K. Keep f opaque throughout.
    a, k = sp.symbols('_anchor_value _key_value', real=True)
    target = a+k if structure['output'] == 'sum' else a*k
    delta = abstract_proof['orientation']*(target-a)
    factored = abstract_proof['orientation']*(k if structure['output'] == 'sum' else a*(k-1))
    proof = {k: v for k, v in abstract_proof.items() if k != 'instantiated'}
    return result({'abstract_proof': proof}, ['abstract_difference_isolation'],
                  [{'kind': 'difference_identity', 'passed': sp.expand(delta-factored) == 0},
                   {'kind': 'positive_factor_certificate', 'passed': verify_construction(description, proof)}])


def order_input(description, abstract_proof):
    structure = _description(description)
    return result({'abstract_proof': dict(abstract_proof, key_range=structure['key_range'])},
                  ['abstract_input_order'],
                  [{'kind': 'ordered_pair_input_range', 'passed': verify_construction(description, abstract_proof)}])


def instantiate_sign(description, abstract_proof):
    structure = _description(description)
    covered = (abstract_proof['key_range'] == structure['key_range']
               and abstract_proof['key_range'].is_subset(structure['sign_domain']))
    proof = dict(abstract_proof, sign=structure['delta_sign'], direction=structure['direction'])
    return result({'abstract_proof': proof}, ['abstract_sign_instantiation'],
                  [{'kind': 'key_inside_sign_condition', 'passed': covered}])


def confirm(description, abstract_result):
    if not verify(description, abstract_result):
        raise LocalCheckFailed('abstract_mono.certificate_failed')
    return result({'abstract_result': abstract_result}, ['abstract_monotonicity_conclusion'],
                  [{'kind': 'arbitrary_pair_strict_order', 'passed': True}])


def answer(description, model):
    from .abstract_monotonicity_presentation import _set_tex

    arrow = r'\uparrow' if model['direction'] == 'increasing' else r'\downarrow'
    word = '严格递增' if model['direction'] == 'increasing' else '严格递减'
    return {'kind': description['source']['kind'], 'status': 'complete', 'direction': model['direction'],
            'latex': rf'{description["function"]}\ \text{{在}}\ {_set_tex(model["interval"])}\ \text{{上{word}}}\ ({arrow})',
            'interval_families': {model['direction']: [encode_value(model['interval'])]}}


def verify_frozen(candidate, target_ref, context, encoded_result):
    from .context import build_context
    current = build_context(candidate, target_ref)
    valid = (current == context and admitted(current)
             and verify(current['abstract_monotonicity_goal'], decode_value(encoded_result)))
    return {'status': 'verified' if valid else 'math_failed',
            'checks': [{'kind': 'abstract_relation_sign_and_pair_coverage', 'passed': valid}],
            'processing': [],
            'diagnostics': [] if valid else [{'code': 'abstract_mono.independent_verification_failed'}]}


def finish(state, context, previous):
    model = decode_value(state['monotonicity_result_exact'])
    description = context['abstract_monotonicity_goal']
    if not verify(description, model):
        raise LocalCheckFailed('abstract_mono.finalization_failed')
    final = answer(description, model)
    consistency = 'conflict' if any(r['status'] == 'verified' and r.get('answer') != final for r in previous) else 'consistent'
    return {'state': deepcopy(state), 'answer': final,
            'monotonicity_result_exact': encode_value(model), 'consistency': consistency}


def select(context, contract, primary):
    if not admitted(context):
        return {'status': 'no_applicable_method',
                'selection': {'kind': 'method_cards', 'rule': contract['rule'], 'branches': [],
                              'recommendation_rule': None, 'recommendation_checks': []},
                'd3': None, 'd4': None,
                'diagnostics': [{'code': context.get('abstract_monotonicity_goal', {}).get('reason', 'abstract_mono.unsupported')}]}
    from .abstract_monotonicity_presentation import _context

    desc = context['abstract_monotonicity_goal']
    given = _context({'description': desc})
    note = '没有解析式时，在定义域内任取两个数，看输入变大时，函数值之差是正还是负。'
    cues = [
        {'value': 'definition', 'label': '没有解析式，只给出函数关系与符号条件',
         'note': rf'如本题：${given["relation_tex"]}$，且当 ${given["scope"]}$ 时 ${given["sign_rule"]}$。'},
        {'value': 'structure', 'label': '给出了具体的一次、二次等函数解析式',
         'note': '这时可以直接用常见函数的增减规律。'},
    ]
    labels = {'definition': LABEL, 'structure': '基本函数与复合法'}
    branch = {'branch': 'definition', 'target': METHOD, 'route_id': 'monotonicity-definition',
              'trigger': 'triggered', 'applicability': 'applicable', 'recommendation': 'preferred',
              'route_plan': 'capability_gap', 'missing_capabilities': ['execution:' + METHOD],
              'checks': [{'check_id': 'original_abstract_relation', 'status': 'holds',
                          'source_refs': desc['source_refs']}]}
    return {'status': 'no_verified_route',
            'selection': {'kind': 'method_cards', 'rule': contract['rule'], 'branches': [branch],
                          'recommendation_rule': 'abstract_monotonicity_goal', 'recommendation_checks': []},
            'd3': {'id': 'D3', 'title': '选择解题方法', 'question': '结合本题给出的条件，选择解题方法。',
                   'query': {'op': 'methods', 'from': primary},
                   'interaction': {'type': 'method_cards', 'layout': 'connections', 'facts': [],
                                   'method_notes': {'structure': '本题没有解析式，无法套用常见函数的增减规律。'},
                                   'checks': [{'id': 'source', 'question': '本题给出的函数是什么样的？',
                                               'options': cues, 'resolved': LABEL, 'feedback': note}],
                                   'method_choices': [{'value': key, 'label': labels[key]} for key in labels],
                                   'connections': [{'cue': key, 'method': key} for key in labels],
                                   'source_refs': desc['source_refs']},
                   'expected_answer': {'checks': {'source': 'definition'}},
                   'verdicts': {
                       'definition': {'value': 'fit', 'message': note},
                       'structure': {'value': 'unfit',
                                     'message': '本题没有给出解析式，只能从单调性的定义出发，任取两点比较。'},
                   },
                   'submit_label': '确认选法'},
            'd4': {'id': 'D4', 'title': '按所选方法解题', 'options': [
                {'branch': 'definition', 'method': METHOD, 'route_id': 'monotonicity-definition',
                 'recommendation': 'preferred', 'route_plan': 'capability_gap', 'message': LABEL}]},
            'diagnostics': []}
