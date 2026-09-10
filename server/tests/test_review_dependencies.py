import os
from types import SimpleNamespace

import pytest

from shuxueshuo_server.review.dependencies import collect, spec_parts, manifest, changes, INPUTS, KEYS

CONFIG = SimpleNamespace(doubao_model='extract', doubao_base_url='url', llm_model=None,
                         deepseek_model='solve', deepseek_base_url='url', max_llm_attempts=3,
                         functional_few_shot_mode='strict_test')


def put(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return target


@pytest.mark.parametrize('path,stage', [
    ('internal/llm-prompts/strategy-functional-system.jinja', 'solver'),
    ('server/shuxueshuo_server/solver/explanation/snapshot.py', 'evidence'),
    ('server/shuxueshuo_server/solver/explanation/scope_lesson.py', 'lesson'),
    ('server/shuxueshuo_server/solver/visual/builder.py', 'visual'),
    ('site/assets/css/lesson.css', 'page'),
    ('internal/schemas/functional-plan-v2.schema.json', 'solver'),
    ('internal/schemas/functional-annotated-teaching-plan.schema.json', 'lesson'),
    ('internal/schemas/novel-resource.json', 'source'),
])
def test_change_matrix(tmp_path, path, stage):
    baseline = collect(tmp_path, CONFIG)
    target = put(tmp_path, path, 'a=1')
    added = collect(tmp_path, CONFIG)
    assert [s for s in KEYS if baseline['stages'][s] != added['stages'][s]] == [stage]
    os.utime(target, (100, 100))
    assert collect(tmp_path, CONFIG) == added
    target.write_text('a=2')
    assert collect(tmp_path, CONFIG) != added
    target.rename(target.with_name('renamed' + target.suffix))
    assert collect(tmp_path, CONFIG) != added
    target.with_name('renamed' + target.suffix).unlink()
    assert collect(tmp_path, CONFIG) == baseline


def test_mixed_specs_and_runtime_trace():
    source = 'SPEC = MethodSpecSource(inputs={"x": 1}, teaching_unit=TeachingUnitSpec(title="teach"), visual=VisualSpec(color="blue"))\ndef run(): return "trace"'
    base = spec_parts(source)
    for old, new, stage in [('teach', 'lesson', 'lesson'), ('blue', 'red', 'visual'), ('trace', 'runtime', 'solver')]:
        after = spec_parts(source.replace('"' + old + '"', '"' + new + '"'))
        assert [s for s in base if base[s] != after[s]] == [stage]


def test_ignore_outputs_and_config(tmp_path):
    before = collect(tmp_path, CONFIG)
    put(tmp_path, 'internal/review-runs/generated.json', '{}')
    put(tmp_path, 'server/tests/test_generated.py', 'pass')
    assert collect(tmp_path, CONFIG) == before
    settings = SimpleNamespace(**{**vars(CONFIG), 'deepseek_model': 'changed'})
    after = collect(tmp_path, settings)
    assert [s for s in KEYS if before['stages'][s] != after['stages'][s]] == ['solver', 'lesson']


def test_input_edges_are_distinct_from_audit_edges(tmp_path):
    snapshot = collect(tmp_path, CONFIG)
    artifacts = [{'stage': s, 'name': n, 'sha256': 'hash', 'dependencies': ['unrelated']} for deps in INPUTS.values() for s, n in deps]
    doc = {'stages': [{'id': s} for s in KEYS], 'artifacts': artifacts}
    for record in doc['stages']: record['manifest'] = manifest(doc, record['id'], snapshot)
    assert not changes(doc, snapshot)
    doc['artifacts'].append({'stage': 'source', 'name': 'extra audit', 'sha256': 'new'})
    assert not changes(doc, snapshot)
    doc['artifacts'].append({'stage': 'lesson', 'name': 'LessonIR（实际采用）', 'sha256': 'new'})
    assert [r['stage'] for r in changes(doc, snapshot)] == ['visual']
    del doc['stages'][0]['manifest']
    assert changes(doc, snapshot)[0]['code'] == 'build.version_unknown'


def test_unknown_resources_are_visible(tmp_path):
    put(tmp_path, 'internal/schemas/new-contract.json', '{}')
    result = collect(tmp_path, CONFIG)
    assert result['unclassified_resources'] == [{'path': 'internal/schemas/new-contract.json', 'stage': 'source'}]
