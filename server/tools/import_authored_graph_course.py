"""Build a topic course from an explicitly source-checked authored record.

No model calls or student-upload identity are manufactured. The downstream
recognition, execution, independent verification and course exporter are shared
with photo lessons. Source files and transcriptions are bound by hashes.
"""

import argparse
import json
from hashlib import sha256
from pathlib import Path

from shuxueshuo_server.graph_lesson.stage_one.authored import prepare_authored
from shuxueshuo_server.graph_lesson.stage_three.runner import run_sample
from shuxueshuo_server.graph_lesson.stage_three.teaching_version import (
    teaching_revision,
)
from shuxueshuo_server.graph_lesson.stage_two.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from tools.export_graph_walk_course import export_course


def import_course(record_path, recording, evidence_path):
    record_path, recording, evidence_path = map(Path, (record_path, recording, evidence_path))
    record = json.loads(record_path.read_text())
    if record.get('contract') != 'authored-graph-course/v1':
        raise ValueError('authored.record_contract')
    for source in record['sources']:
        path = (ROOT/source['reference']).resolve()
        if not path.is_relative_to(ROOT) or sha256(path.read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('authored.source_hash_mismatch')
    stage_one = prepare_authored(record['candidate'], run_id=record['problem_id']+'-authored',
                                 sources=record['sources'], reviewer=record['reviewer'])
    recording.mkdir(parents=True, exist_ok=False)
    save(recording/'authored-source.json', record)
    stage_two = run_result(stage_one, recording/'stage-two', admission='authored_topic',
                           input_reference=str(record_path.resolve()), unsupported_root=recording/'unsupported')
    if stage_two['status'] != 'completed':
        raise ValueError('authored.classification_failed')
    result = run_sample(recording/'stage-two/stage-two-result.json', recording/'execution')
    if result['status'] != 'completed' or any(goal['status'] != 'solved' for goal in result['goals']):
        raise ValueError('authored.execution_incomplete')
    evidence = export_course(recording/'execution', record['problem_id'])
    evidence['provenance']['source_admission'] = 'authored_topic'
    evidence['provenance']['authoring_record_sha256'] = sha256(record_path.read_bytes()).hexdigest()
    evidence['provenance']['teaching_revision'] = teaching_revision()
    save(evidence_path, evidence)
    source_path = ROOT/'site/data/graph-walk'/f'{record["problem_id"]}.source.json'
    if source_path.is_file() and record_path.resolve().is_relative_to(ROOT/'internal'):
        source = json.loads(source_path.read_text())
        source['authoringSource'] = str(record_path.resolve().relative_to(ROOT))
        save(source_path, source)
    return {'problem_id': record['problem_id'], 'run_id': evidence['provenance']['run_id'],
            'evidence': str(evidence_path), 'answer': result['goals'][0]['answer']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--recording', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(import_course(args.source, args.recording, args.evidence), ensure_ascii=False))


if __name__ == '__main__':
    main()
