"""Explicit opt-in execution of the shared exact original-domain profile."""

from ...problem_understanding.notation_parser import NotationError
from ..function_cells import solve_domain


def solve_original_function_domain(function):
    from .capabilities import CapabilityGap, result

    try:
        solved = solve_domain(function)
    except NotationError as exc:
        raise CapabilityGap(exc.code) from exc
    return result({'solved': solved}, ['domain_intersection'],
                  [{'kind': 'original_guard_intersection_and_source_partition', 'passed': True}])
