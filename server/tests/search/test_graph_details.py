"""Detail rereading provenance/budget contracts; synthetic responses are not live evidence."""
import json
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from shuxueshuo_server.problem_understanding.workflow_diagnostics import (
    uncertainty_diagnostics,
)
from shuxueshuo_server.search import dev_api, reviewed_figures
from shuxueshuo_server.search.extraction import (
    SearchStageOneContract,
    build_search_request,
)
from shuxueshuo_server.search.graph_details import detail_crops, plan_details
from shuxueshuo_server.search.question_image import expected_image_hashes
from shuxueshuo_server.search.stage_one import (
    ledger_calls,
    reviewing_candidate,
)
from shuxueshuo_server.search.stage_one import (
    run_legacy_question_image as run_question_image,
)
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from tests.search.test_public_extraction import CONFIRMED, Responses

RECORDING = Path(__file__).parent/'fixtures/function-graph/b09-v3-original-view-recorded-20261102'


def inputs():
    first = json.loads((RECORDING/'result.json').read_text())['public_candidate']
    processed, original = [(RECORDING/name).read_bytes() for name in ('question.png', 'original.png')]
    workflow = {'status': 'needs_confirmation', 'candidate': first, 'diagnostics': uncertainty_diagnostics(first)}
    return processed, original, workflow


def clarified(first):
    # Authored unit response, deliberately separate from actual photo acceptance.
    candidate = deepcopy(first)
    goal = candidate['root']['goals'][0]
    for graph, x in zip([goal['source_graph'], *goal['options']], ['0', '2', '-2', '2', '-2'], strict=True):
        graph['facts']['x_intercept'] = {'x': x, 'evidence': 'origin' if x == '0' else 'labelled'}
        graph['uncertainties'] = []
    return candidate


def test_detail_pixels_source_mapping_and_review_preserve_every_view(tmp_path):
    processed, original, first = inputs()
    plan = plan_details(first, original)
    assert len(plan['regions']) == 5
    request = build_search_request(processed, ExtractionArtifactStore(tmp_path), original_png=original, detail_plan=plan)
    assert len(request.images) == 7
    with Image.open(BytesIO(original)) as source:
        for view, pixels in detail_crops(original, plan['regions']):
            with Image.open(BytesIO(pixels)) as crop:
                assert crop.tobytes() == source.crop(view['pixel_box']).tobytes()
    payload = json.loads(request.prompt.user_prefix)
    bound = {'question_sha256': sha256(processed).hexdigest(), 'image_inputs': payload['image_inputs']}
    assert expected_image_hashes(bound) == [i.artifact.sha256 for i in request.images]
    for stage in ('repair', 'review'):
        outgoing = SearchStageOneContract().request_for(request, stage, {}, [])
        assert outgoing.images == request.images
        assert json.loads(outgoing.prompt.user_prefix)['detail_reading'] == plan
        assert json.loads(outgoing.prompt.user_prefix)['image_inputs'] == payload['image_inputs']
    bad = deepcopy(bound)
    bad['image_inputs']['views'][2]['pixel_box'][0] += 1
    assert not expected_image_hashes(bad)
    with pytest.raises(ValueError, match='detail_source_mismatch'):
        build_search_request(processed, ExtractionArtifactStore(tmp_path/'bad'), original_png=original,
                             detail_plan={**plan, 'source_sha256': '0'*64})


def test_malformed_incomplete_or_non_graph_uncertainty_cannot_request_detail_reads():
    _, original, workflow = inputs()
    candidate = workflow['candidate']
    mutations = []
    for path, value in [('completeness', 'incomplete'), ('statement_figure_regions', []), ('figure_regions', [])]:
        bad = deepcopy(workflow)
        bad['candidate']['public_content'][path] = value
        mutations.append(bad)
    for box in ([0.5, 0, 0.4, 1], [0, 0, 0.001, 0.001], [0, 0, float('nan'), 1]):
        bad = deepcopy(workflow)
        bad['candidate']['public_content']['figure_regions'][0]['box'] = box
        mutations.append(bad)
    bad = deepcopy(workflow)
    bad['diagnostics'].append({'path': '/root/uncertainties/0', 'action': 'needs_confirmation'})
    mutations.append(bad)
    bad = deepcopy(workflow)
    del bad['candidate']['root']['goals'][0]['source_graph']
    mutations.append(bad)
    for bad in mutations:
        assert plan_details(bad, original) is None
    assert workflow['candidate'] == candidate  # Planning never edits the first extraction.


def test_fresh_detail_reading_requires_review_and_retains_the_first_failure(tmp_path):
    processed, original, first = inputs()
    correct = clarified(first['candidate'])
    provider = Responses(first['candidate'], correct, CONFIRMED)
    result = run_question_image(processed, tmp_path, provider, problem_id='detail-unit',
                               original_png=original, read_graph_details=True)
    assert result['status'] == 'reviewed_candidate' and result['source_reviewed']
    assert result['features_ok'] and result['figure_binding']['statement_figures']
    assert [len(r.images) for r in provider.requests] == [2, 7, 7]
    assert 'candidate' not in json.loads(provider.requests[1].prompt.user_prefix)
    assert json.loads(provider.requests[2].prompt.user_prefix)['candidate'] == correct
    previous = json.loads((tmp_path/'workflow/workflow-result.json').read_text())
    assert previous['status'] == 'needs_confirmation' and previous['candidate'] == first['candidate']
    assert result['workflow_directory'] == 'workflow-detail'
    assert ledger_calls(tmp_path/'workflow') == [('extract', 'completed'), ('extract', 'completed'), ('review', 'completed')]
    assert reviewing_candidate(tmp_path/'workflow') == correct
    assert dev_api._present(result)['image_check']['verified']
    assert dev_api._present(result)['image_check']['original_sha256'] == sha256(original).hexdigest()
    # A swapped crop or a stale region hint cannot install a reviewed manifest.
    bad = deepcopy(result)
    bad['detail_reading']['regions'][0]['box'][0] += 0.01
    with pytest.raises(ValueError, match='figure.review_image_mismatch'):
        reviewed_figures.install(tmp_path, bad)
    bad = deepcopy(result)
    bad['image_inputs']['views'][2]['sha256'] = '0'*64
    bad['sent_image_sha256'][2] = '0'*64
    with pytest.raises(ValueError, match='figure.review_image_mismatch'):
        reviewed_figures.install(tmp_path, bad)


@pytest.mark.parametrize('failure', ['uncertain', 'review_rejected'])
def test_failed_detail_reading_cannot_loop_or_publish(tmp_path, failure):
    processed, original, first = inputs()
    responses = [first['candidate'], first['candidate']] if failure == 'uncertain' else [
        first['candidate'], clarified(first['candidate']), {'status': 'correction_required', 'findings': [{
            'path': '/root/goals/0/options/0/facts/x_intercept', 'kind': 'wrong_expression',
            'source_excerpt': '图形', 'message': '需要重新核对。'}]}]
    provider = Responses(*responses)
    result = run_question_image(processed, tmp_path, provider, problem_id='detail-failure',
                               original_png=original, read_graph_details=True)
    assert len(provider.requests) == len(responses)
    assert result['status'] == 'needs_confirmation' and not result['source_reviewed']
    assert result['confirmation_diagnostics'] and not result['features_ok']
    assert not result.get('figure_binding') and not (tmp_path/'question-figures.json').exists()
    assert result['detail_attempt']['status'] != 'reviewed_candidate'


def test_provider_cannot_drop_a_detail_image_and_publish(tmp_path):
    processed, original, first = inputs()
    class MissingDetail(Responses):
        def prepare_request(self, request):
            if len(request.images) > 2:
                request = replace(request, images=request.images[:-1])
            return super().prepare_request(request)
    provider = MissingDetail(first['candidate'], clarified(first['candidate']), CONFIRMED)
    with pytest.raises(ValueError, match='image_input.sent_image_mismatch'):
        run_question_image(processed, tmp_path, provider, problem_id='detail-drop',
                           original_png=original, read_graph_details=True)
    assert not (tmp_path/'result.json').exists() and not (tmp_path/'question-figures.json').exists()
