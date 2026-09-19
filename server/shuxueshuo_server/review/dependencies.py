"""Content-based production dependencies, separate from the audit artifact DAG."""
from __future__ import annotations

import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

from .store import REPO, STAGES

KEYS = tuple(key for key, _ in STAGES)
CONTRACT = 'review-stage-manifest/v1'
INPUTS = {
    'source': (('source', '原始上传图片'),),
    'observation': (('source', '规范化图片'),),
    'extraction': (('source', 'Source / selection / initial Context'), ('observation', 'Observation Context')),
    'projection': (('extraction', 'Extraction Context'), ('extraction', 'VerifiedProblem')),
    'solver': (('extraction', 'Extraction Context'), ('projection', 'Solver ProblemIR')),
    'evidence': (('solver', 'VerifiedFunctionalPlanExecution'), ('solver', 'Evidence input checkpoint/v1'), ('extraction', 'Extraction Context')),
    'lesson': (('evidence', 'ExplanationSnapshot'),),
    'visual': (('evidence', 'ExplanationSnapshot'), ('lesson', 'LessonIR（实际采用）')),
    'page': tuple(('visual', name) for name in ('geometry-spec.json', 'step-decorations.json', 'lesson-data.json')),
}
TEACHING_FIELDS = {'explanation', 'teaching_unit', 'teaching_units', 'teaching_variants', 'generic_teaching_reason'}
VISUAL_FIELDS = {'visual', 'animation'}


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def inventory_paths(root=REPO):
    paths = set()
    for directory, suffixes in (
        ('server/shuxueshuo_server', None), ('tools', {'.mjs', '.js'}),
        ('internal/llm-prompts', None), ('internal/schemas', None),
        ('internal/templates', None), ('internal/config', None),
        ('internal/functional-plan-v2-fixtures', {'.json'}),
        ('internal/functional-plan-fixtures', {'.json'}),
        ('internal/functional-few-shots', {'.json'}),
        ('internal/functional-few-shots-v2', {'.json'}),
        ('internal/functional-few-shot-manifests', {'.json'}),
        ('internal/functional-plan-scope-native-fixtures', {'.json'}),
        ('site/assets/js', {'.js'}), ('site/assets/css', {'.css'}),
    ):
        for path in (root / directory).rglob('*'):
            if path.is_file() and 'tests' not in path.parts and '__pycache__' not in path.parts and (suffixes is None or path.suffix in suffixes):
                paths.add(path)
    for name in ('server/pyproject.toml', 'server/uv.lock', 'frontend/package-lock.json'):
        if (root / name).is_file():
            paths.add(root / name)
    return sorted(paths)


def inventory(root=REPO):
    return {str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest() for path in inventory_paths(root)}


def resource_owner(path):
    """Every resource has an explicit consumer or a conservative fallback."""
    # The product pipeline freezes its notation workflow and runtime lowering
    # separately; keep those files visible to the corresponding stage owners.
    if path.startswith('server/shuxueshuo_server/product/'):
        return None, False
    if path.startswith('server/shuxueshuo_server/problem_understanding/'):
        if Path(path).stem in {'runtime_binding', 'runtime_lowering', 'compact_planner_input'}:
            return 'projection', False
        return 'extraction', False
    if path.startswith(('tools/', 'internal/templates/', 'internal/config/', 'site/assets/', 'frontend/')):
        return 'page', False
    if path.startswith(('internal/functional-plan-', 'internal/functional-few-shot')):
        return 'solver', False
    if path.startswith('internal/llm-prompts/'):
        name = Path(path).name
        if name.startswith('visual-'): return 'visual', False
        if name.startswith(('strategy-', 'functional-')): return 'solver', False
        if name.startswith(('lesson-', 'scope-lesson', 'teaching-', 'explanation-')): return 'lesson', False
        if name.startswith(('problem-', 'extraction-', 'f3-')): return 'extraction', False
        return 'extraction', True
    if path.startswith('internal/schemas/'):
        name = Path(path).name
        if name.startswith('functional-annotated-teaching-'): return 'lesson', False
        if name.startswith(('verified-functional-', 'method-', 'macro-', 'path-minimum-')): return 'solver', False
        if name.startswith(('paddle-', 'multimodal-')): return 'observation', False
        if name.startswith('solver-problem-'): return 'projection', False
        if name.startswith(('functional-', 'strategy-', 'planner-')): return 'solver', False
        if name.startswith(('lesson-', 'scope-lesson', 'teaching-', 'explanation-')): return 'lesson', False
        if name.startswith(('visual-', 'geometry-', 'step-decorations')): return 'visual', False
        if name.startswith(('problem-', 'extraction-', 'source-', 'observation-')): return 'extraction', False
        return 'source', True
    if '/solver/visual/' in path: return 'visual', False
    if '/solver/explanation/' in path:
        if Path(path).stem in {'scope_lesson', 'lesson_ir', 'lesson_semantic', 'teaching_specs'}:
            return 'lesson', False
        return 'evidence', False
    if '/solver/extraction/' in path:
        if Path(path).stem in {'source_identity', 'observations', 'observation_pipeline', 'observation_context', 'paddle_worker', 'handwriting'}:
            return 'observation', False
        if Path(path).stem.startswith(('problem_planning', 'problem_planner', 'problem_solver', 'problem_domain_projection')):
            return 'projection', False
        return 'extraction', False
    if '/solver/' in path: return 'solver', False
    if path in {'server/pyproject.toml', 'server/uv.lock', 'server/shuxueshuo_server/__init__.py'}: return 'source', False
    if path in {'server/shuxueshuo_server/main.py', 'server/shuxueshuo_server/wechat_jssdk.py'}: return None, False
    if '/review/' in path:
        if Path(path).stem in {'api', 'worker', 'versions'}: return None, False
        if Path(path).stem == 'problem_edit': return 'extraction', False
        if Path(path).stem == 'ocr': return 'observation', False
        return 'source', False
    return 'source', True


def spec_parts(source):
    """Separate typed SPEC presentation fields without hiding executable changes."""
    tree = ast.parse(source)
    sections = {'lesson': [], 'visual': []}
    class Split(ast.NodeTransformer):
        def visit_Call(self, node):
            name = node.func.id if isinstance(node.func, ast.Name) else ''
            if name.endswith(('SpecSource', 'MethodSpec', 'MacroSpec', 'RecipeSpec')):
                kept = []
                for keyword in node.keywords:
                    stage = 'lesson' if keyword.arg in TEACHING_FIELDS else 'visual' if keyword.arg in VISUAL_FIELDS else None
                    if stage:
                        sections[stage].append(ast.dump(keyword, include_attributes=False))
                    else:
                        kept.append(keyword)
                node.keywords = kept
            return self.generic_visit(node)
    tree = Split().visit(tree)
    return {'solver': digest(ast.dump(tree, include_attributes=False)), **{key: digest(value) for key, value in sections.items()}}


def collect(root=REPO, config=None):
    if config is None:
        from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
        config = SolverRuntimeConfig.from_sources(llm_provider='deepseek', allow_same_problem_few_shot=False)
    resources = {key: {} for key in KEYS}
    unknown = []
    observed = inventory(root)
    for path, hashed in observed.items():
        stage, fallback = resource_owner(path)
        if stage is None: continue
        if fallback: unknown.append({'path': path, 'stage': stage})
        if '/solver/runtime/' in path and path.endswith('.py') and ('/methods/' in path or '/macros/' in path or '/recipes/' in path):
            parts = spec_parts((root / path).read_text())
            for owner, value in parts.items(): resources[owner][path + '#' + owner] = value
        else:
            resources[stage][path] = hashed
    if inventory(root) != observed:
        raise ValueError('build.source_changed: 依赖探测期间文件变化')
    settings = {key: {} for key in KEYS}
    settings['observation'] = {
        'mode': 'fast-pass',
        'python': os.environ.get('REVIEW_OCR_PYTHON', str(root / 'server/.venv-ocr/bin/python')),
    }
    from shuxueshuo_server.solver.extraction.multimodal_provider import vision_effective_config
    settings['extraction'] = {**vision_effective_config(config), 'attempts': 3}
    model = config.llm_model or config.deepseek_model
    settings['solver'] = {
        'model': model, 'endpoint_hash': digest(config.deepseek_base_url),
        'thinking': 'low', 'max_attempts': config.max_llm_attempts,
        'few_shot_mode': config.functional_few_shot_mode,
        'argument_encoding': config.argument_encoding,
    }
    settings['lesson'] = {'model': model, 'endpoint_hash': digest(config.deepseek_base_url), 'thinking': 'disabled'}
    stages = {key: {'resources': resources[key], 'config': settings[key]} for key in KEYS}
    return {'schema_version': 'review-dependency-snapshot/v1', 'stages': stages, 'fingerprint': digest(stages), 'unclassified_resources': unknown}


def probe():
    """Fresh interpreter owns discovery, imports, and effective configuration.

    Keeping even the inventory algorithm in the API process would miss newly
    registered directories after a code edit. No generated results are cached.
    """
    result = subprocess.run([sys.executable, '-m', 'shuxueshuo_server.review.dependencies'],
                            cwd=REPO / 'server', capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError('build.dependencies_invalid: 当前代码或配置无法生成依赖指纹')
    return json.loads(result.stdout)


def stage_inputs(doc, stage):
    result = {}
    for owner, name in INPUTS[stage]:
        ref = next((a for a in reversed(doc['artifacts']) if a['stage'] == owner and a['name'] == name), None)
        if ref is None: raise ValueError(f'build.input_missing: {owner}/{name}')
        result[owner + '/' + name] = ref['sha256']
    return result


def manifest(doc, stage, snapshot):
    body = {'schema_version': CONTRACT, 'stage': stage, 'inputs': stage_inputs(doc, stage), **snapshot['stages'][stage]}
    return {**body, 'fingerprint': digest(body)}


def changes(doc, snapshot):
    reasons = []
    for record in doc['stages']:
        stage = record['id']
        old = record.get('manifest')
        if not old or old.get('schema_version') != CONTRACT:
            reasons.append({'stage': stage, 'code': 'build.version_unknown', 'message': '缺少可验证的阶段版本记录'})
            continue
        current = snapshot['stages'][stage]
        for path in sorted(old['resources'].keys() | current['resources'].keys()):
            if old['resources'].get(path) != current['resources'].get(path):
                reasons.append({'stage': stage, 'code': 'build.resource_changed', 'message': path})
        if old['config'] != current['config']:
            reasons.append({'stage': stage, 'code': 'build.config_changed', 'message': '有效生成配置变化'})
        try:
            if old['inputs'] != stage_inputs(doc, stage):
                reasons.append({'stage': stage, 'code': 'build.input_changed', 'message': '阶段输入变化'})
        except ValueError as exc:
            reasons.append({'stage': stage, 'code': 'build.input_missing', 'message': str(exc)})
    return reasons


if __name__ == '__main__':
    print(json.dumps(collect(), ensure_ascii=False))
