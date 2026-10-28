"""Unmarked choice sources preserve their mode through completion and handoff."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.stage_one.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.capabilities import LocalCheckFailed
from shuxueshuo_server.graph_lesson.stage_three.equality_runtime import original_choice
from shuxueshuo_server.graph_lesson.stage_three.handoff import validate_original_choice
from tests.solver.test_graph_stage_three_execution import constructed_upstream, store

TARGET = '/root/goals/0'


def candidate(correct):
    options = []
    for label in ('A', 'B'):
        rhs = 'x' if label in correct else 'x+1'
        options.append({'id': label, 'label': label, 'text': f'$f(x)=x$，$g(x)={rhs}$',
                        'functions': [{'id': 'f', 'definition': 'f(x)=x'},
                                      {'id': 'g', 'definition': f'g(x)={rhs}'}],
                        'left': 'local:f', 'right': 'local:g'})
    return {'original_text': '下列各组函数中表示同一函数的是', 'root': {'goals': [{
        'kind': 'compare_functions', 'mode': 'groups', 'select_relation': 'equal',
        'selection_mode': 'unspecified', 'completeness': 'complete',
        'shared_functions': [], 'options': options}]}}


@pytest.mark.parametrize('correct', [('A',), ('A', 'B'), ()])
def test_unmarked_source_completes_and_hands_off_an_exact_set_without_inference(tmp_path, correct):
    source = constructed_upstream(tmp_path, candidate(correct))
    output = tmp_path / 'run'
    result = runner.run_sample(source, output)
    assert result['status'] == 'completed', result
    goal = result['goals'][0]
    assert goal['status'] == 'solved', goal
    answer = goal['answer']
    assert answer['selection_mode'] == 'unspecified'
    assert answer['correct_labels'] == list(correct)
    handoff, = store(output).snapshot()['handoffs']
    assert handoff['answer'] == answer
    choice = handoff['original_choice']
    assert (choice['selection_mode'], choice['kind']) == ('unspecified', 'multiple_choice')
    assert choice['correct_labels'] == list(correct)
    validate_original_choice(choice, TARGET)
    for field, value in [('kind', 'single_choice'), ('selection_mode', 'none'),
                         ('correct_labels', ['illegal']), ('option_verdicts', choice['option_verdicts'][:-1])]:
        changed = {**deepcopy(choice), field: value}
        with pytest.raises(ValueError, match='invalid_original_choice'):
            validate_original_choice(changed, TARGET)
    resumed = runner.resume_sample(output)
    assert resumed['goals'][0]['answer'] == answer
    assert store(output).snapshot()['handoffs'] == [handoff]


def comparison_answer_schemas():
    def walk(value):
        if isinstance(value, dict):
            props = value.get('properties', {})
            if props.get('kind', {}).get('const') == 'compare_functions' and 'selection_mode' in props:
                yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    for filename in ('graph-stage-three-result-v1.schema.json', 'graph-stage-three-route-v2.schema.json'):
        yield from walk(json.loads((ROOT / 'internal/schemas' / filename).read_text()))


def test_every_completion_answer_schema_preserves_unspecified_without_loosening_pair_none():
    answer = {'kind': 'compare_functions', 'status': 'complete', 'mode': 'groups',
              'selection_mode': 'unspecified', 'select_relation': 'equal', 'correct_labels': [],
              'option_verdicts': [{'option_id': 'A', 'label': 'A', 'verdict': 'different', 'reason': 'outputs_differ'}]}
    schemas = list(comparison_answer_schemas())
    assert len(schemas) == 3
    for schema in schemas:
        validator = Draft202012Validator(schema)
        validator.validate(answer)
        assert not validator.is_valid({**answer, 'selection_mode': 'none'})
        assert not validator.is_valid({**answer, 'mode': 'pair', 'select_relation': None})
        validator.validate({**answer, 'mode': 'pair', 'selection_mode': 'none', 'select_relation': None})


@pytest.mark.parametrize('mode,selection', [('groups', 'none'), ('pair', 'single'), ('pair', 'multiple'), ('pair', 'unspecified')])
def test_original_choice_refuses_invalid_pair_or_none_combinations(mode, selection):
    context = {'comparison_goal': {'mode': mode, 'selection_mode': selection}}
    with pytest.raises(LocalCheckFailed, match='invalid_selection_mode'):
        original_choice(context, {})
    assert original_choice({'comparison_goal': {'mode': 'pair', 'selection_mode': 'none'}}, {}) is None


@pytest.mark.parametrize('relative', [
    'server/shuxueshuo_server/graph_lesson/stage_three/equality_runtime.py',
    'server/shuxueshuo_server/graph_lesson/stage_three/handoff.py',
    'internal/schemas/graph-stage-three-result-v1.schema.json',
    'internal/schemas/graph-stage-three-route-v2.schema.json',
])
def test_new_completion_contract_is_part_of_mathematical_fingerprint(monkeypatch, relative):
    source = ROOT / relative
    before = runner.fingerprint()
    original_read = Path.read_bytes
    assert before[relative] == sha256(original_read(source)).hexdigest()
    monkeypatch.setattr(Path, 'read_bytes', lambda path: original_read(path) + (
        b'\n# contract changed\n' if path.resolve() == source else b''))
    after = runner.fingerprint()
    assert {name for name in before if before[name] != after[name]} == {relative}
