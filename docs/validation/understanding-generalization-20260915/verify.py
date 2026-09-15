"""Verify immutable audit bytes and reported gates without network or database."""
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import tarfile

root = Path(__file__).resolve().parent
summary = json.loads((root / 'summary.json').read_text())
archive = root / 'evidence.tar.gz'
assert sha256(archive.read_bytes()).hexdigest() == summary['archive_sha256']
with tarfile.open(archive, 'r:gz') as tar:
    members = tar.getmembers()
    assert all(m.isfile() and not PurePosixPath(m.name).is_absolute()
               and '..' not in PurePosixPath(m.name).parts for m in members)
    assert len({m.name for m in members}) == len(members)
    manifest = json.load(tar.extractfile('manifest.json'))
    for name, digest in manifest['files'].items():
        content = tar.extractfile(name).read()
        assert sha256(content).hexdigest() == digest, name
    for name in set(manifest['images'].values()):
        assert sha256(tar.extractfile(name).read()).hexdigest() == Path(name).stem
    for batch in ('five-01', 'five-02'):
        raw = json.load(tar.extractfile(batch + '/batch-summary.json'))
        assert raw['passed_count'] == summary['batches'][batch]['passed']
        for case in raw['cases']:
            assert case['attempt_count'] <= 3 and case['network_attempt_count'] <= 12
            assert case['semantic_call_count'] <= 6 and len(case['source_reviews']) <= 3
            for review in case['source_reviews']:
                assert review['usage']['thinking_mode'] == 'enabled'
                assert review['usage']['reasoning_effort'] == 'low'
        if batch == 'five-02':
            assert raw['passed_count'] == raw['sample_count'] == 5
            config = json.load(tar.extractfile(batch + '/batch-config.json'))
            repo = root.parents[2]
            for name, digest in config['implementation_sha256'].items():
                assert sha256((repo/name).read_bytes()).hexdigest() == digest, name
    for batch in ('holdout-01', 'holdout-02'):
        scores = []
        for case in summary['batches'][batch]['cases']:
            raw = json.load(tar.extractfile(batch + '/' + case['case'] + '/holdout-result.json'))
            assert raw['attempts'] <= 3 and raw['network_attempts'] <= 12
            assert len(raw['reviews']) <= 3 and raw['attempts'] + len(raw['reviews']) <= 6
            ok = raw['accepted'] and raw['domain_ok'] and raw['projection_diff']['ok']
            scores.append(ok)
        assert sum(scores) == summary['batches'][batch]['passed']
print('Archive hashes, images, budgets, scores and final implementation verified.')
print({name: result['passed'] for name, result in summary['batches'].items()})
