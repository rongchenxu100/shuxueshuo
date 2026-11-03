"""Repair reviewed figure bounds without asking the model to rewrite the question."""

import json
import re
from copy import deepcopy
from dataclasses import replace

from jsonschema import Draft202012Validator, ValidationError

from ..problem_understanding.candidate_common import strict_json
from ..problem_understanding.identity import revision
from ..problem_understanding.review_contract import pointer
from ..problem_understanding.workflow import RepairResponseError
from ..solver.extraction.multimodal_provider import MultimodalExtractionPrompt

CONTRACT = 'search-figure-box-repair/v1'
BOX_PATH = re.compile(r'/public_content/figure_detection/regions/(0|[1-9][0-9]*)/box')
SYSTEM = '''你只负责修正题目配图的裁框，不重新提取题干，也不求解。
根据同一题图和 review_findings，只修改待修区域的 box。其它区域、题干、公式、目标和选项身份由程序保留。
box 是同一裁剪框的归一化坐标，依次为左、上、右、下，范围 0 到 1；与 processed/original 像素尺寸无关。
完整包含该图的曲线、坐标轴、箭头、刻度和原标签，留出适当空隙；不把相邻题图、解析和答案划入。
base_revision、path、figure_id 必须照抄；只输出指定的坐标补丁 JSON，不输出完整题目或图形数学事实。
如果不能确定边界或图号对应，box 填 null 并在 uncertainties 说明，不按解析或答案猜测。清楚时 uncertainties 填 []。'''


def authorized_regions(candidate, diagnostics):
    """Only exact box-only source-review grants enter this optional path."""
    if not candidate or not diagnostics:
        return []
    public = candidate.get('public_content', {})
    if public.get('figure') != 'unrepresented' or public.get('figure_detection', {}).get('status') != 'present':
        return []
    rows = {}
    for issue in diagnostics:
        path = issue.get('path', '')
        if (issue.get('stage') != 'review' or issue.get('code') != 'wrong_public_content' or
                issue.get('action') != 'repair' or not BOX_PATH.fullmatch(path)):
            return []
        try:
            region = pointer(candidate, path.rsplit('/', 1)[0])
        except (KeyError, ValueError, IndexError, TypeError):
            return []
        if region.get('role') not in {'statement', 'option'}:
            return []
        rows[path] = region
    return list(rows.items())


def patch_schema(candidate, regions):
    items = []
    for path, region in regions:
        items.append({'type': 'object', 'additionalProperties': False,
                      'required': ['path', 'figure_id', 'box', 'uncertainties'], 'properties': {
                          'path': {'const': path}, 'figure_id': {'const': region['id']},
                          'box': {'anyOf': [
                              {'type': 'array', 'minItems': 4, 'maxItems': 4,
                               'items': {'type': 'number', 'minimum': 0, 'maximum': 1}},
                              {'type': 'null'}]},
                          'uncertainties': {'type': 'array', 'maxItems': 4,
                                            'items': {'type': 'string', 'minLength': 1, 'maxLength': 256}}}})
    return {'title': CONTRACT, 'type': 'object', 'additionalProperties': False,
            'required': ['base_revision', 'boxes'], 'properties': {
                'base_revision': {'const': revision(candidate)},
                'boxes': {'type': 'array', 'minItems': len(items), 'maxItems': len(items),
                          'prefixItems': items, 'items': False}}}


def build_request(base, candidate, diagnostics, feedback):
    regions = authorized_regions(candidate, diagnostics)
    if not regions:
        return None
    schema = patch_schema(candidate, regions)
    payload = {'response_schema': schema, 'base_revision': revision(candidate),
               'readonly_statement': candidate['original_text'],
               'regions': candidate['public_content']['figure_detection']['regions'],
               'review_findings': list(diagnostics), 'repair_feedback': list(feedback)}
    return replace(base, contract_version=CONTRACT, contract_schema=schema,
                   prompt=MultimodalExtractionPrompt(SYSTEM, json.dumps(payload, ensure_ascii=False),
                                                     '只返回获准修改的图框坐标；不要重写整份题目。'))


def apply_response(request, raw, candidate, diagnostics):
    if request.contract_version != CONTRACT:
        return raw
    regions = authorized_regions(candidate, diagnostics)
    schema = patch_schema(candidate, regions)
    try:
        if not regions or request.contract_schema != schema:
            raise ValueError('repair.stale_box_authority')
        patch = strict_json(raw)
        Draft202012Validator(schema).validate(patch)
    except (ValueError, RecursionError, ValidationError) as exc:
        raise RepairResponseError([{
            'stage': 'repair', 'code': 'figure.invalid_box_patch', 'path': '', 'action': 'repair',
            'message': '只返回指定 base_revision 及 boxes，照抄获准的 path 和 figure_id；'
                       '坐标须为 0 到 1 的四个数，不附带题干、选项或其它字段。',
        }]) from exc
    issues = []
    for row in patch['boxes']:
        box = row['box']
        if box is None or row['uncertainties']:
            issues.append({'stage': 'source', 'code': 'figure.box_uncertain', 'path': row['path'],
                           'action': 'needs_confirmation',
                           'message': '；'.join(row['uncertainties']) or '无法确认这幅题图的完整边界。'})
        elif box[0] >= box[2] or box[1] >= box[3]:
            issues.append({'stage': 'repair', 'code': 'figure.invalid_box_patch', 'path': row['path'],
                           'action': 'repair', 'message': '左边界必须小于右边界，上边界必须小于下边界。'})
    if issues:
        raise RepairResponseError(issues)
    merged = deepcopy(candidate)
    for row in patch['boxes']:
        pointer(merged, row['path'].rsplit('/', 1)[0])['box'] = row['box']
    return json.dumps(merged, ensure_ascii=False)
