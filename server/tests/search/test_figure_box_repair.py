"""Recorded box-only failure plus bounded repair and unchanged-text contracts."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.review_contract import pointer
from shuxueshuo_server.problem_understanding.workflow import RepairResponseError
from shuxueshuo_server.search import figure_box_repair
from shuxueshuo_server.search.extraction import REVIEW_CONTRACT, SearchStageOneContract
from shuxueshuo_server.search.stage_one import run_question_image
from shuxueshuo_server.search.text_extraction import TEXT_CONTRACT, TextExtractionContract, build_text_request
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from tests.search.test_public_extraction import CONFIRMED, Responses, correction

FIXTURES = Path(__file__).parent / 'fixtures/function-graph'


def recorded_case():
    case = json.loads((FIXTURES / 'figure-box-repair.json').read_text())
    candidate = case['candidate']
    diagnostics = TextExtractionContract().review_diagnostics(case['review'], candidate)
    patch = {'base_revision': revision(candidate), 'boxes': [
        {'path': d['path'], 'figure_id': pointer(candidate, d['path'].rsplit('/', 1)[0])['id'],
         'box': pointer(case['corrected'], d['path']), 'uncertainties': []}
        for d in diagnostics]}
    return case, diagnostics, patch


def image_pair():
    folder = FIXTURES / 'b09-v3-reviewed-recorded-20261102'
    return (folder / 'question.png').read_bytes(), (folder / 'original.png').read_bytes()


def test_recorded_box_repair_preserves_question_and_gets_fresh_full_review(tmp_path):
    case, diagnostics, patch = recorded_case()
    png, original = image_pair()
    provider = Responses(case['candidate'], case['review'], patch, CONFIRMED, case['figures'], CONFIRMED)
    result = run_question_image(png, tmp_path, provider, problem_id='box-repair', original_png=original,
                                read_graph_details=True)
    assert result['status'] == 'reviewed_candidate' and result['features_ok'], result
    assert len(provider.requests) == 6  # One box repair, no second full-question rewrite.
    assert [len(r.images) for r in provider.requests] == [1, 1, 1, 1, 5, 5]
    repair = provider.requests[2]
    assert repair.contract_version == figure_box_repair.CONTRACT
    payload = json.loads(repair.prompt.user_prefix)
    assert 'math_expression_catalog' not in payload and 'base_candidate' not in payload
    old = SearchStageOneContract().request_for(provider.requests[0], 'repair', case['candidate'], [], diagnostics)
    assert len(repair.prompt.system + repair.prompt.user_prefix) < len(old.prompt.system + old.prompt.user_prefix) / 4
    reviewed = json.loads(provider.requests[3].prompt.user_prefix)
    assert reviewed['candidate'] == case['corrected']
    assert 'math_expression_catalog' not in reviewed and 'graph_goal_schema' in reviewed
    assert reviewed['code_validation']['candidate_revision'] == revision(case['corrected'])
    assert result['public_candidate']['original_text'] == case['candidate']['original_text']
    assert result['public_candidate']['public_content']['scopes'] == case['candidate']['public_content']['scopes']
    assert result['figure_binding']['statement_figures'] and result['figure_binding']['option_figures']
    saved = json.loads((tmp_path / 'workflow/calls/03-repair/response.json').read_text())
    assert json.loads(saved['text']) == patch  # Preserve the actual wire reply, not a fabricated full response.
    workflow = json.loads((tmp_path / 'workflow/workflow-result.json').read_text())
    assert workflow['candidate'] == case['corrected']
    assert workflow['review']['revision'] == revision(case['corrected'])


@pytest.mark.parametrize('mutation', ['stale-base', 'wrong-id', 'wrong-path', 'rewrite-text', 'outside-image', 'empty-box'])
def test_box_patch_rejects_stale_or_unauthorized_edits(tmp_path, mutation):
    case, diagnostics, patch = recorded_case()
    candidate = deepcopy(case['candidate'])
    request = build_text_request(image_pair()[0], ExtractionArtifactStore(tmp_path / 'inputs'))
    request = TextExtractionContract().request_for(request, 'repair', candidate, [], diagnostics)
    if mutation == 'stale-base':
        patch['base_revision'] = '0' * 64
    elif mutation == 'wrong-id':
        patch['boxes'][0]['figure_id'] = patch['boxes'][1]['figure_id']
    elif mutation == 'wrong-path':
        patch['boxes'][0]['path'] = '/original_text'
    elif mutation == 'rewrite-text':
        patch['original_text'] = '替换题目'
    elif mutation == 'outside-image':
        patch['boxes'][0]['box'][0] = -0.1
    else:
        patch['boxes'][0]['box'] = [0.4, 0.1, 0.2, 0.5]
    with pytest.raises(RepairResponseError):
        TextExtractionContract().repair_response(request, json.dumps(patch), candidate, diagnostics)
    assert candidate == case['candidate']


def test_uncertain_box_stops_without_adopting_other_boxes_or_reading_figures(tmp_path):
    case, _, patch = recorded_case()
    patch['boxes'][-1].update(box=None, uncertainties=['图号对应不清楚。'])
    provider = Responses(case['candidate'], case['review'], patch)
    result = run_question_image(image_pair()[0], tmp_path, provider, problem_id='unclear-box')
    assert result['status'] == 'needs_confirmation'
    assert result['public_candidate'] == case['candidate']
    assert not result['source_reviewed'] and not result['features_ok'] and not result.get('figure_binding')
    assert result['confirmation_diagnostics'][0]['code'] == 'figure.box_uncertain'
    assert len(provider.requests) == 3 and not result['figure_attempts']


def test_bad_patch_retry_keeps_same_authority_and_existing_call_budget(tmp_path):
    case, _, patch = recorded_case()
    patch['boxes'][0]['path'] = '/root'
    provider = Responses(case['candidate'], case['review'], patch, patch)
    result = run_question_image(image_pair()[0], tmp_path, provider, problem_id='invalid-box')
    assert result['status'] == 'workflow.budget_exhausted'
    assert result['public_candidate'] == case['candidate'] and not result['figure_attempts']
    assert len(provider.requests) == 4
    assert provider.requests[2].contract_schema == provider.requests[3].contract_schema
    assert json.loads(provider.requests[3].prompt.user_prefix)['repair_feedback'][0]['code'] == 'figure.invalid_box_patch'


def test_mixed_text_and_box_findings_keep_existing_full_repair(tmp_path):
    case, diagnostics, _ = recorded_case()
    contract = TextExtractionContract()
    diagnostics += contract.review_diagnostics(correction('/public_content/scopes/0/statement'), case['candidate'])
    base = build_text_request(image_pair()[0], ExtractionArtifactStore(tmp_path / 'inputs'))
    request = contract.request_for(base, 'repair', case['candidate'], [], diagnostics)
    assert request.contract_version == TEXT_CONTRACT
    assert json.loads(request.prompt.user_prefix)['base_candidate'] == case['candidate']
    raw = json.dumps(case['corrected'])
    assert contract.repair_response(request, raw, case['candidate'], diagnostics) == raw


@pytest.mark.parametrize('mixed_content', ['goal', 'definition', 'fact'])
def test_graph_review_stays_complete_and_mixed_questions_keep_general_catalog(tmp_path, mixed_content):
    case, _, _ = recorded_case()
    base = build_text_request(image_pair()[0], ExtractionArtifactStore(tmp_path / 'inputs'))
    contract = TextExtractionContract()
    plain = contract.request_for(base, 'review', case['candidate'], [], validation={'contract_valid': True})
    assert plain.contract_version == REVIEW_CONTRACT
    payload = json.loads(plain.prompt.user_prefix)
    assert payload['candidate'] == case['candidate']
    assert 'math_expression_catalog' not in payload
    assert 'source_graph' in payload['graph_goal_schema']['properties']
    mixed = deepcopy(case['candidate'])
    if mixed_content == 'goal':
        mixed['root']['goals'].append({'kind': 'find_range', 'object': 'f'})
    elif mixed_content == 'definition':
        mixed['root']['definitions'] = ['f(x)=x^2']
    else:
        mixed['root']['facts'] = ['x>0']
    request = contract.request_for(base, 'review', mixed, [], validation={'contract_valid': True})
    payload = json.loads(request.prompt.user_prefix)
    assert payload['candidate'] == mixed and 'math_expression_catalog' in payload
    assert 'graph_goal_schema' not in payload


def test_box_patch_cannot_publish_before_source_review_confirms(tmp_path):
    case, _, patch = recorded_case()
    uncertain = deepcopy(case['review'])
    uncertain['status'] = 'uncertain'
    provider = Responses(case['candidate'], case['review'], patch, uncertain)
    result = run_question_image(image_pair()[0], tmp_path, provider, problem_id='unreviewed-box')
    assert result['status'] == 'needs_confirmation' and not result['source_reviewed']
    assert result['public_candidate'] == case['corrected']
    assert not result.get('figure_binding') and not result['figure_attempts']


def test_graph_review_includes_the_identical_function_definition_without_general_catalog(tmp_path):
    case = json.loads((FIXTURES / 'formula-graph-comparison-misclassified.json').read_text())
    candidate = case['text_candidate']
    candidate['root']['goals'][0]['comparison'] = 'rough_shape'
    contract = TextExtractionContract()
    base = build_text_request(image_pair()[0], ExtractionArtifactStore(tmp_path / 'inputs'))
    request = contract.request_for(base, 'review', candidate, [], validation={'contract_valid': True})
    payload = json.loads(request.prompt.user_prefix)
    assert payload['candidate'] == candidate
    assert payload['candidate']['root']['definitions'] == ['f(x)=abs(x-1)+1']
    assert 'math_expression_catalog' not in payload
    # A different definition or additional condition must keep the general review.
    for field, extra in [('definitions', 'f(x)=abs(x+1)+1'), ('facts', 'x>0')]:
        changed = deepcopy(candidate)
        changed['root'][field] = [extra]
        request = contract.request_for(base, 'review', changed, [], validation={'contract_valid': True})
        assert 'math_expression_catalog' in json.loads(request.prompt.user_prefix)
