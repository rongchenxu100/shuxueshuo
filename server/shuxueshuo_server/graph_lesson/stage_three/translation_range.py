"""Exact images of complete integer translates; never extrapolate a partial cell."""

import sympy as sp

from ..range_syntax import range_domain
from ..stage_one.translation_range import inspect_translation_target
from .capabilities import CapabilityGap, result
from .capabilities.cases import exact_set_equal
from .math_values import math_value

METHOD = 'method-translation-range'
MAX_SEGMENTS = 64


def source_values(desc):
    if desc.get('structure_supported') is not True:
        raise CapabilityGap(desc.get('reason') or 'translation_range.unsupported_source')
    base, image, target = (range_domain(desc[key+'_ast']) for key in ('known_domain', 'known_range', 'input_domain'))
    period, slope = sp.Rational(desc['period']), sp.Rational(desc['slope'])
    if (not isinstance(base, sp.Interval) or base.measure != period
            or base.start.is_Rational is not True or base.end.is_Rational is not True):
        raise CapabilityGap('translation_range.full_period_interval_required')
    parts = target.args if isinstance(target, sp.Union) else [target]
    if (len(parts) > MAX_SEGMENTS or not all(isinstance(part, sp.Interval)
            and part.start.is_Rational is True and part.end.is_Rational is True for part in parts)):
        raise CapabilityGap('translation_range.finite_target_intervals_required')
    if image == sp.S.EmptySet:
        raise CapabilityGap('translation_range.empty_known_image')
    if (target.sup-target.inf)/period > MAX_SEGMENTS:
        raise CapabilityGap('translation_range.segment_budget')
    # Shared endpoints represent the same input. There must be a possible
    # endpoint value v with both v and v+a*p in the stated complete image.
    if (not base.left_open and not base.right_open
            and image.intersect(translate(image, -slope*period)) == sp.S.EmptySet):
        raise CapabilityGap('translation_range.conflicting_endpoint_values')
    return base, image, target, period, slope


def translate(value, offset):
    if value == sp.S.Reals:
        return value
    if isinstance(value, sp.Interval):
        return sp.Interval(value.start+offset, value.end+offset,
                           left_open=value.left_open, right_open=value.right_open)
    if isinstance(value, sp.FiniteSet):
        return sp.FiniteSet(*(point+offset for point in value))
    if isinstance(value, sp.Union):
        return sp.Union(*(translate(part, offset) for part in value.args))
    raise CapabilityGap('translation_range.unsupported_set')


def solve(desc):
    base, image, target, period, slope = source_values(desc)
    indexes = set()
    parts = target.args if isinstance(target, sp.Union) else [target]
    for part in parts:
        first, last = (part.start-base.start)/period, (part.end-base.end)/period
        if first.is_Integer is not True or last.is_Integer is not True or first > last:
            raise CapabilityGap('translation_range.partial_base_interval')
        if last-first+1 > MAX_SEGMENTS:
            raise CapabilityGap('translation_range.segment_budget')
        indexes.update(range(int(first), int(last)+1))
    if len(indexes) > MAX_SEGMENTS:
        raise CapabilityGap('translation_range.segment_budget')
    rows = [{'k': sp.Integer(k), 'input': translate(base, k*period),
             'output': translate(image, k*period*slope)} for k in sorted(indexes)]
    covered = sp.Union(*(row['input'] for row in rows))
    if not exact_set_equal(covered, target):
        raise CapabilityGap('translation_range.incomplete_input_coverage')
    return {'description': desc, 'base': base, 'known_image': image, 'domain': target,
            'period': period, 'slope': slope, 'rows': rows, 'covered': covered,
            'feasible_set': sp.Union(*(row['output'] for row in rows))}


def admitted(context):
    if context.get('goal', {}).get('kind') != 'find_translation_range' or context.get('entries'):
        return False
    try:
        solve(context['translation_range_goal'])
        return True
    except (CapabilityGap, ValueError, TypeError, KeyError):
        return False


def translate_range(context):
    if not admitted(context):
        raise CapabilityGap('translation_range.not_admitted')
    values = solve(context['translation_range_goal'])
    checks = [{'kind': 'integer_translation_full_coverage', 'passed': True,
               'source_refs': values['description']['source_refs'],
               'target_domain': values['domain'], 'rows': values['rows']}]
    desc = {**values['description'], 'translation': {k: v for k, v in values.items() if k != 'description'}}
    return result({'description': desc, 'function': sp.Symbol(desc['function_name']),
                   'variable': sp.Symbol(desc['variable'], real=True), 'domain': values['domain'],
                   'feasible_set': values['feasible_set']}, ['integer_translation_full_coverage'], checks)


def independent_verify(candidate, target_ref, feasible_set):
    """Rebuild shifted sets with imageset from source, independently of solve()."""
    desc = inspect_translation_target(candidate, target_ref)
    base, image, target, period, slope = source_values(desc)
    symbol = sp.Symbol('translation_value', real=True)
    low, high = sp.ceiling((target.inf-base.start)/period), sp.floor((target.sup-base.end)/period)
    if high-low+1 > MAX_SEGMENTS or high < low:
        raise CapabilityGap('translation_range.verification_budget')
    domains, images = [], []
    for k in range(int(low), int(high)+1):
        shift = sp.Lambda(symbol, symbol+k*period)
        segment = sp.imageset(shift, base)
        if segment.is_subset(target) is True:
            domains.append(segment)
            images.append(sp.imageset(sp.Lambda(symbol, symbol+k*period*slope), image))
    coverage = exact_set_equal(sp.Union(*domains), target)
    expected = sp.Union(*images)
    same = isinstance(feasible_set, sp.Set) and exact_set_equal(expected, feasible_set)
    passed = coverage and same
    return {'status': 'verified' if passed else 'math_failed',
            'proof': {'kind': 'integer_translation_complete_image', 'passed': passed,
                      'checks': [{'kind': 'exact_input_cover', 'passed': coverage},
                                 {'kind': 'exact_image_union', 'passed': same}],
                      'source_refs': desc['source_refs'], 'expected': math_value(expected),
                      'actual': math_value(feasible_set)},
            'diagnostics': [] if passed else [{'code': 'translation_range.coverage_or_image_mismatch'}]}


def image_endpoints(candidate, target_ref, feasible_set):
    if independent_verify(candidate, target_ref, feasible_set)['status'] != 'verified':
        raise CapabilityGap('translation_range.unverified_image')
    return {'status': 'passed', 'checks': [
        {'point': math_value(point), 'included': point in feasible_set, 'holds': point in feasible_set,
         'passed': True, 'evidence': {'kind': 'known_exact_image_integer_translation'}}
        for point in sorted(feasible_set.boundary)]}
