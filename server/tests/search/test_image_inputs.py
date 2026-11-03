"""Same-crop original pixels reach extraction and review; old runs stay single-image."""
import json
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from shuxueshuo_server.search import dev_api, reviewed_figures
from shuxueshuo_server.search.extraction import (
    SearchStageOneContract,
    build_search_request,
)
from shuxueshuo_server.search.question_image import image_inputs, question_png
from shuxueshuo_server.search.stage_one import (
    run_legacy_question_image as run_question_image,
)
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from tests.search.test_public_extraction import CONFIRMED, Responses

RECORDING = Path(__file__).parent/'fixtures/function-graph/b09-recorded-20261102'


def _png(picture):
    buffer = BytesIO()
    picture.save(buffer, format='PNG')
    return buffer.getvalue()


@pytest.mark.parametrize('size', [(400, 200), (2400, 1200)])
def test_original_pixels_and_crop_coordinates_survive_every_stage(tmp_path, size):
    picture = Image.new('RGB', size, 'white')
    draw = ImageDraw.Draw(picture)
    draw.line((20, 110, 380, 110), fill='black', width=4)
    draw.ellipse((95, 95, 105, 105), outline=(240, 240, 240), width=1)
    original, processed = _png(picture), question_png(picture)
    request = build_search_request(processed, ExtractionArtifactStore(tmp_path), original_png=original)
    assert [i.content for i in request.images] == [processed, original]
    assert [i.page_id for i in request.images] == ['page-1', 'page-1']
    assert (request.images[1].width, request.images[1].height) == size
    with Image.open(BytesIO(request.images[1].content)) as source:
        assert source.getpixel((100, 95)) == (240, 240, 240)
    if size == (400, 200):
        with Image.open(BytesIO(processed)) as flat:
            assert flat.getpixel((100, 95)) == 255
    else:
        assert request.images[0].width == 1600
    contract = SearchStageOneContract()
    expected = image_inputs(processed, original)
    for outgoing in (request, contract.request_for(request, 'review', {}, []),
                     contract.request_for(request, 'repair', {}, [])):
        assert json.loads(outgoing.prompt.user_prefix)['image_inputs'] == expected
        assert [i.content for i in outgoing.images] == [processed, original]
        assert '不是两页' in outgoing.prompt.system
    legacy = build_search_request(processed, ExtractionArtifactStore(tmp_path/'legacy'))
    assert len(legacy.images) == 1 and 'image_inputs' not in json.loads(legacy.prompt.user_prefix)


def test_mismatched_crop_and_stale_source_fail_before_model_call(tmp_path):
    original = _png(Image.new('RGB', (400, 200), 'white'))
    changed = Image.new('RGB', (400, 200), 'white')
    ImageDraw.Draw(changed).line((20, 110, 380, 110), fill='black', width=4)
    provider = Responses()
    with pytest.raises(ValueError, match='image_input.crop_mismatch'):
        run_question_image(question_png(changed), tmp_path, provider, problem_id='mismatch', original_png=original)
    assert not (tmp_path/'question.png').exists()
    (tmp_path/'original.png').write_bytes(_png(changed))
    with Image.open(BytesIO(original)) as picture:
        processed = question_png(picture)
    with pytest.raises(ValueError, match='image_input.source_changed'):
        run_question_image(processed, tmp_path, provider, problem_id='stale', original_png=original)
    assert not provider.requests
    assert (tmp_path/'original.png').read_bytes() == _png(changed)


def test_dual_view_review_binds_both_images_and_rejects_unreviewed_original(tmp_path):
    # Offline contract exercise, not evidence of a fresh model recognition.
    candidate = json.loads((RECORDING/'result.json').read_text())['public_candidate']
    processed, original = [(RECORDING/name).read_bytes() for name in ('question.png', 'original.png')]
    provider = Responses(candidate, CONFIRMED)
    result = run_question_image(processed, tmp_path, provider, problem_id='dual-view-unit', original_png=original)
    assert result['status'] == 'reviewed_candidate' and result['source_reviewed']
    expected = [sha256(image).hexdigest() for image in (processed, original)]
    assert result['sent_image_sha256'] == expected
    ledger = json.loads((tmp_path/'workflow/ledger.json').read_text())
    assert ledger['identity']['binding']['images'] == expected
    assert len(provider.requests) == 2
    for request in provider.requests:
        assert [i.artifact.sha256 for i in request.images] == expected
    assert result['figure_binding']['source_sha256'] == expected[1]
    assert dev_api._present(result)['image_check']['verified']
    assert dev_api._present(result)['image_check']['original_sha256'] == expected[1]
    bad = deepcopy(result)
    bad['sent_image_sha256'] = expected[:1]
    assert not dev_api._present(bad)['image_check']['verified']
    with pytest.raises(ValueError, match='figure.review_image_mismatch'):
        reviewed_figures.install(tmp_path, bad)
    bad = deepcopy(result)
    bad['image_inputs']['views'][1]['sha256'] = '0'*64
    bad['sent_image_sha256'][1] = '0'*64
    with pytest.raises(ValueError, match='figure.review_image_mismatch'):
        reviewed_figures.install(tmp_path, bad)
    bad['image_inputs']['views'] = []
    assert not dev_api._present(bad)['image_check']['verified']


def test_provider_cannot_drop_original_and_publish_a_reviewed_result(tmp_path):
    candidate = json.loads((RECORDING/'result.json').read_text())['public_candidate']
    class DroppedOriginal(Responses):
        def prepare_request(self, request):
            return super().prepare_request(replace(request, images=request.images[:1]))
    provider = DroppedOriginal(candidate, CONFIRMED)
    with pytest.raises(ValueError, match='image_input.sent_image_mismatch'):
        run_question_image((RECORDING/'question.png').read_bytes(), tmp_path, provider,
                           problem_id='dropped-original-unit', original_png=(RECORDING/'original.png').read_bytes())
    assert not (tmp_path/'result.json').exists()
    assert not (tmp_path/'question-figures.json').exists()
