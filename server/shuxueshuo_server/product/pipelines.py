"""Code-owned pipeline definitions; no executable code in persisted snapshots."""
from copy import deepcopy

from .db import digest
from .errors import Conflict, ProductError

KEYS = ('source', 'observation', 'extraction', 'projection', 'solver', 'evidence', 'lesson', 'visual', 'page')
TITLES = ('来源入库', 'OCR 与观察', '题意抽取', 'Solver 输入投影', '规划与执行', '教学证据', '学生讲解', '图形生成', '页面编译')
V1 = {
    'schema_version': 'product-pipeline/v1',
    'stages': [{'stage_key': key, 'title': title, 'ordinal': i + 1, 'contract_version': 'v1',
                'depends_on': list(KEYS[:i])} for i, (key, title) in enumerate(zip(KEYS, TITLES))],
    'completion': {'required_stages': list(KEYS), 'required_artifacts': [
        {'stage_key': 'page', 'name': 'page_manifest', 'schema_version': 'product-page/v1'},
        {'stage_key': 'page', 'name': 'page_html', 'schema_version': None}]},
}


CURRENT_PIPELINE_VERSION = 'v2'
V2 = deepcopy(V1)
next(s for s in V2['stages'] if s['stage_key'] == 'extraction')['contract_version'] = 'v2'


def validate(snapshot):
    if snapshot.get('schema_version') != 'product-pipeline/v1':
        raise ProductError('pipeline.unknown_schema')
    stages = snapshot.get('stages')
    if not isinstance(stages, list) or not stages:
        raise ProductError('pipeline.empty')
    seen, ordinals = {}, set()
    for stage in stages:
        key, ordinal = stage.get('stage_key'), stage.get('ordinal')
        if not isinstance(key, str) or not key.strip() or key in seen:
            raise ProductError('pipeline.duplicate_key')
        if type(ordinal) is not int or not 1 <= ordinal <= 32767 or ordinal in ordinals:
            raise ProductError('pipeline.ordinal')
        if not all(isinstance(stage.get(k), str) and stage[k].strip() for k in ('title', 'contract_version')):
            raise ProductError('pipeline.contract')
        deps = stage.get('depends_on')
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps) or len(set(deps)) != len(deps):
            raise ProductError('pipeline.dependencies')
        if any(d not in seen or seen[d] >= ordinal for d in deps):
            raise ProductError('pipeline.dependency_order')
        if ordinals and ordinal <= max(ordinals):
            raise ProductError('pipeline.stage_order')
        seen[key] = ordinal
        ordinals.add(ordinal)
    completion = snapshot.get('completion', {})
    required = completion.get('required_stages')
    if not isinstance(required, list) or not required or any(x not in seen for x in required) or len(set(required)) != len(required):
        raise ProductError('pipeline.completion')
    artifacts = completion.get('required_artifacts')
    if not isinstance(artifacts, list):
        raise ProductError('pipeline.artifacts')
    for artifact in artifacts:
        if artifact.get('stage_key') not in required or not artifact.get('name') or 'schema_version' not in artifact:
            raise ProductError('pipeline.artifact_contract')
    return deepcopy(snapshot)


class PipelineRegistry:
    def __init__(self):
        self._definitions = {('problem_lesson', 'v1'): validate(V1), ('problem_lesson', 'v2'): validate(V2)}

    def register(self, key, version, snapshot):
        checked = validate(snapshot)
        previous = self._definitions.get((key, version))
        if previous is not None and previous != checked:
            raise Conflict('pipeline.version_redefined')
        self._definitions[key, version] = checked

    def get(self, key, version):
        try:
            return deepcopy(self._definitions[key, version])
        except KeyError:
            raise ProductError('pipeline.unsupported') from None


def affected(snapshot, changed, *, suffix=True):
    stages = validate(snapshot)['stages']
    keys = [s['stage_key'] for s in stages]
    invalid = set(changed)
    if not invalid.issubset(keys):
        raise Conflict('pipeline.repreview_required')
    for s in stages:
        if invalid.intersection(s['depends_on']):
            invalid.add(s['stage_key'])
    if suffix and invalid:
        invalid.update(keys[min(keys.index(k) for k in invalid):])
    return [k for k in keys if k in invalid]


def fingerprint(key, version, snapshot, dependencies, config, inputs):
    return digest({'key': key, 'version': version, 'definition': validate(snapshot),
                   'dependencies': dependencies, 'config': config, 'inputs': inputs})


def reusable(old_definition, new_definition, key, old_manifest, new_manifest, compatible_contracts=()):
    old = next((s for s in validate(old_definition)['stages'] if s['stage_key'] == key), None)
    new = next((s for s in validate(new_definition)['stages'] if s['stage_key'] == key), None)
    if old is None or new is None:
        return False
    pair = (old['contract_version'], new['contract_version'])
    if pair[0] != pair[1] and pair not in compatible_contracts:
        return False
    return old['depends_on'] == new['depends_on'] and all(
        field in old_manifest and field in new_manifest and old_manifest[field] == new_manifest[field]
        for field in ('inputs', 'resources', 'config', 'upstream'))
