"""Named target functions retain T3 source semantics through photo compilation.

The sequence provider is an offline replay of the failing candidate shape; it
does not claim a new image-model extraction or source-review result.
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp
from shuxueshuo_server.graph_lesson.stage_one import contracts
from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import (
    abstract_domain_parameter,
    abstract_function_domain,
    driver,
    interaction,
    verification,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types
from shuxueshuo_server.problem_understanding.workflow import run_workflow
from shuxueshuo_server.search.extraction import (
    SearchStageOneContract,
    build_search_request,
)
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from tests.solver.test_graph_function_equality_repair import CONFIRMED, Sequence
from tests.solver.test_graph_stage_three_methods import finish

FIXTURES = Path(__file__).parent / 'fixtures/abstract-function-domain'
TARGET = '/root/goals/0'
ALIAS = 'g(x)=f(x+1)/sqrt(3*x-1)'
EXPECTED = sp.Interval.open(sp.Rational(1, 3), 5)


def candidate(*, fixture='mixed-q03-candidate.json', public=False):
    value = json.loads((FIXTURES / fixture).read_text())
    if not public:
        value.pop('public_content', None)
    return value


def extracted(value):
    before = deepcopy(value)
    result = extract_features(value)
    assert result['ok'], result
    assert value == before
    return result['features']


def unsupported(value, target=TARGET):
    result = extract_features(value)
    if result['ok']:
        features = [row for row in result['features'] if row['target_ref'] == target]
        assert not any(row['status'] == 'supported' for row in evaluate_types(features))


@pytest.mark.parametrize('collection', ['definitions', 'facts'])
@pytest.mark.parametrize('alias', [ALIAS, 'g(t)=f(t+1)/sqrt(3*t-1)'])
def test_equivalent_named_target_compiles_recognizes_and_preserves_denominator(collection, alias):
    value = candidate()
    value['root'][collection] = [alias]
    before = deepcopy(value)
    features = extracted(value)
    assert validate_candidate(value)['reports']['ir']['abstract_target_aliases'] == {
        f'r.{collection}[0]': {
            'scope': 'r', 'path': f'r.{collection}[0]', 'source': alias,
            'name': 'g', 'variable': 't' if alias.startswith('g(t)') else 'x',
            'target_refs': [TARGET],
        },
    }
    supported = [row['type_id'] for row in evaluate_types(features) if row['status'] == 'supported']
    assert supported == ['type-abstract-function-domain']
    context = build_context(value, TARGET)
    assert abstract_function_domain.admitted(context)
    outputs = abstract_function_domain.solve_abstract_function_domain(context)['outputs']
    assert outputs['candidate_set'] == EXPECTED
    assert outputs['abstract_domain'] == sp.Interval.open(-2, 5)
    assert outputs['concrete_domain'] == sp.Interval.open(sp.Rational(1, 3), sp.oo)
    assert {row['kind'] for row in outputs['concrete_constraints']} == {
        'denominator_nonzero', 'radicand_nonnegative',
    }
    assert all(row['source_ref'] == TARGET + '/target_call' for row in outputs['concrete_constraints'])
    assert abstract_function_domain.independent_verify(value, TARGET, EXPECTED)['status'] == 'verified'
    assert verification.endpoint_check(value, TARGET, EXPECTED)['status'] == 'passed'
    assert value == before


@pytest.mark.parametrize('collection', ['definitions', 'facts'])
def test_parameter_goal_alias_keeps_parameter_and_renames_only_outer_variable(collection):
    value = candidate(fixture='variant02-candidate.json')
    value['root'][collection] = ['g(t)=f(t+a)+f(t-a)']
    before = deepcopy(value)
    features = extracted(value)
    assert any(row['status'] == 'supported' for row in evaluate_types(features))
    context = build_context(value, TARGET)
    assert abstract_domain_parameter.admitted(context)
    answer = sp.Interval(-sp.Rational(1, 2), sp.Rational(1, 2))
    assert abstract_domain_parameter.solve_abstract_domain_parameter(context)['outputs']['candidate_set'] == answer
    assert abstract_domain_parameter.independent_verify(value, TARGET, answer)['status'] == 'verified'
    assert value == before


@pytest.mark.parametrize('alias', [
    'g(x)=f(x+1)',
    'g(x)=f(x+1)/sqrt(3*x+1)',
    'g(x)=f(x+2)/sqrt(3*x-1)',
    'g(t)=f(x+1)/sqrt(3*x-1)',
    'f(x)=f(x+1)/sqrt(3*x-1)',
])
def test_nonidentical_or_self_referential_definition_is_not_discarded(alias):
    value = candidate()
    value['root']['definitions'] = [alias]
    unsupported(value)


@pytest.mark.parametrize('fact', ['x>1', 'x∈(1,2)', 'g(x)>0'])
def test_real_extra_conditions_are_not_erased_with_target_alias(fact):
    value = candidate()
    value['root']['definitions'] = [ALIAS]
    value['root']['facts'] = [fact]
    unsupported(value)


def test_conflicting_duplicate_alias_does_not_hide_a_second_equation():
    value = candidate()
    value['root']['definitions'] = [ALIAS, 'g(x)=f(x+1)/sqrt(3*x+1)']
    unsupported(value)


def test_alias_cannot_borrow_a_matching_target_from_a_sibling_scope():
    value = candidate()
    goal = value['root']['goals'][0]
    value['root'] = {'children': [
        {'definitions': [ALIAS]},
        {'goals': [goal]},
    ]}
    result = extract_features(value)
    assert result['ok'] is False


def test_alias_of_one_goal_does_not_authorize_discarding_it_for_another_goal():
    value = candidate()
    value['root']['definitions'] = [ALIAS]
    other = deepcopy(value['root']['goals'][0])
    other['target_call'] = 'f(x+2)/sqrt(3*x-1)'
    value['root']['goals'].append(other)
    unsupported(value, '/root/goals/1')


def test_parameter_alias_cannot_rename_the_parameter_or_capture_it_as_its_argument():
    for alias in ('g(t)=f(t+b)+f(t-b)', 'g(a)=f(a+a)+f(a-a)'):
        value = candidate(fixture='variant02-candidate.json')
        value['root']['definitions'] = [alias]
        unsupported(value)


def test_named_target_reaches_review_and_complete_interaction_without_candidate_rewrite(tmp_path):
    value = candidate(public=True)
    value['root']['definitions'] = [ALIAS]
    before = deepcopy(value)
    provider = Sequence(value, CONFIRMED)
    image = contracts.ROOT / 'internal/senior-high/source-images/function-concepts-abstract-mixed-q03/source-question.png'
    request = build_search_request(image.read_bytes(), ExtractionArtifactStore(tmp_path / 'inputs'))
    result = run_workflow(request, provider, tmp_path / 'workflow', [],
                          problem_id='named-target-q03-regression', contract_adapter=SearchStageOneContract())
    assert result['status'] == 'reviewed_candidate', result
    assert result['source_reviewed'] is True
    assert result['candidate'] == before == value
    assert [event['stage'] for event in result['events']] == ['extract', 'review']
    assert provider.calls == 2
    assert json.loads(provider.requests[1].prompt.user_prefix)['candidate'] == value

    math_candidate = deepcopy(result['candidate'])
    math_candidate.pop('public_content')
    state = finish(driver.create_state(
        features=extracted(math_candidate), context=build_context(math_candidate, TARGET),
        method='method-input-domain-correspondence', route_id='abstract-function-domain',
        branch='direct', target_ref=TARGET, run_id='named-target-regression', lesson_version='test',
    ))
    assert state['status'] == 'method_complete', state.get('diagnostics')
    assert decode_value(state['result'])['candidate_set'] == EXPECTED
    chunks, pending = interaction.compile_route(state['interaction_seeds'], interaction.load_registry())
    assert not pending
    assert chunks
    for chunk, _ in chunks:
        interaction.validate_chunk(chunk)
    assert any('分母' in part['title'] or '具体' in part['title']
               for chunk, _ in chunks for part in chunk['parts'])
