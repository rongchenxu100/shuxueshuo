"""Generated T2 lessons use the same authoritative grading contract as uploads."""
import json
import subprocess
from pathlib import Path

import pytest

from shuxueshuo_server.learning import graph_walk


@pytest.mark.parametrize('key', ['a16', 'a14', 'a07', 'a18', 'b16', 'b11', 'b10', 'b08', 'b14'])
def test_extremum_course_native_grading_matches_verified_replay(key):
    root = Path(__file__).resolve().parents[3]
    version = 'v1' if key == 'a14' else 'v2'
    pid = f'function-monotonicity-{key}-{version}'
    bundle = json.loads((root/f'site/data/graph-walk/{pid}.json').read_text())
    replay = json.loads((root/f'site/data/graph-walk/{pid}.replay.json').read_text())
    code = """import fs from 'node:fs';
import {nativePracticeContract} from './tools/lib/graph-walk-practice.mjs';
console.log(JSON.stringify(nativePracticeContract(JSON.parse(fs.readFileSync(0, 'utf8')))));"""
    contract = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', code],
                         input=json.dumps(bundle), text=True, cwd=root))
    graph_walk.validate_contract(contract, pid)
    route, = replay['routes']
    steps = graph_walk.route_steps(contract, route)
    assert [s['id'] for s in steps] == [a['decision'] for a in replay['actions']]
    for step, action in zip(steps, replay['actions'], strict=True):
        assert graph_walk.grade(step, {'value': action['answer']}, route) == 'passed'
        if step['interaction']['type'] == 'choice':
            wrong = next((o['value'] for o in step['interaction']['options']
                          if o['value'] not in step['expected_answer']['one_of']), None)
            if wrong is not None:
                assert graph_walk.grade(step, {'value': wrong}, route) == 'wrong'
