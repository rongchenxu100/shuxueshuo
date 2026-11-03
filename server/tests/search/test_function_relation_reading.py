"""A named unknown function must reach the photo lesson's reading card.

Synthetic fixtures reproduce the source text of the reported photo; they do
not claim a fresh OCR/model review. Both binding and the owned API are real.
"""

import secrets
import time
from copy import deepcopy
from hashlib import sha256

import pytest
from PIL import Image

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_two.formula_surface import formula_source_spans
from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.identity import build_identity
from shuxueshuo_server.search.lesson import run_stage_two
from tests.search.support import authenticated_client, session_for
from tests.search.test_identity import reviewed_result

TARGET = '/root/goals/0'


def candidate(*, kind='find_value', name='f', variable='x', prefix='已知函数'):
    goal = {'kind': kind, 'function': name, 'variable': variable,
            'relation': f'{name}(2*{variable}+1)={variable}^2-2*{variable}'}
    if kind == 'find_value':
        goal['expression'] = f'{name}(2)'
    requested = f'{name}(2)' if kind == 'find_value' else f'{name}({variable})'
    task = '值' if kind == 'find_value' else '解析式'
    text = (f'13. {prefix} ${name}({variable})$ 满足 '
            f'${name}(2{variable}+1)={variable}^2-2{variable}$，则 ${requested}$ 的{task}为____。')
    return {'original_text': text, 'root': {'goals': [goal]}}


def locate(value):
    context = build_context(value, TARGET)
    description = context.get('formula_goal', context.get('evaluation_goal'))
    return formula_source_spans(value, TARGET, [(0, len(value['original_text']))],
                                description, _abstract_formula_matches)


@pytest.mark.parametrize('kind', ['find_value', 'find_function_formula'])
@pytest.mark.parametrize('name,variable,prefix', [('f', 'x', '已知函数'), ('p', 't', '设函数')])
def test_function_introduction_binds_name_and_variable_without_an_extra_condition(kind, name, variable, prefix):
    value = candidate(kind=kind, name=name, variable=variable, prefix=prefix)
    before = deepcopy(value)
    spans = locate(value)
    assert spans
    introductions = [row for row in spans if value['original_text'][row[0]:row[1]] == f'{name}({variable})'
                     and row[2] == 'expression']
    assert len(introductions) == 1
    assert introductions[0][3] == [TARGET+'/function', TARGET+'/variable']
    assert any(row[2] == 'goal' for row in spans)
    assert value == before


@pytest.mark.parametrize('before,after', [
    ('$f(x)$', '$g(x)$'), ('$f(x)$', '$f(x+1)$'), ('$f(x)$', '$f(x)>0$'),
    ('$f(x)$ 满足', '$f(x)$ 为偶函数，满足'),
    ('$f(x)$ 满足', '$f(x)$ 的值为 $1$，满足'),
    ('x^2-2x', 'x^2+2x'), ('则 $f(2)$', '则 $f(3)$'),
])
def test_introduction_does_not_hide_different_names_arguments_or_extra_conditions(before, after):
    value = candidate()
    value['original_text'] = value['original_text'].replace(before, after)
    assert locate(value) is None


def forbidden(*args, **kwargs):
    raise AssertionError('saved function-value lesson must not invoke OCR or a model')


@pytest.mark.parametrize('mismatch', [False, True])
def test_photo_api_requires_reading_card_as_well_as_verified_answer(tmp_path, monkeypatch, mismatch):
    monkeypatch.setattr(dev_api, 'run_question_image', forbidden)
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    root = tmp_path/'search'
    session = session_for(root)
    page_id, search_id = secrets.token_hex(6), secrets.token_hex(6)
    directory = root/'submissions'/search_id
    directory.mkdir(parents=True)
    value = candidate()
    if mismatch:
        value['original_text'] = value['original_text'].replace('$f(x)$', '$g(x)$')
    value['public_content'] = {
        'completeness': 'complete', 'privacy': 'separated', 'figure': 'not_required',
        'figure_detection': {'status': 'none', 'regions': []},
        'scopes': [{'scope_ref': '/root', 'statement': value['original_text'],
                    'choices': [{'target_ref': TARGET, 'status': 'none', 'selection_mode': 'none', 'options': []}]}],
    }
    result = reviewed_result(value)
    result.update(features=extract_features(result['candidate'])['features'], features_ok=True)
    page = root/'pages'/page_id
    page.mkdir(parents=True)
    for path in (page/'page.png', directory/'question.png', directory/'original.png'):
        Image.new('RGB', (100, 100), 'white').save(path)
    digest = sha256((directory/'question.png').read_bytes()).hexdigest()
    result.update(question_sha256=digest, sent_image_sha256=[digest])
    save(directory/'result.json', result)
    save(directory/'crop.json', {'page_id': page_id, 'box': [0, 0, 1, 1]})
    session.repository.register_page(session.user, page_id, {})
    session.repository.create_submission(session.user, search_id, page_id, [0, 0, 1, 1])
    assert session.repository.associate(search_id, build_identity(result))
    run_stage_two(directory, result, provider=forbidden, unsupported_root=directory/'unsupported')
    session.repository.set_state(search_id, recognition_state='reviewed', lesson_state='not_started')
    base = f'/api/search/problems/{search_id}'
    with authenticated_client(root) as client:
        goal, = client.get(base).json()['lesson']['goals']
        assert bool(goal['walk']) is not mismatch
        if not mismatch:
            assert [step['id'] for step in goal['walk']['bundle']['intro']] == ['D1', 'D2']
        assert client.post(base+'/lesson/start').status_code == 200
        deadline = time.monotonic()+60
        while time.monotonic() < deadline:
            detail = client.get(base).json()
            if detail['lesson_status'] not in ('not_started', 'running'):
                break
            time.sleep(0.05)
        assert detail['lesson']['execution_status'] == 'completed', detail
        assert detail['lesson_status'] == ('failed' if mismatch else 'ready')
        snapshot = client.get(detail['lesson']['stream']['snapshot_url']).json()
        assert snapshot['goals'][TARGET]['answer']['value']['expression'] == '-3/4'
        assert len(snapshot['math_steps']) == 2
        assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
