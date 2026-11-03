import json
from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from shuxueshuo_server.search import figures
from shuxueshuo_server.search.question_image import question_png
from shuxueshuo_server.search.storage import SearchError


@pytest.fixture
def source(tmp_path):
    # Light hollow endpoints and dashed lines deliberately challenge the 16-level
    # model preprocessing. Display must retain the exact original pixels.
    picture = Image.new('RGB', (400, 200), 'white')
    draw = ImageDraw.Draw(picture)
    draw.line((20, 110, 380, 110), fill='black', width=4)
    draw.ellipse((95, 95, 105, 105), outline=(240, 240, 240), width=1)
    for x in range(30, 370, 12):
        draw.line((x, 80, x + 5, 80), fill=(240, 240, 240), width=1)
    picture.save(tmp_path / 'original.png')
    (tmp_path / 'question.png').write_bytes(question_png(picture))
    return tmp_path


def reviewed_manifest(source):
    manifest = figures.manifest_for(source)
    for i, label in enumerate('AB'):
        manifest['figures'].append({'id': f'option-{label.lower()}', 'role': 'option',
                                    'scope_ref': '/root', 'target_ref': '/root/goals/0',
                                    'option_id': f'choice-{label.lower()}', 'label': label,
                                    'box': [i / 2, 0, (i + 1) / 2, 1]})
    (source / figures.MANIFEST).write_text(json.dumps(manifest))
    return manifest


def test_original_and_processed_have_separate_content_and_fallback(source):
    original = (source / 'original.png').read_bytes()
    processed = (source / 'question.png').read_bytes()
    shown = figures.present(source, 'abcdef012345')
    assert shown['source']['quality'] == 'original'
    assert figures.image_bytes(source, 'original', shown['content_id']) == original
    assert original != processed
    with Image.open(BytesIO(original)) as high, Image.open(BytesIO(processed)) as low:
        assert high.getpixel((100, 95)) == (240, 240, 240)
        assert low.getpixel((100, 95)) == 255  # preprocessing removed the pale ring
    (source / 'original.png').unlink()
    legacy = figures.present(source, 'abcdef012345')
    assert legacy['source']['quality'] == 'processed'
    assert figures.image_bytes(source, 'original') == processed
    with pytest.raises(SearchError, match='figure.version_changed'):
        figures.image_bytes(source, 'original', shown['content_id'])


def test_crop_uses_source_dimensions_and_version_bound_allowlisted_id(source):
    reviewed_manifest(source)
    shown = figures.present(source, 'abcdef012345')
    row = shown['figures'][1]
    assert row['image_url'] == f"/api/search/problems/abcdef012345/figures/option-a?version={shown['content_id']}"
    content = figures.image_bytes(source, row['id'], shown['content_id'])
    with Image.open(BytesIO(content)) as crop, Image.open(source / 'original.png') as high:
        assert crop.size == (200, 200)
        assert crop.tobytes() == high.crop((0, 0, 200, 200)).tobytes()
    for unknown in ('missing', '../original.png', 'original.png'):
        with pytest.raises(SearchError, match='figure.not_found'):
            figures.image_bytes(source, unknown)


@pytest.mark.parametrize('change', ['pixels', 'region', 'order', 'label', 'scope'])
def test_display_identity_binds_image_regions_and_option_mapping(source, change):
    manifest = reviewed_manifest(source)
    before = figures.presentation_identity(manifest)
    changed = deepcopy(manifest)
    if change == 'pixels':
        changed['source']['sha256'] = 'a' * 64
    elif change == 'region':
        changed['figures'][1]['box'][0] = .01
    elif change == 'order':
        changed['figures'][1:] = reversed(changed['figures'][1:])
    elif change == 'label':
        changed['figures'][1]['label'], changed['figures'][2]['label'] = 'B', 'A'
    else:
        changed['figures'][1].update(scope_ref='/root/children/0', target_ref='/root/children/0/goals/0')
    assert figures.presentation_identity(changed) != before
    (source / figures.MANIFEST).write_text(json.dumps(changed))
    with pytest.raises(SearchError, match='figure.source_changed' if change == 'pixels' else 'figure.version_changed'):
        figures.image_bytes(source, 'option-a', before)


@pytest.mark.parametrize('change,code', [
    ('duplicate', 'duplicate_option'), ('target', 'wrong_target'), ('zero', 'invalid_box'),
    ('nan', 'invalid_box'), ('path', 'invalid_manifest'), ('solution', 'invalid_manifest'),
])
def test_invalid_or_ambiguous_bindings_fail_closed(source, change, code):
    manifest = reviewed_manifest(source)
    row = manifest['figures'][1]
    if change == 'duplicate':
        manifest['figures'][2]['option_id'] = row['option_id']
    elif change == 'target':
        row['target_ref'] = '/root/children/0/goals/0'
    elif change == 'zero':
        row['box'] = [0, 0, 0, 1]
    elif change == 'nan':
        row['box'][0] = float('nan')
    elif change == 'path':
        row['path'] = '../other-upload/original.png'
    else:
        row['role'] = 'solution'
    (source / figures.MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(SearchError, match=f'figure.{code}'):
        figures.manifest_for(source)


def test_changed_source_and_symlinks_are_never_served_as_reviewed_crops(source, tmp_path):
    reviewed_manifest(source)
    Image.new('RGB', (400, 200), 'red').save(source / 'original.png')
    with pytest.raises(SearchError, match='figure.source_changed'):
        figures.image_bytes(source, 'option-a')
    (source / figures.MANIFEST).unlink()
    (source / figures.MANIFEST).symlink_to(tmp_path / 'question.png')
    with pytest.raises(SearchError, match='storage.symlink'):
        figures.manifest_for(source)
