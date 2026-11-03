"""Install source-bound option crops only after the whole photo review passes."""
import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from PIL import Image

from ..problem_understanding.identity import revision
from . import figures
from .identity import public_structure_errors
from .question_image import expected_image_hashes, image_inputs, question_png


def install(directory, result):
    candidate = result.get('public_candidate')
    if (result.get('status') != 'reviewed_candidate' or not result.get('source_reviewed') or
            not candidate or result.get('reviewed_candidate_revision') != revision(candidate) or
            candidate['public_content']['figure'] != 'represented' or
            candidate['public_content']['completeness'] != 'complete' or
            any(group['status'] not in {'complete', 'none'} for scope in candidate['public_content']['scopes']
                for group in scope['choices']) or
            public_structure_errors(candidate)):
        return None
    if result.get('pipeline') == 'text-then-figures/v1':
        from .figure_extraction import verify_reading

        verify_reading(Path(directory), result)
    content, source = figures.source_image(directory)
    if (result.get('stored_original_sha256') is not None and
            result['stored_original_sha256'] != source['sha256']):
        raise ValueError('figure.original_changed')
    with Image.open(BytesIO(content)) as picture:
        sent = question_png(picture) if source['quality'] == 'original' else content
        expected = expected_image_hashes(result)
        if (not expected or sha256(sent).hexdigest() != result['question_sha256'] or
                result['sent_image_sha256'] != expected):
            raise ValueError('figure.review_image_mismatch')
        if result.get('image_inputs') is not None:
            plan = result.get('detail_reading')
            if plan:
                from .graph_details import plan_details
                first = json.loads((Path(directory)/'workflow/workflow-result.json').read_text())
                actual = json.loads((Path(directory)/'workflow-detail/ledger.json').read_text())
                if (plan != plan_details(first, content) or result.get('workflow_directory') != 'workflow-detail' or
                        actual['identity']['binding']['images'] != expected):
                    raise ValueError('figure.review_image_mismatch')
            if (source['quality'] != 'original' or result['image_inputs'] !=
                    image_inputs(sent, content, detail_regions=plan['regions'] if plan else ())):
                raise ValueError('figure.review_image_mismatch')
        rows = [{'id': 'original', 'role': 'source', 'scope_ref': '/root', 'box': [0, 0, 1, 1]}]
        identity, statement_identity = [], []
        for i, region in enumerate(candidate['public_content'].get('statement_figure_regions', [])):
            row = {**region, 'id': f'statement-{i+1}', 'role': 'statement',
                   'scope_ref': region['target_ref'].rsplit('/goals/', 1)[0]}
            crop = BytesIO()
            picture.crop(figures.pixel_box(row['box'], picture.size)).save(crop, format='PNG')
            rows.append(row)
            statement_identity.append({'target_ref': row['target_ref'], 'sha256': sha256(crop.getvalue()).hexdigest()})
        for i, region in enumerate(candidate['public_content']['figure_regions']):
            row = {**region, 'id': f'choice-{i+1}', 'role': 'option',
                   'scope_ref': region['target_ref'].rsplit('/goals/', 1)[0]}
            box = figures.pixel_box(row['box'], picture.size)
            crop = BytesIO()
            picture.crop(box).save(crop, format='PNG')
            rows.append(row)
            identity.append({key: row[key] for key in ('target_ref', 'option_id', 'label')} |
                            {'sha256': sha256(crop.getvalue()).hexdigest()})
    manifest = {'schema_version': figures.VERSION, 'source': source, 'figures': rows}
    figures.validate_manifest(manifest, source)
    path = Path(directory)/figures.MANIFEST
    if path.is_symlink():
        raise ValueError('figure.manifest_symlink')
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    binding = {'candidate_revision': revision(candidate), 'source_sha256': source['sha256'], 'option_figures': identity}
    if statement_identity:
        binding['statement_figures'] = statement_identity
    return binding
