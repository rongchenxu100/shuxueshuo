"""Bounded rereading of schematic graphs, using untrusted boxes only as hints."""

import re
from hashlib import sha256
from io import BytesIO

from jsonschema import Draft202012Validator
from PIL import Image

from ..graph_lesson.stage_one.extraction import scopes
from ..problem_understanding.identity import revision
from .figures import pixel_box
from .identity import candidate_schema
from .storage import SearchError

MAX_DETAILS = 8
_GRAPH_UNCERTAINTY = re.compile(r'^(/root(?:/children/\d+)*/goals/\d+)/(?:source_graph|options/\d+)/uncertainties/\d+$')


def plan_details(workflow, original):
    """Never infer facts or repair uncertainty. Select crops for a fresh reading.

    Only complete, single-crop schematic selections with graph uncertainties
    qualify. An incomplete page, non-graph uncertainty or missing box stops here.
    All graphs are included so the second reading cannot favour one option.
    """
    candidate = workflow.get('candidate')
    diagnostics = workflow.get('diagnostics', [])
    if (workflow.get('status') != 'needs_confirmation' or workflow.get('source_reviewed') or
            not diagnostics or not all(d.get('action') == 'needs_confirmation' and
                _GRAPH_UNCERTAINTY.fullmatch(d.get('path', '')) for d in diagnostics) or
            not Draft202012Validator(candidate_schema()).is_valid(candidate)):
        return None
    public = candidate['public_content']
    if public['completeness'] != 'complete' or public['privacy'] != 'separated' or public['figure'] != 'represented':
        return None
    goals = [(f'{path}/goals/{i}', goal) for path, scope, _ in scopes(candidate['root'])
             for i, goal in enumerate(scope.get('goals', []))]
    if not goals or any(g['kind'] != 'select_function_graph' or not g.get('source_graph') for _, g in goals):
        return None
    choices = [c for s in public['scopes'] for c in s['choices']]
    if ([c['target_ref'] for c in choices] != [ref for ref, _ in goals] or
            any(c['status'] != 'complete' for c in choices)):
        return None
    statements = public.get('statement_figure_regions', [])
    options = public.get('figure_regions', [])
    if ([r['target_ref'] for r in statements] != [ref for ref, _ in goals] or
            [(r['target_ref'], r['option_id'], r['label']) for r in options] !=
            [(ref, o['option_id'], o['label']) for ref, g in goals for o in g['options']]):
        return None
    hints = [(f'/public_content/{field}/{i}', region['box']) for field in
             ('statement_figure_regions', 'figure_regions') for i, region in enumerate(public[field])]
    if not 1 <= len(hints) <= MAX_DETAILS:
        return None
    regions = []
    with Image.open(BytesIO(original)) as picture:
        for ref, box in hints:
            try:
                left, top, right, bottom = pixel_box(box, picture.size)
            except SearchError:
                return None
            if min(right-left, bottom-top) < 32:
                return None
            # Preserve nearby ticks/labels; snapping also fixes the exact mapping.
            margin = max(8, round(min(right-left, bottom-top)*0.08))
            pixels = [max(0, left-margin), max(0, top-margin),
                      min(picture.width, right+margin), min(picture.height, bottom+margin)]
            regions.append({'region_ref': ref, 'box': [v/picture.size[i % 2] for i, v in enumerate(pixels)]})
    return {'schema_version': 'search-graph-detail-plan/v1', 'source_sha256': sha256(original).hexdigest(),
            'candidate_revision': revision(candidate), 'regions': regions}


def detail_crops(original, regions):
    """Exact original pixels and explicit crop provenance; no resampling/redrawing."""
    if not isinstance(regions, (list, tuple)) or not 1 <= len(regions) <= MAX_DETAILS:
        raise ValueError('image_input.invalid_details')
    result, refs = [], set()
    with Image.open(BytesIO(original)) as picture:
        for index, region in enumerate(regions):
            if (not isinstance(region, dict) or set(region) != {'region_ref', 'box'} or
                    not isinstance(region['region_ref'], str) or not re.fullmatch(
                        r'/public_content/(?:statement_figure_regions|figure_regions)/\d+', region['region_ref']) or
                    region['region_ref'] in refs):
                raise ValueError('image_input.invalid_details')
            refs.add(region['region_ref'])
            try:
                box = pixel_box(region['box'], picture.size)
            except (SearchError, TypeError):
                raise ValueError('image_input.invalid_details') from None
            if min(box[2]-box[0], box[3]-box[1]) < 32:
                raise ValueError('image_input.invalid_details')
            crop = picture.crop(box)
            output = BytesIO()
            crop.save(output, format='PNG')
            content = output.getvalue()
            view = {'image_id': f'detail-{index+1}', 'kind': 'detail', 'sha256': sha256(content).hexdigest(),
                    'width': crop.width, 'height': crop.height, 'box': region['box'], 'pixel_box': list(box),
                    'source_image_id': 'original', 'source_sha256': sha256(original).hexdigest(),
                    'region_ref': region['region_ref']}
            result.append((view, content))
    return result
