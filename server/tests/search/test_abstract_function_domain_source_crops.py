"""The Q2/Q26 photo inputs remain exact crops of their shared archived pages."""

import json
from hashlib import sha256
from pathlib import Path

import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
SOURCES = REPO / 'internal/senior-high/source-images'


@pytest.mark.parametrize('problem,shared_page,box', [
    ('function-concepts-q02', 'function-concepts-q04', [180, 284, 800, 329]),
    ('function-concepts-q26', 'function-concepts-q25', [79, 750, 675, 831]),
])
def test_abstract_domain_source_crop_preserves_the_existing_page(problem, shared_page, box):
    directory = SOURCES / problem
    manifest = json.loads((directory / 'manifest.json').read_text())
    assert manifest['problem_id'] == problem
    page_file = (directory / manifest['page']['file']).resolve()
    assert page_file == SOURCES / shared_page / 'source-page.jpg'
    assert not (directory / 'source-page.jpg').exists(), 'reuse the archived page without a duplicate'
    crop_file = directory / manifest['crop']['file']
    assert manifest['crop']['xyxy'] == box
    assert sha256(page_file.read_bytes()).hexdigest() == manifest['page']['sha256']
    assert sha256(crop_file.read_bytes()).hexdigest() == manifest['crop']['sha256']
    with Image.open(page_file) as page, Image.open(crop_file) as crop:
        assert list(page.size) == manifest['page']['size']
        assert list(crop.size) == manifest['crop']['size']
        assert page.crop(box).convert('RGB').tobytes() == crop.convert('RGB').tobytes()
    if problem == 'function-concepts-q26':
        candidate = json.loads((REPO / manifest['candidate_fixture']).read_text())
        assert candidate['original_text'].replace('$', '') == manifest['verified_statement']
        assert candidate['root'] == {'goals': [{
            'kind': 'find_abstract_domain', 'known_call': 'f(x+2)',
            'known_domain': '[-3,2]', 'strength': 'exact', 'target_call': 'f(2*x-1)',
        }]}, 'the fixture must retain both photographed composite calls, without injecting a solved domain'
