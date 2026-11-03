"""Refresh authored topic evidence before compilation, without OCR or an LLM.

The source record is the build recipe, never a copy of a submethod's steps.
Frozen evidence remains immutable until a new verified export replaces it.
"""

import argparse
import json
import tempfile
from hashlib import sha256
from pathlib import Path

from shuxueshuo_server.graph_lesson.stage_three.teaching_version import (
    teaching_revision,
)
from shuxueshuo_server.graph_lesson.stage_two.contracts import ROOT
from tools.import_authored_graph_course import import_course


def refresh_courses(sources, *, check=False, root=ROOT):
    root = Path(root).resolve()
    current, updated = teaching_revision(), []
    for source_path in sources:
        source = json.loads((root/source_path).read_text())
        recipe = source.get('authoringSource')
        if not recipe:
            continue
        record_path, evidence_path = (root/recipe).resolve(), (root/source['evidence']).resolve()
        if not record_path.is_relative_to(root/'internal') or not evidence_path.is_relative_to(root/'site/data/graph-walk'):
            raise ValueError('course_refresh.invalid_path')
        record = json.loads(record_path.read_text())
        if record['problem_id'] != source['problemId']:
            raise ValueError('course_refresh.problem_mismatch')
        provenance = json.loads(evidence_path.read_text()).get('provenance', {}) if evidence_path.exists() else {}
        if (provenance.get('teaching_revision') == current
                and provenance.get('authoring_record_sha256') == sha256(record_path.read_bytes()).hexdigest()):
            continue
        if check:
            raise ValueError(f'Course teaching flow is stale: {source_path}; run node tools/build-graph-walk-topic.mjs')
        # Export only after all steps and the independent answer check succeed.
        with tempfile.TemporaryDirectory(prefix='course-teaching-update-') as scratch:
            candidate = Path(scratch)/'evidence.json'
            import_course(record_path, Path(scratch)/'recording', candidate)
            evidence_path.write_bytes(candidate.read_bytes())
        updated.append(source['problemId'])
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', nargs='+')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    print(json.dumps({'updated': refresh_courses(args.sources, check=args.check)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
