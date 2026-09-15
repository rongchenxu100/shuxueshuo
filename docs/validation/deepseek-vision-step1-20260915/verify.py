"""Verify the archived acceptance without a model, OCR service, or database."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-source', action='store_true', help='Also require the current implementation to match the tested version')
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    summary = json.loads((directory / 'summary.json').read_text())
    archive = directory / 'evidence.tar.gz'
    assert sha256(archive.read_bytes()).hexdigest() == summary['evidence_archive_sha256']
    assert summary['ok'] and summary['sample_count'] == summary['passed_count'] == 5
    for case in summary['cases']:
        assert case['accepted'] and case['family_ok'] and case['solver_projection_diff_ok']
        evidence = case['acceptance_evidence']
        assert evidence['domain_semantic_hash'] == evidence['gold_domain_semantic_hash']
        assert evidence['domain_semantic_hash'] and case['source_input_complete']
        assert case['attempt_count'] <= 3 and len(case['reviews']) <= 3
        assert case['semantic_call_count'] <= 6 and case['network_attempt_count'] <= 12
        assert case['reviews'][-1]['status'] == 'confirmed'
    with tarfile.open(archive, 'r:gz') as bundle:
        manifest = json.load(bundle.extractfile('manifest.json'))
        assert manifest['batch_id'] == summary['batch_id']
        for name, digest in manifest['files'].items():
            assert sha256(bundle.extractfile(name).read()).hexdigest() == digest, name
        for digest, name in manifest['image_files'].items():
            assert sha256(bundle.extractfile(name).read()).hexdigest() == digest, name
        for case in summary['cases']:
            for image in case['acceptance_evidence']['image_inputs']:
                assert image['sha256'] in manifest['image_files']
    if args.check_source:
        repo = directory.parents[2]
        for name, digest in summary['implementation_sha256'].items():
            assert sha256((repo / name).read_bytes()).hexdigest() == digest, name
    print(f"{summary['batch_id']}: 5/5; archive, images, semantic hashes and budgets verified")


if __name__ == '__main__':
    main()
