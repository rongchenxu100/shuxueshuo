"""Verified graph transformations shared by topic and photograph routes."""
from copy import deepcopy

from ..function_graph import solve, verify
from .capabilities import CapabilityGap, LocalCheckFailed, result
from .trajectory import decode_value, encode_value


def admitted(context):
    desc = context.get('graph_goal', {})
    sources = [{key: row[key] for key in ('source_ref', 'expression')} for row in context.get('entries', [])]
    return (context.get('goal', {}).get('kind') in ('select_function_graph', 'draw_function_graph', 'solve_graph_inequality')
            and sources == desc.get('given_definitions', []) and desc.get('structure_supported') is True)


def transform_function_graph(context):
    if not admitted(context) or context['goal']['kind'] != 'select_function_graph':
        raise CapabilityGap('function_graph.input_class_unavailable')
    desc = deepcopy(context['graph_goal'])
    try:
        transformed = solve(desc)
    except ValueError as exc:
        raise CapabilityGap(str(exc)) from exc
    if not verify(desc, transformed):
        raise LocalCheckFailed('function_graph.local_verification_failed')
    return result({'description': desc, 'graph_result': transformed}, ['graph_coordinate_transform'],
                  [{'kind': 'point_map_domains_and_original_options', 'passed': True}])


def verify_frozen(candidate, target_ref, context, encoded_result):
    from .context import build_context
    current = build_context(candidate, target_ref)
    valid = current == context and admitted(current) and verify(current['graph_goal'], decode_value(encoded_result))
    return {'status': 'verified' if valid else 'math_failed',
            'checks': [{'kind': 'source_formula_map_domain_and_all_options', 'passed': valid}],
            'processing': [{'source_ref': row['source_ref'], 'kind': 'identical_graph_definition', 'status': 'processed'}
                           for row in current['entries']] if valid else [],
            'diagnostics': [] if valid else [{'code': 'function_graph.independent_verification_failed'}]}


def finish(state, context, previous):
    transformed = decode_value(state['graph_result_exact'])
    if not verify(context['graph_goal'], transformed):
        raise LocalCheckFailed('function_graph.finalization_failed')
    if transformed['kind'] != 'select_function_graph':
        from .absolute_graph_runtime import finish_absolute
        return finish_absolute(state, context, previous, transformed)
    correct = next(row for row in transformed['option_verdicts'] if row['matches'])
    answer = {'kind': 'select_function_graph', 'status': 'complete',
              'comparison': 'rough_shape', 'correct_option_id': correct['option_id'],
              'correct_labels': [correct['label']], 'option_verdicts': deepcopy(transformed['option_verdicts'])}
    consistency = 'conflict' if any(r['status'] == 'verified' and r.get('answer') != answer for r in previous) else 'consistent'
    return {'state': deepcopy(state), 'answer': answer,
            'graph_result_exact': encode_value(transformed), 'consistency': consistency}
