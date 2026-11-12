"""Run genuine upload/crop/model/lesson requests in an isolated search instance."""
import argparse
import json
import os
import time
from hashlib import sha256
from pathlib import Path

from PIL import Image

from tests.search.support import authenticated_client, session_for

REPO = Path(__file__).resolve().parents[2]
SOURCES = REPO / 'internal/senior-high/source-images/function-monotonicity-planning-20261104'
CASES = {
    'b01': (3, [65, 135, 1210, 247]),
    'b02': (3, [65, 270, 1220, 389]),
    'b03': (3, [65, 450, 1210, 604]),
    'b04': (3, [65, 640, 1240, 799]),
    'b05': (3, [65, 817, 1200, 968]),
    'b06': (3, [65, 1030, 1220, 1160]),
    'b09': (4, [60, 78, 1225, 242]),
    'b12': (4, [65, 610, 1230, 754]),
    'b13': (4, [65, 775, 1240, 958]),
}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def emit(**value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def main(*, cases=CASES, sources=SOURCES, source_files=None, request_prefix='t3-photo', continue_on_error=False):
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=list(cases), default=list(cases))
    args = parser.parse_args()
    if os.environ.get('RUN_LLM_INTEGRATION') != '1':
        parser.error('RUN_LLM_INTEGRATION=1 is required: this records fresh paid model calls')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    root = out / 'private-search'
    session_for(root)
    summary = {'scope': 'development_source_photos_fresh_live_api_not_unseen_holdout', 'cases': []}
    with authenticated_client(root) as client:
        pages = {}
        for key in args.cases:
            number, pixels = cases[key]
            photo = (Path(source_files[number]) if source_files is not None
                     else Path(sources) / f'source-image-{number:02}.jpg')
            if number not in pages:
                emit(stage='upload', source=photo.name)
                started = time.monotonic()
                media_type = 'image/png' if photo.suffix.lower() == '.png' else 'image/jpeg'
                uploaded = client.post('/api/search/pages', content=photo.read_bytes(), headers={'Content-Type': media_type})
                save(out / f'upload-{number:02}.json', {'status_code': uploaded.status_code, 'body': uploaded.json(),
                     'source': str(photo.relative_to(REPO)), 'source_sha256': sha256(photo.read_bytes()).hexdigest(),
                     'elapsed_seconds': round(time.monotonic()-started, 3)})
                if uploaded.status_code != 200:
                    raise RuntimeError(f'Upload failed: {uploaded.status_code} {uploaded.text}')
                pages[number] = uploaded.json()
                emit(stage='uploaded', number=number, mode=pages[number]['mode'], regions=len(pages[number]['regions']), orientation=pages[number]['orientation'])
            page = pages[number]
            assert page['orientation']['rotation_degrees'] == 0, 'Recheck crop coordinates after auto-rotation'
            with Image.open(photo) as image:
                width, height = image.size
            assert [width, height] == [page['width'], page['height']]
            box = [v/(width if i % 2 == 0 else height) for i, v in enumerate(pixels)]
            search_id = None
            try:
                started = time.monotonic()
                response = client.post('/api/search/problems', json={'page_id': page['page_id'], 'box': box, 'client_request_id': f'{request_prefix}-{key}'})
                assert response.status_code == 200, response.text
                search_id = response.json()['search_id']
                emit(stage='recognizing', case=key, search_id=search_id)
                base = f'/api/search/problems/{search_id}'
                directory = root / 'submissions' / search_id
                save(out / key / 'created.json', {'search_id': search_id})
                save(directory / 'source.json', {'source': str(photo.relative_to(REPO)), 'source_sha256': sha256(photo.read_bytes()).hexdigest(), 'crop_pixels': pixels, 'box': box, 'usage': 'development_real_photo_not_holdout'})
                deadline = time.monotonic() + 600
                last = None
                while time.monotonic() < deadline:
                    status_response = client.get(base)
                    assert status_response.status_code == 200, status_response.text
                    status = status_response.json()
                    state = (status.get('recognition_status'), status.get('lesson_status'), tuple((c['stage'], c['status']) for c in status.get('calls', [])))
                    if state != last:
                        emit(stage='progress', case=key, recognition=state[0], lesson=state[1], calls=state[2])
                        last = state
                    if state[0] in {'failed', 'interrupted', 'needs_confirmation'}:
                        break
                    if state[0] == 'reviewed' and state[1] in {'ready', 'unsupported', 'failed', 'interrupted'}:
                        break
                    time.sleep(.4)
                else:
                    raise TimeoutError(f'{key} recognition/lesson timed out')
                save(out / key / 'api-final.json', status)
                row = {'case': key, 'search_id': search_id, 'recognition_status': status.get('recognition_status'), 'lesson_status': status.get('lesson_status'), 'elapsed_seconds': round(time.monotonic()-started, 3), 'calls': status.get('calls'), 'status': status.get('status')}
                result_path = directory / 'result.json'
                if result_path.exists():
                    result = json.loads(result_path.read_text())
                    row['recognition_seconds'] = result.get('elapsed_seconds')
                    row['original_text'] = result.get('candidate', {}).get('original_text')
                    row['root'] = result.get('candidate', {}).get('root')
                if status.get('recognition_status') == 'reviewed' and status.get('lesson_status') == 'ready':
                    resumed = client.post(base + '/lesson/start')
                    save(out / key / 'start.json', {'status_code': resumed.status_code, 'body': resumed.json()})
                    if resumed.status_code == 200:
                        deadline = time.monotonic() + 120
                        while time.monotonic() < deadline:
                            status = client.get(base).json()
                            lesson = status.get('lesson') or {}
                            if lesson.get('execution_status') in {'completed', 'partial', 'failed', 'error', 'input_error'}:
                                break
                            time.sleep(.1)
                        save(out / key / 'api-completed.json', status)
                        row['execution_status'] = lesson.get('execution_status')
                        row['types'] = [goal.get('primary') for goal in lesson.get('goals', [])]
                        row['source_located'] = bool(lesson.get('goals')) and all(
                            goal.get('d1', {}).get('rows') and not goal['d1'].get('diagnostics')
                            for goal in lesson['goals'])
                        if lesson.get('stream'):
                            stream = lesson['stream']
                            snapshot_response = client.get(stream['snapshot_url'])
                            assert snapshot_response.status_code == 200, snapshot_response.text
                            snapshot = snapshot_response.json()
                            save(out / key / 'snapshot.json', snapshot)
                            row['goals'] = snapshot.get('goals')
                            row['interaction_count'] = len(snapshot.get('interactions', []))
                            row['interactions_ready'] = bool(snapshot.get('interaction_states')) and all(
                                item['status'] == 'interactive' for item in snapshot['interaction_states'])
                            again = client.post(base + '/lesson/start')
                            row['same_stream_on_reopen'] = again.status_code == 200 and again.json().get('stream') == stream
                            row['same_snapshot_on_reopen'] = client.get(stream['snapshot_url']).json() == snapshot
            except Exception as exc:
                if not continue_on_error:
                    raise
                # Preserve failures, continue the inventory; never manufacture a ready result.
                error = {'exception_type': type(exc).__name__, 'message': str(exc)[:1000]}
                save(out / key / 'api-error.json', error)
                row = {'case': key, 'search_id': search_id, 'status': 'api_error',
                       'recognition_status': 'unknown', 'lesson_status': 'api_error',
                       'elapsed_seconds': round(time.monotonic() - started, 3), 'error': error}
                if search_id and (result_path := root / 'submissions' / search_id / 'result.json').exists():
                    result = json.loads(result_path.read_text())
                    row.update(status=result.get('status'), recognition_seconds=result.get('elapsed_seconds'),
                               original_text=result.get('candidate', {}).get('original_text'),
                               root=result.get('candidate', {}).get('root'))
                    if result.get('source_reviewed'):
                        row['recognition_status'] = 'reviewed'
            summary['cases'].append(row)
            save(out / 'summary.json', summary)
            emit(stage='case_complete', **{k:v for k,v in row.items() if k not in {'root', 'goals', 'original_text'}})
    emit(stage='finished', output=str(out))


if __name__ == '__main__':
    main()
