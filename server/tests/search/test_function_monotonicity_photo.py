"""Real six-source photographs: immutable response replay and the owned lesson API."""
import secrets
import shutil
import time
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.identity import build_identity
from shuxueshuo_server.search.lesson import run_stage_two, stage_one_result
from shuxueshuo_server.search.stage_one import run_question_image
from tests.search.function_equality_recording import (
    RecordedWorkflowProvider,
    forbidden,
    read,
)
from tests.search.support import authenticated_client, session_for

ROOT=Path(__file__).resolve().parents[3]
RECORDINGS=Path(__file__).parent/'fixtures/function-monotonicity'


def replay_photo(key,output):
    recording=RECORDINGS/key
    manifest=read(recording/'recording.json')
    for name,digest in manifest['files'].items():
        assert sha256((recording/name).read_bytes()).hexdigest()==digest
    provenance=read(recording/'source.json')
    source=ROOT/provenance['source']
    assert sha256(source.read_bytes()).hexdigest()==provenance['source_sha256']
    raw=BytesIO()
    with Image.open(source) as photo:
        photo.crop(provenance['crop_pixels']).save(raw,format='PNG')
    assert raw.getvalue()==(recording/'original.png').read_bytes()
    ledger=read(recording/'workflow/ledger.json')
    assert [c['stage'] for c in ledger['calls']]==manifest['call_stages']==['extract','review']
    png=(recording/'question.png').read_bytes()
    provider=RecordedWorkflowProvider(recording,ledger,sha256(png).hexdigest())
    result=run_question_image(png,output,provider,problem_id=ledger['identity']['binding']['problem_id'],original_png=raw.getvalue())
    assert provider.position==2
    assert result['status']=='reviewed_candidate' and result['features_ok']
    assert result['candidate']==read(recording/'result.json')['candidate']
    assert not result.get('figure_binding')
    identity=build_identity(result)
    assert identity and identity['statement']
    return result


@pytest.mark.parametrize('key',['a03','a02','a15','a12','a04','a01'])
def test_real_photo_replay_and_source_roles(key,tmp_path,monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory',forbidden)
    result=replay_photo(key,tmp_path/'recognition')
    s2=run_result(stage_one_result(result,'replay-'+key),tmp_path/'stage-two',admission='student_upload',unsupported_root=tmp_path/'unsupported')
    assert s2['status']=='completed'
    goal,=s2['goals']
    assert goal['primary']=='type-function-monotonicity'
    assert not goal['d1'].get('diagnostics')
    expected=read(ROOT/f'internal/senior-high/authored-courses/function-monotonicity-t1-20261104/{key}.json')['candidate']['root']['goals'][0]
    actual=result['candidate']['root']['goals'][0]
    assert actual['kind']==expected['kind'] and actual['direction']==expected['direction']
    assert actual.get('input_domain')==expected.get('input_domain'), 'handwritten answers must not become a supplied domain'


@pytest.mark.parametrize('key,increasing_count,operations', [
    ('a01', 2, []), ('a02', 1, ['开方', '开方']), ('a04', 1, ['开方', '取倒数', '开方', '取倒数']),
])
def test_photo_api_completes_and_recovers_submethods(key,increasing_count,operations,tmp_path,monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory',forbidden)
    root=tmp_path/'search';session=session_for(root)
    result=replay_photo(key,root/'replay')
    page_id,search_id=secrets.token_hex(6),secrets.token_hex(6)
    session.search_id=search_id
    directory=root/'submissions'/search_id;directory.mkdir(parents=True)
    save(directory/dev_api.RESULT_FILE,result)
    recording=RECORDINGS/key
    with Image.open(recording/'question.png') as im:size=list(im.size)
    save(directory/'crop.json',{'page_id':page_id,'box':[0,0,1,1],'crop_size':size,'bytes':(recording/'question.png').stat().st_size})
    for name in ('question.png','original.png'):shutil.copyfile(recording/name,directory/name)
    page=root/'pages'/page_id;page.mkdir(parents=True);shutil.copyfile(recording/'original.png',page/'page.png')
    session.repository.register_page(session.user,page_id,{})
    session.repository.create_submission(session.user,search_id,page_id,[0,0,1,1])
    assert session.repository.associate(search_id,build_identity(result))
    run_stage_two(directory,result,provider=forbidden,unsupported_root=root/'unsupported')
    session.repository.set_state(search_id,recognition_state='reviewed',lesson_state='not_started')
    base='/api/search/problems/'+search_id
    with authenticated_client(root) as client:
        assert client.get(base).status_code==200
        assert client.post(base+'/lesson/start').status_code==200
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            lesson=client.get(base).json()['lesson']
            if lesson.get('execution_status') in {'completed','partial','failed','error','input_error'}:break
            time.sleep(.05)
        assert lesson['execution_status']=='completed',lesson
        stream=lesson['stream']; snapshot=client.get(stream['snapshot_url']).json()
        answer=snapshot['goals']['/root/goals/0']['answer']
        assert answer['kind']=='find_monotonic_intervals'
        assert len(answer['interval_families']['increasing'])==increasing_count
        parts=[p for c in snapshot['interactions'] for p in c['parts']]
        if key=='a01':
            assert any(p['title']=='检查跨段单调性' for p in parts)
        composition=[p for p in parts if p.get('stem_board',{}).get('operation')]
        assert [p['stem_board']['operation']['label'] for p in composition]==operations
        for part in composition:
            assert part['stem_board']['items'][1]['math'] is None
            assert len(part['graph']['params']['interval_marks'])==1
            assert part['graph']['params']['interval_marks'][0]['trend']!='pending'
        assert all(s['status']=='interactive' for s in snapshot['interaction_states'])
        monkeypatch.setattr('shuxueshuo_server.search.stage_three.runner.run_sample',forbidden)
        assert client.post(base+'/lesson/start').json()['stream']==stream
        assert client.get(stream['snapshot_url']).json()==snapshot
