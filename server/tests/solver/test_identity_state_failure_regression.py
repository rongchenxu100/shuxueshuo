"""Recorded failures plus negative state/identity contracts; no live providers."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver import scoped_functional_plan_smoke as smoke
from shuxueshuo_server.solver.runtime.functional_state_allocation import rebase_live_state_versions
from shuxueshuo_server.solver.runtime.functional_plan_models import FunctionalCallReconciliation, FunctionalReturnAllocation
from shuxueshuo_server.solver.runtime.state_identity import (
    ArgVersionBinding, ComputationKey, IndexedStateVersion, LogicalStateKey,
    MathObjectId, ScopeVisibilityResolver, StateIdentityIndex, StateSlotId, StateVersionId,
)

FIXTURES = Path(__file__).parent / 'fixtures/heping_identity_state_failure'

def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


@pytest.mark.parametrize('sample, expected_status', [('01', 'blocked'), ('03', 'accepted')])
def test_recorded_identity_and_state_failures(sample, expected_status, tmp_path):
    # Replay recorded responses against today's identity/state contracts.
    # Historical prompt wording and size are not behavioral acceptance gates.
    case = next(c for c in smoke.load_gold_corpus().cases if c.problem_id == 'tj-2026-heping-ermo-25')
    fixture = smoke._build_planner_authority(case, tmp_path, smoke._resolve_repo_path(smoke._repo_root(), smoke.DEFAULT_F2_INPUT))
    requests = []

    class Client:
        def complete(self, request):
            number = len(requests) + 1
            assert number <= 2, 'Recorded replay must not call a model or invent another response'
            requests.append(request)
            phase = 'pass1' if number == 1 else 'repair'
            return (FIXTURES / f'sample-{sample}-{phase}.json').read_text()

    result = smoke.ScopedFunctionalScopeRetryService(Client(), payload_builder=smoke._smoke_payload_builder()).run(
        inputs=fixture.inputs, planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog, handle_registry=fixture.handle_registry,
        runtime_context=fixture.runtime_context, planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload, max_attempts=2,
    )
    assert result.status == expected_status
    assert len(requests) == 2
    error = next(x for x in walk(requests[1]['planner_payload']) if x.get('code') == 'functional.return_identity_mismatch')
    assert error['expected'] == {'object': 'G'}
    assert error['observed']['object'] == 'E'
    assert error['observed']['via'] == ('eval_e_ii' if sample == '01' else 'ii_final_point')
    assert error['path'] == 'goals[ii.E].answer_from'
    editable = {x['scope_ref'] for x in walk(requests[1]['planner_payload']) if x.get('retry_editable') is True}
    assert editable == ({'i_2', 'ii'} if sample == '01' else {'ii'})
    assert not any(step.startswith('ii_') for step in result.attempts[1].restored_call_ids)
    if sample == '03':
        checkpoint = result.final_execution.checkpoint.authority_payload()
        recovered = next(x for x in walk(checkpoint) if x.get('step_id') == 'ii_recover_E' and 'actual_outputs' in x)
        assert recovered['actual_outputs'] == [{'return': 'adjacent_vertex', 'runtime_type': 'Point', 'value': ['-2', '3/2']}]
        assert all(x['status'] == 'provisionally_solved' for x in walk(checkpoint['root_scope']) if 'goal_ref' in x and 'status' in x)
        assert result.verified_execution is not None


def allocation_case():
    key = LogicalStateKey(MathObjectId('point:problem:Q', 'point', 'problem'), 'coordinate', 'Point')
    slot = StateSlotId(key, 'part')
    previous, selected = StateVersionId(slot, 1), StateVersionId(slot, 2)
    allocation = FunctionalReturnAllocation(
        call_id='recover', return_name='point', handle='fact:part:q', runtime_type='Point',
        valid_scope='part', state_slot_id='q.coordinate@part:Point', object_ref=key.object_id.value,
        identity_policy='target_object', write_mode='transition', logical_state_key=key,
        math_object_id=key.object_id, typed_slot_id=slot, selected_version_id=selected,
        previous_version_id=previous, previous_write_step_id='removed', transition_kind='direct',
        allocation_action='transition', canonical_producer_call_id='recover',
    )
    call = FunctionalCallReconciliation(call_id='recover', scope_id='part', capability_id='construct', resolved_args={}, returns=(allocation,))
    registry = SimpleNamespace(ancestor_scopes=lambda scope: (scope, 'problem'))
    index = StateIdentityIndex(ScopeVisibilityResolver(registry))
    return call, allocation, previous, selected, index


def test_unread_removed_predecessor_becomes_first_write_without_renumbering():
    call, allocation, previous, selected, index = allocation_case()
    calls, repairs = rebase_live_state_versions((call,), base_identity_index=index)
    actual = calls[0].returns[0]
    assert actual.write_mode == actual.allocation_action == 'create'
    assert actual.selected_version_id == selected
    assert actual.previous_version_id is actual.previous_write_step_id is actual.transition_kind is None
    assert actual.source_version_ids == allocation.source_version_ids
    assert repairs[0].removed_previous_version_id == previous
    assert rebase_live_state_versions(calls, base_identity_index=index) == (calls, ())


@pytest.mark.parametrize('has_context', [False, True])
@pytest.mark.parametrize('future_scope', ['part', 'problem'])
def test_future_writer_cannot_prevent_repair_of_removed_predecessor(has_context, future_scope):
    call, allocation, removed, selected, index = allocation_case()
    future_slot = StateSlotId(allocation.logical_state_key, future_scope)
    successor_allocation = replace(
        allocation, call_id='successor', canonical_producer_call_id='successor',
        valid_scope=future_scope, typed_slot_id=future_slot,
        selected_version_id=StateVersionId(future_slot, 3),
        previous_version_id=selected, previous_write_step_id=call.call_id,
        source_version_ids=(selected,),
    )
    if future_scope == 'problem':
        successor_allocation = replace(
            successor_allocation, write_mode='create', allocation_action='create',
            previous_version_id=None, previous_write_step_id=None, transition_kind=None,
            source_version_ids=(),
        )
    successor = replace(call, call_id='successor', scope_id=future_scope, returns=(successor_allocation,))
    context_version = StateVersionId(selected.slot_id, 0)
    if has_context:
        index.register(IndexedStateVersion(context_version, 'part', 'base', 'fact:part:q'))
    calls, repairs = rebase_live_state_versions((call, successor), base_identity_index=index)
    actual = calls[0].returns[0]
    assert actual.selected_version_id == selected
    assert actual.previous_version_id == (context_version if has_context else None)
    assert actual.previous_write_step_id == ('base' if has_context else None)
    assert actual.write_mode == ('transition' if has_context else 'create')
    assert calls[1] == successor  # Exact downstream reads retain the same version.
    assert len(repairs) == 1
    assert repairs[0].call_id == call.call_id
    assert repairs[0].removed_previous_version_id == removed
    assert repairs[0].selected_previous_version_id == actual.previous_version_id
    assert rebase_live_state_versions(calls, base_identity_index=index) == (calls, ())


def test_rebase_uses_prior_live_writer_even_when_later_writer_exists():
    call, allocation, removed, selected, index = allocation_case()
    prior_version = StateVersionId(selected.slot_id, 0)
    prior_allocation = replace(
        allocation, call_id='prior', canonical_producer_call_id='prior',
        selected_version_id=prior_version, write_mode='create', allocation_action='create',
        previous_version_id=None, previous_write_step_id=None, transition_kind=None,
    )
    prior = replace(call, call_id='prior', returns=(prior_allocation,))
    later = replace(call, call_id='later', returns=(replace(
        allocation, call_id='later', selected_version_id=StateVersionId(selected.slot_id, 3),
        previous_version_id=selected, previous_write_step_id=call.call_id,
    ),))
    calls, repairs = rebase_live_state_versions((prior, call, later), base_identity_index=index)
    assert calls[1].returns[0].previous_version_id == prior_version
    assert calls[1].returns[0].previous_write_step_id == 'prior'
    assert calls[1].returns[0].write_mode == 'transition'
    assert calls[0] == prior and calls[2] == later
    assert repairs[0].removed_previous_version_id == removed


@pytest.mark.parametrize('read_kind', ['source', 'computation', 'lineage'])
def test_removed_exact_read_is_never_rebound_or_converted_to_create(read_kind):
    call, allocation, previous, _, index = allocation_case()
    if read_kind == 'source':
        allocation = replace(allocation, source_version_ids=(previous,))
    elif read_kind == 'lineage':
        allocation = replace(allocation, lineage=replace(allocation.lineage, source_version_ids=(previous,)))
    else:
        allocation = replace(allocation, computation_key=ComputationKey('construct', (ArgVersionBinding('point', 0, version_id=previous),)))
    call = replace(call, returns=(allocation,))
    assert rebase_live_state_versions((call,), base_identity_index=index) == ((call,), ())


def test_context_predecessor_is_not_mistaken_for_a_pruned_writer():
    call, _, previous, _, index = allocation_case()
    index.register(IndexedStateVersion(previous, 'part', 'context_producer', 'fact:part:q'))
    assert rebase_live_state_versions((call,), base_identity_index=index) == ((call,), ())


def test_sibling_context_cannot_supply_a_predecessor():
    call, allocation, _, _, index = allocation_case()
    sibling = StateVersionId(StateSlotId(allocation.logical_state_key, 'sibling'), 1)
    index.register(IndexedStateVersion(sibling, 'sibling', 'other', 'fact:sibling:q'))
    calls, _ = rebase_live_state_versions((call,), base_identity_index=index)
    assert calls[0].returns[0].previous_version_id is None
    assert calls[0].returns[0].write_mode == 'create'


def test_unread_ordering_predecessor_reconnects_to_visible_context():
    call, allocation, _, selected, index = allocation_case()
    context_version = StateVersionId(selected.slot_id, 0)
    index.register(IndexedStateVersion(context_version, 'part', None, 'fact:part:q'))
    calls, _ = rebase_live_state_versions((call,), base_identity_index=index)
    actual = calls[0].returns[0]
    assert actual.previous_version_id == context_version
    assert actual.selected_version_id == selected
    assert actual.write_mode == 'transition'
    assert actual.source_version_ids == allocation.source_version_ids
