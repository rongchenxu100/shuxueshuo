"""Generated T3 R0 lessons use the same authoritative grading contract as uploads."""
import json
import subprocess
from pathlib import Path

import pytest

from shuxueshuo_server.learning import graph_walk


@pytest.mark.parametrize('key', ['b01', 'b02', 'b03', 'b04', 'b05', 'b06', 'b09', 'b12', 'b13'])
def test_inequality_course_native_grading_matches_verified_replay(key):
    root = Path(__file__).resolve().parents[3]
    pid = f'function-monotonicity-{key}-v1'
    bundle = json.loads((root / f'site/data/graph-walk/{pid}.json').read_text())
    replay = json.loads((root / f'site/data/graph-walk/{pid}.replay.json').read_text())
    code = """import fs from 'node:fs';
import {nativePracticeContract} from './tools/lib/graph-walk-practice.mjs';
console.log(JSON.stringify(nativePracticeContract(JSON.parse(fs.readFileSync(0, 'utf8')))));"""
    contract = json.loads(subprocess.check_output(
        ['node', '--input-type=module', '-e', code],
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
