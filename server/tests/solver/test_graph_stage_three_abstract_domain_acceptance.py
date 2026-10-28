"""Q25 runs through storage, independent verification, export, UI and grading."""

import json
import subprocess
from pathlib import Path

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.learning import graph_walk
from tests.solver.test_graph_stage_three_execution import constructed_upstream, store
from tools.export_graph_walk_course import export_course

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).parent / 'fixtures/abstract-function-domain/q25-candidate.json'


def test_q25_complete_verified_run_exports_a_readable_gradeable_lesson(tmp_path):
    candidate = json.loads(FIXTURE.read_text())
    source = constructed_upstream(tmp_path, candidate)
    output = tmp_path / 'run'
    result = runner.run_sample(source, output)
    assert result['status'] == 'completed', result
    assert result['goals'][0]['status'] == 'solved', result['goals'][0]
    snapshot = store(output).snapshot()
    handoff, = snapshot['handoffs']
    assert handoff['available'] is True
    assert handoff['answer']['set']['expression'] == 'Interval(-1, 3/2)'
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
    evidence = export_course(output, 'abstract-domain-acceptance-test')
    path = tmp_path / 'evidence.json'
    path.write_text(json.dumps(evidence, ensure_ascii=False))
    probe = subprocess.run(
        ['node', str(ROOT / 'tools/tests/graph-walk-abstract-domain-acceptance.mjs'), str(path)],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=60)
    assert probe.returncode == 0, probe.stderr or probe.stdout
    contract = json.loads(probe.stdout)
    graph_walk.validate_contract(contract, 'abstract-domain-acceptance-test')
    route_id, = contract['routes']
    for step in contract['routes'][route_id]['steps']:
        if step['interaction']['type'] != 'choice':
            continue
        for option in step['interaction']['options']:
            expected = 'passed' if option['value'] in step['expected_answer']['one_of'] else 'wrong'
            assert graph_walk.grade(step, {'value': option['value']}, route_id) == expected
    resumed = runner.resume_sample(output)
    assert resumed['goals'][0]['answer'] == result['goals'][0]['answer']
    assert store(output).snapshot()['handoffs'] == snapshot['handoffs']
