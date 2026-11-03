"""Single-image text extraction with an explicit, non-mathematical figure inventory."""

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator

from ..graph_lesson.stage_one import contracts
from ..graph_lesson.stage_one.extraction import scopes
from ..graph_lesson.stage_one.runner import build_image_request
from ..problem_understanding.candidate_common import strict_json
from ..problem_understanding.identity import revision
from ..problem_understanding.review_contract import pointer
from ..problem_understanding.workflow_ledger import WorkflowStop
from ..solver.extraction.multimodal_provider import MultimodalExtractionPrompt
from . import figure_box_repair
from .extraction import PUBLIC_PROMPT_PATH, REVIEW_CONTRACT, SearchStageOneContract, review_schema
from .identity import candidate_schema, public_structure_errors

TEXT_CONTRACT = 'search-text-extraction/v1'
GRAPH_REVIEW_PROMPT = contracts.ROOT / 'internal/llm-prompts/search-graph-text-review.md'
SCHEMATIC_COMPARISON = (
    '选项为示意图、部分图象或大致图象时使用 rough_shape，即使题干给出完整解析式。'
    '它表示按已核对的图形特征排除选项；已知目标函数不等于已知每个选项的完整规则。'
    'exact_equivalence 需要每个选项的完整规则与定义域，不能仅凭裁图中的有限特征声明精确等价。'
)


def text_schema():
    schema = candidate_schema()
    schema['title'] = TEXT_CONTRACT
    public = schema['properties']['public_content']
    public['required'].append('figure_detection')
    public['properties']['figure']['enum'] = ['not_required', 'unrepresented']
    public['properties']['figure']['description'] = '需要读取配图时为 unrepresented，否则为 not_required。'
    for field in ('figure_regions', 'statement_figure_regions'):
        del public['properties'][field]
    goal = schema['$defs']['FunctionGraphGoal']['oneOf'][0]
    goal['description'] = '只抄题给函数式、变换、所求和选项标签；图形事实另行提取。'
    goal['properties']['comparison']['description'] = SCHEMATIC_COMPARISON
    for entry in (goal['properties']['options']['items'], goal['properties']['source_graph']):
        for field in ('facts', 'uncertainties'):
            del entry['properties'][field]
            entry['required'].remove(field)
    goal['properties']['source_graph']['description'] = '只给原图时保留函数名，不补造解析式。'
    return schema


def graph_goals(candidate):
    return [(f'{path}/goals/{i}', goal) for path, scope, _ in scopes(candidate['root'])
            for i, goal in enumerate(scope.get('goals', [])) if goal['kind'] == 'select_function_graph']


def reading_regions(candidate):
    return [r for r in candidate['public_content']['figure_detection']['regions'] if r['role'] != 'workspace']


def graph_only_review(candidate):
    """A parsed pictured-choice goal needs no unrelated expression catalogue."""
    if not candidate or candidate.get('public_content', {}).get('figure') != 'unrepresented':
        return False
    if candidate['public_content']['figure_detection']['status'] != 'present':
        return False
    goals = []
    for _, scope, _ in scopes(candidate['root']):
        # Keep the general review for shared assumptions and mixed questions.
        if scope.get('facts'):
            return False
        definitions = scope.get('definitions', [])
        if definitions:
            from ..graph_lesson.function_graph import identical_function_definition

            local_goals = scope.get('goals', [])
            if (len(definitions) != 1 or len(local_goals) != 1 or
                    not identical_function_definition(local_goals[0], definitions[0])):
                return False
        goals.extend(scope.get('goals', []))
    return bool(goals) and all(g['kind'] == 'select_function_graph' for g in goals)


def inventory_issues(candidate):
    public = candidate['public_content']
    if public['figure'] == 'represented':
        # The merged candidate is checked through public_structure_errors and figure binding.
        return []
    detection = public['figure_detection']
    regions = detection['regions']
    path = '/public_content/figure_detection'
    if detection['status'] == 'uncertain':
        return [(path, '无法确认题图是否完整，请检查原照片中的配图。')]
    if ((detection['status'] == 'none' and regions) or
            (detection['status'] == 'present' and not regions)):
        return [(path, '配图状态与区域清单不一致。')]
    if len({r['id'] for r in regions}) != len(regions):
        return [(path, '配图编号重复。')]
    goals = dict(graph_goals(candidate))
    for i, region in enumerate(regions):
        box = region['box']
        if box[0] >= box[2] or box[1] >= box[3]:
            return [(f'{path}/regions/{i}/box', '配图区域为空。')]
        try:
            target = pointer(candidate, region['target_ref'])
        except (KeyError, ValueError, IndexError):
            return [(f'{path}/regions/{i}/target_ref', '配图没有对应的原题目标。')]
        if not isinstance(target, dict) or 'kind' not in target:
            return [(f'{path}/regions/{i}/target_ref', '配图没有对应的原题目标。')]
        if region['role'] == 'option':
            options = target.get('options', [])
            if not any(o.get('option_id') == region.get('option_id') and
                       o.get('label') == region.get('label') for o in options):
                return [(f'{path}/regions/{i}', '配图选项与原标签不对应。')]
        elif 'option_id' in region or 'label' in region:
            return [(f'{path}/regions/{i}', '题干图和作图区不能带选项身份。')]
    needed = reading_regions(candidate)
    if (goals or needed) and public['figure'] != 'unrepresented':
        return [('/public_content/figure', '需要读取的配图尚未补充，不能按无图题继续。')]
    if public['figure'] == 'unrepresented' and not needed:
        return [(path, '题干依赖的配图未完整定位。')]
    expected = [(ref, 'statement', None) for ref, g in goals.items() if 'source_graph' in g]
    expected += [(ref, 'option', o['option_id']) for ref, g in goals.items() for o in g['options']]
    actual = [(r['target_ref'], r['role'], r.get('option_id')) for r in needed]
    if goals and (len(actual) != len(expected) or set(actual) != set(expected)):
        return [(path, '须完整定位题干原图及各选项，不能漏图或重复绑定。')]
    return []


def build_text_request(content, store):
    request = build_image_request(content, store)
    schema = text_schema()
    return replace(request, contract_version=TEXT_CONTRACT, contract_schema=schema,
                   prompt=MultimodalExtractionPrompt(
                       contracts.SYSTEM + '\n\n' + PUBLIC_PROMPT_PATH.read_text(),
                       json.dumps({'response_schema': schema,
                                   'math_expression_catalog': contracts.expression_catalog()}, ensure_ascii=False),
                       '提取完整文字题意，并标记配图是否存在及其位置。只返回指定 JSON。'))


class TextExtractionContract(SearchStageOneContract):
    def schema(self):
        return text_schema()

    def validate_request(self, request, registry, mode):
        if registry or request.contract_version != TEXT_CONTRACT or request.contract_schema != self.schema():
            raise WorkflowStop('workflow.unsupported_or_stale_contract')

    def frozen_files(self):
        files = super().frozen_files()
        for name in ('text_extraction.py', 'figure_extraction.py', 'figure_box_repair.py', 'text_first.py'):
            path = Path(__file__).with_name(name)
            files[str(path.relative_to(contracts.ROOT))] = sha256(path.read_bytes()).hexdigest()
        prompt = contracts.ROOT / 'internal/llm-prompts/search-figure-extraction.md'
        files[str(prompt.relative_to(contracts.ROOT))] = sha256(prompt.read_bytes()).hexdigest()
        files[str(GRAPH_REVIEW_PROMPT.relative_to(contracts.ROOT))] = sha256(GRAPH_REVIEW_PROMPT.read_bytes()).hexdigest()
        return files

    def parse(self, raw, **kwargs):
        try:
            candidate = strict_json(raw)
        except (ValueError, RecursionError):
            return super().parse(raw, **kwargs)
        errors = list(Draft202012Validator(self.schema()).iter_errors(candidate))
        if errors:
            return {'contract_valid': False, 'reports': {'ir': {'ok': False, 'issues': [
                {'path': '/' + '/'.join(map(str, e.absolute_path)), 'code': 'schema.invalid',
                 'message': e.message} for e in errors[:16]]}}}
        if graph_goals(candidate):
            # A text-only graph goal is not a complete mathematical candidate.
            # Defer mathematical compilation until the independently read facts are merged.
            issues = public_structure_errors(candidate)
            # Classify pictured choices before spending calls on their facts.
            # A wrong classification must be repaired and reviewed in the text
            # workflow, never silently downgraded when merging reviewed figures.
            issues.extend((f'{ref}/comparison', SCHEMATIC_COMPARISON)
                          for ref, goal in graph_goals(candidate)
                          if goal['comparison'] != 'rough_shape')
            parsed = {'contract_valid': not issues, 'mathematics_pending': True,
                      'reports': {'ir': {'ok': not issues, 'issues': [
                          {'path': path, 'code': 'schema.invalid', 'message': message}
                          for path, message in issues]}}}
        else:
            parsed = super().parse(raw, **kwargs)
        parsed['revision'] = revision(candidate)
        return parsed

    def diagnose(self, parsed, candidate):
        diagnoses = super().diagnose(parsed, candidate)
        if Draft202012Validator(self.schema()).is_valid(candidate):
            diagnoses.extend({'stage': 'source', 'code': 'figure.inventory_uncertain', 'path': path,
                              'message': message, 'action': 'needs_confirmation'}
                             for path, message in inventory_issues(candidate))
        return diagnoses

    def request_for(self, base, stage, candidate, registry, diagnostics=(), feedback=(), *, validation=None):
        if stage == 'repair':
            patch = figure_box_repair.build_request(base, candidate, diagnostics, feedback)
            if patch is not None:
                return patch
        if stage == 'review' and graph_only_review(candidate):
            schema = review_schema()
            payload = {'response_schema': schema, 'candidate': candidate,
                       'graph_goal_schema': self.schema()['$defs']['FunctionGraphGoal']['oneOf'][0],
                       'code_validation': {'candidate_revision': revision(candidate),
                                           'notation_valid': bool(validation and validation['contract_valid']),
                                           'image_alignment_verified': False}}
            if feedback:
                payload['review_feedback'] = list(feedback)
            return replace(base, contract_version=REVIEW_CONTRACT, contract_schema=schema,
                           prompt=MultimodalExtractionPrompt(
                               GRAPH_REVIEW_PROMPT.read_text(), json.dumps(payload, ensure_ascii=False),
                               '完整核对文字题意与配图位置，只返回复核 JSON。'))
        outgoing = super().request_for(base, stage, candidate, registry, diagnostics, feedback, validation=validation)
        payload = json.loads(outgoing.prompt.user_prefix)
        schema = review_schema() if stage == 'review' else self.schema()
        payload['response_schema'] = schema
        if stage == 'review':
            payload['review_scope'] = '核对文字题意和配图清单；图中的数学事实尚未提取，不要求补写。'
            if candidate and graph_goals(candidate):
                payload['graph_comparison_rule'] = SCHEMATIC_COMPARISON
        return replace(outgoing, contract_schema=schema,
                       contract_version=outgoing.contract_version if stage == 'review' else TEXT_CONTRACT,
                       prompt=replace(outgoing.prompt, user_prefix=json.dumps(payload, ensure_ascii=False)))

    def repair_response(self, request, raw, candidate, diagnostics):
        return figure_box_repair.apply_response(request, raw, candidate, diagnostics)
