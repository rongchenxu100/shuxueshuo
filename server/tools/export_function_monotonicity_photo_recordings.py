"""Archive a live photo run immutably, including unsuccessful attempts."""

import argparse
import json
import shutil
from datetime import date
from hashlib import sha256
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def export(run, target, *, sources=REPO / 'internal/senior-high/source-images/function-monotonicity-planning-20261104'):
    target.mkdir(parents=True, exist_ok=False)
    summary = read(run / 'summary.json')
    save(target / 'summary.json', summary)
    for row in summary['cases']:
        key = row['case']
        destination = target / key
        destination.mkdir()
        if row.get('search_id'):
            source = run / 'private-search/submissions' / row['search_id']
            for name in ('source.json', 'crop.json', 'original.png', 'question.png', 'result.json'):
                if (source / name).exists():
                    shutil.copyfile(source / name, destination / name)
            if (source / 'workflow').exists():
                shutil.copytree(source / 'workflow', destination / 'workflow')
        for path in (run / key).glob('*.json'):
            shutil.copyfile(path, destination / path.name)
        ledger = read(destination / 'workflow/ledger.json') if (destination / 'workflow/ledger.json').exists() else {'calls': []}
        responses = {'workflow/' + c['response_file']: read(destination / 'workflow' / c['response_file'])
                     for c in ledger['calls'] if c.get('response_file')}
        save(destination / 'recording.json', {
            'recorded_at': date.today().isoformat(), 'usage': summary['scope'],
            'pipeline': 'real_upload_ocr_manual_crop_extract_review_lesson_api',
            'status': row['status'], 'call_stages': [c['stage'] for c in ledger['calls']],
            'historical_semantic_calls': len(ledger['calls']),
            'historical_network_attempts': sum(c.get('network_attempts', 0) for c in ledger['calls']),
            'response_text_sha256': {name: sha256(r['text'].encode()).hexdigest() for name, r in responses.items()},
            'api_acceptance': {k: v for k, v in row.items() if k not in {'root', 'goals', 'original_text'}},
            'files': {str(p.relative_to(destination)): sha256(p.read_bytes()).hexdigest()
                      for p in sorted(destination.rglob('*')) if p.is_file()},
        })
        print(key, row['recognition_status'], row['lesson_status'])
    uploads = []
    for path in sorted(run.glob('upload-*.json')):
        shutil.copyfile(path, target / path.name)
        number = int(path.stem.split('-')[1])
        source = Path(sources) / f'source-image-{number:02}.jpg'
        upload = {'file': path.name, 'sha256': sha256(path.read_bytes()).hexdigest(),
                  'source': str(source.relative_to(REPO)), 'source_sha256': sha256(source.read_bytes()).hexdigest()}
        page_id = read(path).get('body', {}).get('page_id')
        if page_id:
            artifacts = {}
            for name in ('ocr.json', 'segments.json'):
                original = run / 'private-search/pages' / page_id / name
                if original.is_file():
                    destination = target / f'page-{number:02}' / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(original, destination)
                    artifacts[str(destination.relative_to(target))] = sha256(destination.read_bytes()).hexdigest()
            upload['artifacts'] = artifacts
        uploads.append(upload)
    save(target / 'uploads.json', uploads)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('--sources', type=Path,
                        default=REPO / 'internal/senior-high/source-images/function-monotonicity-planning-20261104')
    args = parser.parse_args()
    export(args.run, args.target, sources=args.sources.resolve())
