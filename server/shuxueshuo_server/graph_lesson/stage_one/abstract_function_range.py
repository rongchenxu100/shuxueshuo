"""Known output range with an exact domain and an affine input substitution."""

from .abstract_function_domain import (
    describe_abstract_domain_goal,
    inspect_abstract_domain_target,
)

VERSION = 'abstract-function-range-coverage/v1'


def _range_description(value):
    value['structure_version'] = VERSION
    if value['structure_supported'] and (
        value['target_form'] != 'plain' or not value.get('known_range_ast')
    ):
        value.update(structure_supported=False, reason='abstract_range.plain_call_and_known_range_required')
    return value


def describe_abstract_range_goal(report, scope, ancestors, goal_index):
    return _range_description(describe_abstract_domain_goal(
        report, scope, ancestors, goal_index, range_goal=True))


def inspect_abstract_range_target(candidate, target_ref):
    return _range_description(inspect_abstract_domain_target(candidate, target_ref, range_goal=True))
