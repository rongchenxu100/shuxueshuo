"""Read bounded figure crops and merge only figure facts into immutable text."""

import json
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from io import BytesIO

from jsonschema import Draft202012Validator
from PIL import Image

from ..graph_lesson.stage_one import contracts
from ..graph_lesson.stage_one.runner import build_image_request
from ..problem_understanding.candidate_common import strict_json
from ..problem_understanding.identity import revision
from ..problem_understanding.review_contract import pointer
from ..problem_understanding.workflow_diagnostics import review_diagnostics
from ..problem_understanding.workflow_ledger import WorkflowStop
from ..solver.extraction.multimodal_evidence import MultimodalImageInput
from ..solver.extraction.multimodal_provider import (
    MultimodalExtractionPrompt,
    MultimodalProviderImage,
)
from .figures import pixel_box
from .text_extraction import (
    TextExtractionContract,
    graph_goals,
    inventory_issues,
    reading_regions,
)

FIGURE_CONTRACT = 'search-figure-extraction/v1'
PROMPT_PATH = contracts.ROOT / 'internal/llm-prompts/search-figure-extraction.md'
REVIEW_PROMPT_PATH = contracts.ROOT / 'internal/llm-prompts/search-figure-review.md'
MAX_FIGURES = 8
MAX_SIDE = 960
MAX_IMAGE_BYTES = 384 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024


def figure_schema(base):
    graph = contracts.schema()['$defs']['FunctionGraphGoal']['oneOf'][0]['properties']
    choices = graph['options']['items']['properties']['facts']
    properties = {'figure_id': {'type': 'string'},
                  'facts': {'anyOf': [deepcopy(choices), {'type': 'null'}],
                            'description': '只记录图中可核对的受支持事实；示意图不要求解析式、全定义域或图外性质。'},
                  'uncertainties': {'type': 'array', 'maxItems': 16,
                                    'items': {'type': 'string', 'minLength': 1, 'maxLength': 256},
                                    'description': '仅记录妨碍核对 facts 或图文对应的实际疑点。'
                                                   '未提供解析式、未展示全图等适用范围说明不属于疑点；事实清楚时填 []。'}}
    items = []
    for region in reading_regions(base):
        row = {'type': 'object', 'additionalProperties': False,
               'required': list(properties), 'properties': deepcopy(properties)}
        row['properties']['figure_id'] = {'const': region['id']}
        items.append(row)
    return {'type': 'object', 'additionalProperties': False,
            'required': ['base_revision', 'figures'], 'properties': {
                'base_revision': {'const': revision(base)},
                'figures': {'type': 'array', 'minItems': len(items), 'maxItems': len(items),
                            'prefixItems': items, 'items': False}}}


def figure_review_schema():
    schema = contracts.review_schema()
    finding = schema['properties']['findings']['items']['properties']
    finding['path'] = {'type': 'string', 'pattern': '^/figures/[0-9]+(?:/.*)?$'}
    finding['kind'] = {'enum': ['wrong_expression', 'wrong_scope', 'unsupported_addition',
                              'missing_condition', 'missing_figure', 'unreadable', 'ambiguous']}
    return schema


def supported_inventory(base):
    if inventory_issues(base):
        return False
    public = base['public_content']
    regions = reading_regions(base)
    goals = dict(graph_goals(base))
    return (public['completeness'] == 'complete' and public['privacy'] == 'separated' and
            0 < len(regions) <= MAX_FIGURES and
            all(r['target_ref'] in goals for r in regions) and
            all(c['status'] in {'complete', 'none'} for scope in public['scopes'] for c in scope['choices']))


def crop_figures(content, base, *, source_kind):
    """Keep the full declared box, resizing only for a bounded image payload."""
    regions = reading_regions(base)
    if not 0 < len(regions) <= MAX_FIGURES:
        raise ValueError('figure.invalid_region_count')
    rows = []
    per_image = min(MAX_IMAGE_BYTES, MAX_TOTAL_BYTES // len(regions))
    with Image.open(BytesIO(content)) as source:
        for region in regions:
            pixels = pixel_box(region['box'], source.size)
            crop = source.crop(pixels)
            if min(crop.size) < 16:
                raise ValueError('figure.crop_too_small')
            crop.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
            while True:
                buffer = BytesIO()
                crop.save(buffer, format='PNG', optimize=True)
                encoded = buffer.getvalue()
                if len(encoded) <= per_image:
                    break
                if min(crop.size) < 64:
                    raise ValueError('figure.image_budget_exceeded')
                crop = crop.resize(tuple(max(1, round(v * .8)) for v in crop.size), Image.Resampling.LANCZOS)
            view = {'figure_id': region['id'], 'source_kind': source_kind,
                    'source_sha256': sha256(content).hexdigest(), 'box': region['box'],
                    'pixel_box': list(pixels), 'width': crop.width, 'height': crop.height,
                    'sha256': sha256(encoded).hexdigest(), 'bytes': len(encoded)}
            rows.append((view, encoded))
    return rows


def build_figure_request(processed, base, store, *, original=None):
    rows = crop_figures(original if original is not None else processed, base,
                        source_kind='original' if original is not None else 'processed')
    images = []
    for view, pixels in rows:
        artifact = store.put_bytes(kind='search_figure', content=pixels, media_type='image/png', suffix='.png')
        images.append(MultimodalProviderImage(view['figure_id'], 'page-1', 'zoom', artifact, pixels,
                                              view['width'], view['height']))
    # The full question remains provenance only; it is not sent again.
    request = build_image_request(processed, store)
    pack = replace(request.evidence_pack, selection_id='figure-crops', images=tuple(MultimodalImageInput(
        i.image_id, i.page_id, i.role, i.artifact, i.width, i.height) for i in images))
    context = []
    for ref, goal in graph_goals(base):
        statements = [scope['statement'] for scope in base['public_content']['scopes']
                      if ref.startswith(scope['scope_ref'] + '/')]
        context.append({'target_ref': ref, 'statements': statements, 'goal': goal})
    schema = figure_schema(base)
    manifest = {'base_revision': revision(base), 'question_sha256': sha256(processed).hexdigest(),
                'views': [view for view, _ in rows]}
    payload = {'response_schema': schema, 'base_revision': revision(base), 'readonly_context': context,
               'regions': reading_regions(base), 'image_inputs': manifest}
    return replace(request, evidence_pack=pack, images=tuple(images), contract_version=FIGURE_CONTRACT,
                   contract_schema=schema, prompt=MultimodalExtractionPrompt(
                       PROMPT_PATH.read_text(), json.dumps(payload, ensure_ascii=False),
                       '逐图补充数学事实，只返回指定 JSON；不输出或改写题干。')), manifest


def merge_figures(base, supplement):
    Draft202012Validator(figure_schema(base)).validate(supplement)
    merged = deepcopy(base)
    public = merged['public_content']
    public['figure_regions'], public['statement_figure_regions'] = [], []
    for region, value in zip(reading_regions(base), supplement['figures'], strict=True):
        if value['uncertainties'] or value['facts'] is None:
            raise ValueError('figure.uncertain_facts')
        goal = pointer(merged, region['target_ref'])
        if region['role'] == 'option':
            option = next(o for o in goal['options'] if o['option_id'] == region['option_id'])
            option.update(facts=deepcopy(value['facts']), uncertainties=[])
            public['figure_regions'].append({k: region[k] for k in ('target_ref', 'option_id', 'label', 'box')})
        else:
            goal['source_graph'].update(facts=deepcopy(value['facts']), uncertainties=[])
            public['statement_figure_regions'].append({k: region[k] for k in ('target_ref', 'box')})
    # Region detection order may be spatial; publication order follows original goals/options.
    order = {(ref, o['option_id']): i for i, (ref, o) in enumerate(
        (ref, option) for ref, goal in graph_goals(base) for option in goal['options'])}
    public['figure_regions'].sort(key=lambda r: order[(r['target_ref'], r['option_id'])])
    goal_order = {ref: i for i, (ref, _) in enumerate(graph_goals(base))}
    public['statement_figure_regions'].sort(key=lambda r: goal_order[r['target_ref']])
    public['figure'] = 'represented'
    public.pop('figure_detection', None)
    return merged


def unread_fact_fields(facts):
    """Required evidence can be uncertain even when the free-text list is empty."""
    shape = facts['shape']
    if shape == 'unknown':
        return ['shape']
    if shape == 'shown_monotone_curve':
        points, directions = [('x_intercept', facts['x_intercept'])], ['direction']
    elif shape == 'two_straight_branches':
        points, directions = [('vertex', facts['vertex'])], ['left_direction', 'right_direction']
    else:
        # G3 may exclude a choice using a labelled point alone; its optional
        # outer direction/symmetry need not be known. Supplied coordinates do.
        points = [(f'landmarks/{i}', point) for i, point in enumerate(facts['landmarks'])]
        directions = []
    return ([f'{path}/evidence' for path, point in points if point['evidence'] in ('estimated', 'unknown')]
            + [key for key in directions if facts[key] == 'unknown'])


class FigureExtractionContract(TextExtractionContract):
    def __init__(self, base):
        self.base = deepcopy(base)

    def schema(self):
        return figure_schema(self.base)

    def frozen_files(self):
        files = super().frozen_files()
        files[str(REVIEW_PROMPT_PATH.relative_to(contracts.ROOT))] = sha256(REVIEW_PROMPT_PATH.read_bytes()).hexdigest()
        return files

    def validate_request(self, request, registry, mode):
        if registry or request.contract_version != FIGURE_CONTRACT or request.contract_schema != self.schema():
            raise WorkflowStop('workflow.unsupported_or_stale_contract')

    def parse(self, raw, **kwargs):
        try:
            candidate = strict_json(raw)
        except (ValueError, RecursionError) as exc:
            return {'contract_valid': False, 'reports': {'json': {'ok': False, 'issues': [str(exc)]}}}
        issues = [{'path': '/' + '/'.join(map(str, e.absolute_path)), 'code': 'schema.invalid', 'message': e.message}
                  for e in Draft202012Validator(self.schema()).iter_errors(candidate)]
        return {'contract_valid': not issues, 'reports': {'ir': {'ok': not issues, 'issues': issues}}}

    def diagnose(self, parsed, candidate):
        from ..problem_understanding.workflow_diagnostics import diagnose

        issues = diagnose(parsed, candidate)
        if not parsed['contract_valid']:
            return issues
        for i, value in enumerate(candidate['figures']):
            if value['uncertainties'] or value['facts'] is None:
                issues.append({'stage': 'source', 'code': 'figure.uncertain_facts', 'path': f'/figures/{i}',
                               'message': '；'.join(value['uncertainties']) or '图形事实无法确认。',
                               'action': 'needs_confirmation'})
            else:
                issues.extend({'stage': 'source', 'code': 'figure.uncertain_facts',
                               'path': f'/figures/{i}/facts/{field}',
                               'message': '图形的关键坐标或方向尚未读清，不能将估读结果作为精确事实。',
                               'action': 'needs_confirmation'}
                              for field in unread_fact_fields(value['facts']))
        return issues

    def request_for(self, base, stage, candidate, registry, diagnostics=(), feedback=(), *, validation=None):
        payload = json.loads(base.prompt.user_prefix)
        payload['response_schema'] = figure_review_schema() if stage == 'review' else self.schema()
        payload['candidate'] = candidate
        if diagnostics:
            payload['diagnostics'] = diagnostics
        if feedback:
            payload['review_feedback'] = list(feedback)
        return replace(base, contract_schema=payload['response_schema'],
                       contract_version='search-figure-review/v1' if stage == 'review' else FIGURE_CONTRACT,
                       prompt=replace(base.prompt,
                                      system=REVIEW_PROMPT_PATH.read_text() if stage == 'review' else base.prompt.system,
                                      user_prefix=json.dumps(payload, ensure_ascii=False),
                                      user_suffix='核对各图形事实与图文对应，只返回复核 JSON。'
                                      if stage == 'review' else '只修正图形事实，不输出题干。'))

    def validate_review(self, raw, candidate):
        review = strict_json(raw)
        Draft202012Validator(figure_review_schema()).validate(review)
        for finding in review['findings']:
            pointer(candidate, finding['path'])
        return review

    def review_diagnostics(self, review, candidate):
        return review_diagnostics(review, candidate)

    def invalid_review_feedback(self):
        return [{'code': 'review.invalid_response',
                 'message': '上一轮复核未通过格式校验。重新对照同一组裁片核对同一 candidate，'
                            '只输出 status 和 findings；不要回传 base_revision、figures、candidate 或 type。'
                            'findings.path 必须指向 candidate 中已有的 /figures/序号/... 字段。'}]

    def result_fields(self, current):
        return {'output_contract': FIGURE_CONTRACT}


def verify_reading(directory, result):
    """Reconstruct a merged candidate from two independently reviewed, pixel-bound records."""
    binding = result['figure_reading']
    name = binding['workflow_directory']
    if name not in {'workflow-figures', 'workflow-figures-original'}:
        raise ValueError('figure.invalid_workflow')
    text = json.loads((directory / 'workflow/workflow-result.json').read_text())
    graph = json.loads((directory / name / 'workflow-result.json').read_text())
    if not all(w.get('status') == 'reviewed_candidate' and w.get('source_reviewed') and
               w.get('review', {}).get('revision') == revision(w['candidate']) for w in (text, graph)):
        raise ValueError('figure.unreviewed_component')
    base = text['candidate']
    if (binding['base_revision'] != revision(base) or binding['figure_revision'] != revision(graph['candidate']) or
            merge_figures(base, graph['candidate']) != result['public_candidate']):
        raise ValueError('figure.merge_mismatch')
    processed = (directory / 'question.png').read_bytes()
    question_hash = sha256(processed).hexdigest()
    text_ledger = json.loads((directory / 'workflow/ledger.json').read_text())
    if (text_ledger['identity']['binding']['images'] != [question_hash] or
            result['sent_image_sha256'] != [question_hash] or result['question_sha256'] != question_hash):
        raise ValueError('figure.text_image_mismatch')
    kind = 'original' if name.endswith('-original') else 'processed'
    content = (directory / 'original.png').read_bytes() if kind == 'original' else processed
    rows = crop_figures(content, base, source_kind=kind)
    manifest = {'base_revision': revision(base), 'question_sha256': question_hash,
                'views': [view for view, _ in rows]}
    ledger = json.loads((directory / name / 'ledger.json').read_text())
    if (binding['image_inputs'] != manifest or
            ledger['identity']['binding']['images'] != [v['sha256'] for v, _ in rows]):
        raise ValueError('figure.crop_image_mismatch')
