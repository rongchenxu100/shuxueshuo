"""G2: replay the real two-question photograph through the owned lesson API."""
import time
from hashlib import sha256
from pathlib import Path

from shuxueshuo_server.search import dev_api
from tests.search.function_equality_recording import (
    forbidden,
    read,
    seed_photo_recording,
)
from tests.search.support import authenticated_client

RECORDING = Path(__file__).parent/'fixtures/function-graph/b09-v1-recorded-20261102'
TARGETS = ['/root/children/0/goals/0', '/root/children/1/goals/0']


def test_two_photo_subquestions_keep_source_operator_complete_and_recover(tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    monkeypatch.setattr(dev_api, 'run_question_image', forbidden)
    root = tmp_path/'search'
    _, directory = seed_photo_recording(root, RECORDING)
    result = read(directory/dev_api.RESULT_FILE)
    public = result['public_candidate']['public_content']
    assert public['figure'] == 'not_required' and public['completeness'] == 'complete'
    assert all(scope['choices'] == [] or all(c['status'] == 'none' for c in scope['choices']) for scope in public['scopes'])
    assert '≥3' in public['scopes'][2]['statement']
    assert not any(word in scope['statement'] for scope in public['scopes'] for word in ('答案', '解析', '留上翻下'))
    assert result['candidate']['root']['children'][1]['goals'][0]['operator'] == '>='
    base = f'/api/search/problems/{directory.name}'
    with authenticated_client(root) as client:
        response = client.get(base)
        assert response.status_code == 200, response.text
        problem = response.json()
        goals = problem['lesson']['goals']
        assert [g['target_ref'] for g in goals] == TARGETS
        assert all(g['primary'] == 'type-function-graph' and not g['d1'].get('diagnostics') for g in goals)
        figures = problem['figures']
        assert figures['source']['quality'] == 'original'
        assert [f['role'] for f in figures['figures']] == ['source']  # No invented option or answer graphs.
        original = client.get(figures['figures'][0]['image_url'])
        assert original.status_code == 200
        assert sha256(original.content).hexdigest() == sha256((RECORDING/'original.png').read_bytes()).hexdigest()
        assert client.post(base+'/lesson/start').status_code == 200
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            lesson = client.get(base).json()['lesson']
            if lesson.get('execution_status') in {'completed', 'partial', 'failed', 'error', 'input_error'}:
                break
            time.sleep(.05)
        assert lesson['execution_status'] == 'completed', lesson
        stream = lesson['stream']
        snapshot = client.get(stream['snapshot_url']).json()
        answers = [snapshot['goals'][target]['answer'] for target in TARGETS]
        assert [a['kind'] for a in answers] == ['draw_function_graph', 'solve_graph_inequality']
        assert all(a['status'] == 'complete' for a in answers)
        assert r'\begin{cases}' in answers[0]['latex']
        assert answers[1]['latex'] == r'\left(-\infty, 1 - \sqrt{7}\right] \cup \left[0, 2\right] \cup \left[1 + \sqrt{7}, \infty\right)'
        parts = [p for chunk in snapshot['interactions'] for p in chunk['parts']]
        assert len(parts) == 8 and len(snapshot['math_steps']) == 6
        assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
        assert len(snapshot['handoffs']) == 2 and all(h['available'] for h in snapshot['handoffs'])
        routes = list(directory.glob('stage-two-*/stage-three/goals/*/routes/*.json'))
        assert len(routes) == 2
        for route in routes:
            context = read(route)['constraint_context']
            assert context['processing'] == {'status': 'complete', 'unprocessed_source_refs': []}
            assert context['entries'][0]['processing']['evidence'][0]['kind'] == 'identical_graph_definition'
        assert any(p.get('guided_plot') for p in parts)
        end = next(p for p in parts if p.get('completion_graphs'))
        curve, number_line = end['completion_graphs']
        assert curve['kind'] == 'piecewise_curve' and number_line['kind'] == 'number_line'
        assert len(curve['params']['points']) == 4
        assert all(not point['open'] for point in curve['params']['points'])
        monkeypatch.setattr('shuxueshuo_server.search.stage_three.runner.run_sample', forbidden)
        assert client.post(base+'/lesson/start').json()['stream'] == stream
        assert client.get(stream['snapshot_url']).json() == snapshot
