"""Q13 independently closes domain and range without mixing their identities."""

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import (
    abstract_function_domain,
    verification,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types
from shuxueshuo_server.search.lesson import run_stage_two

DOMAIN_TARGET = '/root/goals/0'
RANGE_TARGET = '/root/goals/1'
FIXTURE = Path(__file__).parent / 'fixtures/abstract-function-domain/q13-candidate.json'


def candidate():
    value = json.loads(FIXTURE.read_text())
    value.pop('public_content', None)
    return value


def features(value):
    result = extract_features(value)
    assert result['ok'], result
    return result['features']


@pytest.mark.parametrize('known_range', ['[0,1/2]', '[-5,-1]', '[100,200]', '{3}'])
def test_known_output_range_is_preserved_but_never_used_as_an_input_restriction(known_range):
    value = candidate()
    for goal in value['root']['goals']:
        goal['known_range'] = known_range
    before = deepcopy(value)
    context = build_context(value, DOMAIN_TARGET)
    assert abstract_function_domain.admitted(context)
    description = context['abstract_domain_goal']
    assert description['known_range_ast'] == context['goal_ast']['known_range']
    assert description['known_range_source_ref'] == DOMAIN_TARGET + '/known_range'
    assert context['goal']['known_range'] == known_range
    solved = abstract_function_domain.solve_abstract_function_domain(context)['outputs']
    assert solved['input_range'] == sp.Interval(1, 2)
    assert solved['candidate_set'] == sp.Interval(0, 1)
    assert solved['description']['known_range_ast'] == context['goal_ast']['known_range']
    assert solved['description']['known_range_source_ref'] == DOMAIN_TARGET + '/known_range'
    assert verification.verify(value, DOMAIN_TARGET, context, sp.Interval(0, 1))['status'] == 'verified'
    assert verification.endpoint_check(value, DOMAIN_TARGET, sp.Interval(0, 1))['status'] == 'passed'
    assert value == before


def test_domain_and_range_keep_distinct_known_goal_features_and_shared_function_identity():
    value = candidate()
    extracted = features(value)
    domain_features = [row for row in extracted if row['target_ref'] == DOMAIN_TARGET]
    range_features = [row for row in extracted if row['target_ref'] == RANGE_TARGET]
    domain_by_id = {row['feature_id']: row for row in domain_features}
    range_by_id = {row['feature_id']: row for row in range_features}
    assert domain_by_id['goal']['status'] == range_by_id['goal']['status'] == 'known'
    assert domain_by_id['goal']['value']['kind'] == 'find_abstract_domain'
    assert range_by_id['goal']['value']['kind'] == 'find_abstract_range'
    assert domain_by_id['abstract_function_domain']['status'] == 'known'
    assert DOMAIN_TARGET + '/known_range' in domain_by_id['abstract_function_domain']['source_refs']
    assert range_by_id['abstract_function_domain']['status'] == 'unknown'
    domain_context = build_context(value, DOMAIN_TARGET)
    range_context = build_context(value, RANGE_TARGET)
    assert domain_context['goal_ast']['known_call'][1] == range_context['goal_ast']['known_call'][1]
    assert domain_context['goal_ast']['known_call'][2] != range_context['goal_ast']['known_call'][2]
    assert domain_context['goal_ast']['known_range'] == range_context['goal_ast']['known_range']
    assert abstract_function_domain.admitted(range_context) is False
    assert range_by_id['abstract_function_range']['status'] == 'known'
    assert any(row['type_id'] == 'type-function-range' and row['status'] == 'supported'
               for row in evaluate_types(range_features))
    forced = evaluate_goal(value, RANGE_TARGET, range_features, 'type-abstract-function-domain')
    assert forced['status'] == 'no_applicable_method'
    assert forced['d3'] is forced['d4'] is None


@pytest.mark.parametrize('inherited', [False, True])
def test_typed_known_range_does_not_authorize_ignoring_arbitrary_facts(inherited):
    value = candidate()
    target = DOMAIN_TARGET
    if inherited:
        value['root'] = {'facts': ['x>1'], 'children': [value['root']]}
        target = '/root/children/0/goals/0'
    else:
        value['root']['facts'] = ['x>1']
    extracted = features(value)
    detail = next(row['value'] for row in extracted
                  if row['target_ref'] == target and row['feature_id'] == 'abstract_function_domain')
    assert detail['structure_supported'] is False
    assert detail['reason'] == 'abstract_domain.additional_conditions_unsupported'
    assert abstract_function_domain.admitted(build_context(value, target)) is False


def test_q13_domain_and_range_are_resolved_without_model_selection(tmp_path):
    value = candidate()
    extracted = features(value)

    def forbidden():
        raise AssertionError('Q13 known goal kinds need no model selection')

    result = run_stage_two(tmp_path, {
        'status': 'reviewed_candidate', 'source_reviewed': True, 'candidate': value,
        'features': extracted, 'features_ok': True,
    }, provider=forbidden, unsupported_root=tmp_path / 'unsupported')
    assert result['status'] == 'completed', result['input_diagnostics']
    by_target = {row['target_ref']: row for row in result['goals']}
    assert by_target[DOMAIN_TARGET]['status'] == 'resolved'
    assert by_target[DOMAIN_TARGET]['primary'] == 'type-abstract-function-domain'
    assert by_target[RANGE_TARGET]['status'] == 'resolved'
    assert by_target[RANGE_TARGET]['primary'] == 'type-function-range'
    assert by_target[RANGE_TARGET]['llm'] is None


def test_q13_completes_each_goal_and_both_interactive_lessons(tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three import runner
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
    from tests.solver.test_graph_stage_three_execution import (
        constructed_upstream,
        store,
    )
    from tools.export_graph_walk_course import export_course

    value = candidate()
    source = constructed_upstream(tmp_path, value)
    output = tmp_path / 'run'
    result = runner.run_sample(source, output)
    assert result['status'] == 'completed', result
    by_target = {row['target_ref']: row for row in result['goals']}
    assert by_target[DOMAIN_TARGET]['status'] == 'solved'
    assert by_target[DOMAIN_TARGET]['answer']['set']['expression'] == 'Interval(0, 1)'
    assert by_target[RANGE_TARGET]['status'] == 'solved', by_target[RANGE_TARGET]
    assert by_target[RANGE_TARGET]['answer']['kind'] == 'find_abstract_range'
    assert by_target[RANGE_TARGET]['answer']['set']['expression'] == 'Interval(0, 1/2)'
    context = by_target[DOMAIN_TARGET]['constraint_context']
    expected_range = context['goal_ast']['known_range']
    assert context['abstract_domain_goal']['known_range_ast'] == expected_range

    snapshot = store(output).snapshot()
    assert len(snapshot['handoffs']) == 2
    handoff = next(row for row in snapshot['handoffs'] if row['target_ref'] == DOMAIN_TARGET)
    assert handoff['target_ref'] == DOMAIN_TARGET and handoff['available'] is True
    checkpoint = store(output).checkpoint(DOMAIN_TARGET, handoff['route_id'])
    executed = decode_value(checkpoint['driver_state']['result'])
    description = executed['domain_evidence']['description']
    assert description['known_range_ast'] == expected_range
    assert description['known_range_source_ref'] == DOMAIN_TARGET + '/known_range'
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])

    evidence = export_course(output, 'q13-domain-acceptance-test')
    exported = {row['target_ref']: row for row in evidence['lesson']['goals']}
    assert exported[DOMAIN_TARGET]['walk'] is not None
    assert exported[RANGE_TARGET]['walk'] is not None
    evidence_path = tmp_path / 'evidence.json'
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False))
    root = Path(__file__).resolve().parents[3]
    script = r"""
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {compileCourse} from './tools/build-graph-walk-topic.mjs';
import {loadSources, repoRoot} from './tools/lib/public-knowledge-sources.mjs';
import {createState, currentDecision, submitAnswer} from './site/assets/graph-walk/walk-state.mjs';
import {replayAnswer} from './site/assets/graph-walk/walk-replay.mjs';
const evidence = JSON.parse(await fs.readFile(process.argv[1], 'utf8'));
const graph = JSON.parse(await fs.readFile(`${repoRoot}/site/knowledge/graph.json`, 'utf8'));
const {nodes} = await loadSources(repoRoot);
const source = {schemaVersion: 1, problemId: 'q13-domain-acceptance-test',
  page: '/topics/function-concepts/q13/', topicHref: '/topics/function-concepts/',
  title: '求定义域', targetRef: '/root/goals/0'};
const {bundle: domainBundle} = compileCourse(source, evidence, graph, nodes);
assert.equal(Object.values(domainBundle.routes)[0].completion.answer.set.expression, 'Interval(0, 1)');
const {bundle} = compileCourse({...source, targetRef: '/root/goals/1'}, evidence, graph, nodes);
const routeId = Object.keys(bundle.routes)[0];
assert.equal(bundle.routes[routeId].completion.answer.kind, 'find_abstract_range');
assert.equal(bundle.routes[routeId].completion.answer.set.expression, 'Interval(0, 1/2)');
let state = createState(bundle), count = 0;
while (currentDecision(bundle, state)) {
  const step = currentDecision(bundle, state);
  assert.ok(count++ < 30, 'domain lesson must terminate');
  if (step.interaction.type === 'choice') {
    const wrong = step.interaction.options.find(option => !step.expected_answer.one_of.includes(option.value));
    if (wrong) {
      const rejected = submitAnswer(bundle, state, {decision: step.id, answer: wrong.value});
      assert.equal(rejected.lastFeedback.status, 'wrong');
      assert.equal(currentDecision(bundle, rejected).id, step.id);
      assert.equal(rejected.done, false);
    }
  }
  state = submitAnswer(bundle, state, {decision: step.id, answer: replayAnswer(step, routeId)});
  assert.equal(state.lastFeedback.status, 'passed');
}
assert.ok(count >= 6);
assert.equal(state.done, true);
assert.ok(evidence.lesson.goals.every(goal => goal.walk));
process.stdout.write(JSON.stringify({decisions: count}));
"""
    probe = subprocess.run(['node', '--input-type=module', '-e', script, str(evidence_path)],
                           cwd=root, capture_output=True, text=True, check=False, timeout=60)
    assert probe.returncode == 0, probe.stderr or probe.stdout
    assert json.loads(probe.stdout)['decisions'] >= 6
