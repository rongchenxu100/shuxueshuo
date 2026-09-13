"""Production extraction boundaries with recorded external observations/providers."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import ExtractionAttemptLedger, ExtractionRetryState, ProblemExtractionContextBuilder
from shuxueshuo_server.solver.extraction.handwriting import ConservativeInkOriginAnalyzer
from shuxueshuo_server.solver.extraction.multimodal_evidence import MultimodalEvidencePackBuilder
from shuxueshuo_server.solver.extraction.observation_context import ObservationContextTransitionService, f2_semantic_config
from shuxueshuo_server.solver.extraction.observation_pipeline import F2ObservationPipeline
from shuxueshuo_server.solver.extraction.observations import PaddleProviderRecord
from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft
from shuxueshuo_server.solver.extraction.problem_domain_service import ProblemDomainExtractionService
from shuxueshuo_server.solver.extraction.problem_domain_validation import ProblemDomainValidator
from shuxueshuo_server.solver.extraction.problem_source_review import CONTRACT, SourceReviewer, binding_for, source_differences, validate_review
from shuxueshuo_server.solver.extraction.source_identity import ExtractionDependencyManifest, ProblemSourceFingerprintService, SourceAssetInput, SourceSelection, SelectionRegion
from shuxueshuo_server.solver.extraction.source_identity import stable_hash

from _problem_extraction_f2_support import provider, successful_ledger
from test_problem_domain_retry import _SequenceProvider

FIXTURE = Path(__file__).parent / 'fixtures/source_review/heping-layout-miss'


def recorded_input(tmp_path, case=None):
    repo = Path(__file__).resolve().parents[3]
    image_path = (repo / json.loads((repo / 'internal/source-images' / case / 'source-manifest.json').read_text())['pages'][0]['asset_path']) if case else FIXTURE / 'source.png'
    content = image_path.read_bytes()
    page_id = 'page_1' if case else 'page-1'
    source = ProblemSourceFingerprintService().fingerprint((SourceAssetInput(
        page_id=page_id, media_type='image/jpeg' if image_path.suffix.lower() in {'.jpg', '.jpeg'} else 'image/png', content_bytes=content, locator='fixture://source.png'),))
    selection = SourceSelection.create(source, mode='user_confirmed', revision=0,
        regions=(SelectionRegion('question', page_id, ((0, 0), (1, 0), (1, 1), (0, 1))),))
    records = []
    manifests = []
    for name, component in [('layout', 'layout'), ('text', 'text_ocr')]:
        raw = (json.loads((FIXTURE.parent / 'gold-observations' / (case + '.json')).read_text())[component]
               if case else json.loads((FIXTURE / (name + '.json')).read_text()))
        raw = {k: v for k, v in raw.items() if k != 'page_id'}
        manifest = provider(component, 'recorded-' + name)
        manifests.append(manifest)
        records.append(PaddleProviderRecord.create(component=component, provider=manifest,
            source_revision_hash=source.source_revision_hash, page_id=page_id, **raw))
    manifests.append(ConservativeInkOriginAnalyzer().provider)
    dependency = ExtractionDependencyManifest.create(source, selection,
        semantic_config=f2_semantic_config([p.to_payload() for p in manifests]))
    initial = ProblemExtractionContextBuilder.initial(source=source, selection=selection, dependency=dependency,
        retry=ExtractionRetryState(attempt_budget=8), quality={'problem_id': case or 'tj-2026-heping-yimo-25'})
    store = ExtractionArtifactStore(tmp_path / 'artifacts')
    from shuxueshuo_server.solver.extraction.multimodal_evidence import _selection_canvas
    crop_bytes = _selection_canvas(initial, page_id, content)
    crop = store.put_bytes(kind='selection_crop', content=crop_bytes, media_type='image/png', suffix='.png')
    assembly = F2ObservationPipeline(artifact_store=store).assemble(source=source, selection=selection,
        dependency=dependency, page_bytes={page_id: content}, layout_records=(records[0],), text_records=(records[1],),
        extra_artifacts=(crop,))
    context = ObservationContextTransitionService().attach(initial, assembly.observation,
        artifacts=assembly.artifacts, attempt_ledger=successful_ledger(initial, assembly.artifacts))
    pack = MultimodalEvidencePackBuilder().build(context, artifact_reader=store, observation=assembly.observation)
    return initial, context, store, pack


def corrected_payload():
    raw = json.loads((FIXTURE / 'draft.json').read_text())
    ray = raw['root']['entities'].pop()
    raw['root']['children'][1]['entities'].append(ray)
    return raw


def review_response(request, status='confirmed'):
    data = json.loads(request.prompt.user_suffix)
    if status == 'confirmed':
        recorded = json.loads((FIXTURE / 'review-confirmed.json').read_text())
        return json.dumps({**recorded, 'binding': data['binding']}, ensure_ascii=False)
    return json.dumps({'schema_version': CONTRACT, 'binding': data['binding'], 'status': status,
        'findings': [{'unit_ids': ['scope:root/part2'], 'source_text': '点N是射线CD上一动点，且满足CN=CM',
                      'message': '原图第Ⅱ问支持射线和等长条件' if status == 'confirmed' else '需要核对第Ⅱ問',
                      'regions': [{'region_id': None, 'page_id': 'page-1', 'bbox': [0, .8, 1, 1]}]}]}, ensure_ascii=False)


def execute(tmp_path, responses, max_attempts=3):
    initial, context, store, pack = recorded_input(tmp_path)
    client = _SequenceProvider(responses)
    result = ProblemDomainExtractionService(input_artifact_reader=store, output_artifact_store=store, provider=client).run(
        context, attempt_ledger=ExtractionAttemptLedger.for_context(context), ancestor_contexts=(initial,), max_attempts=max_attempts)
    return result, client, (initial, context, store, pack)


def test_layout_miss_repairs_scope_then_reviews_image_without_changing_family(tmp_path):
    raw = (FIXTURE / 'draft.json').read_text()
    def patch(request):
        # Canonical revision is bound at runtime, never copied from a live build.
        text = request.prompt.user_suffix
        draft_data = json.loads(text.split('当前 Draft（value 是领域 wire，unit_id 由代码分配）：\n')[1].split('\nValidator root issues：')[0])
        move = json.loads((FIXTURE / 'move-ray.json').read_text())
        return json.dumps({'schema_version': 'problem-repair/v1', 'base_revision_id': draft_data['revision_id'],
                          'replacements': [], 'removals': ['entity:root:ray_CD'],
                          'additions': [{'scope_path': move['scope_path'], 'collection': 'entity', 'value': move['entity']}]})
    result, client, (_, _, _, pack) = execute(tmp_path, [raw, patch, review_response])
    assert result.accepted, [a.to_payload() for a in result.attempts]
    assert [r.contract_version for r in client.requests] == ['problem-domain/v1', 'problem-repair/v1', CONTRACT]
    assert len(result.attempts) == 2
    assert result.verified_problem.graph.family_id == 'QuadraticEqualLengthRayPathMinimumSolver'
    assert not any('射线' in t.text for t in pack.printed_text)
    assert any('射线' in (r['hint'] or '') for r in pack.prompt_payload()['uncertain_regions'])
    assert result.attempts[-1].source_review['status'] == 'confirmed'
    assert any(a.kind == 'problem_source_review' for a in result.final_context.state.artifacts)


@pytest.mark.parametrize('status', ['uncertain', 'correction_required'])
def test_source_review_never_accepts_unconfirmed_image(tmp_path, status):
    result, client, _ = execute(tmp_path, [json.dumps(corrected_payload()), lambda r: review_response(r, status)], max_attempts=1)
    assert result.blocked and not result.accepted
    assert any(i.code == f'extraction.problem_source_{status}' for i in result.attempts[-1].report.issues)
    if status == 'uncertain':
        assert result.blocked_reason == 'extraction.problem_source_uncertain'
        assert len(client.requests) == 2
    else:
        # Budget exhausted before a repair round; still must not adopt the unconfirmed draft.
        assert result.blocked_reason == 'extraction.problem_retry_exhausted'
        assert len(client.requests) == 2


def test_discrepancies_are_advisory_but_structure_is_strict(tmp_path):
    _, _, _, pack = recorded_input(tmp_path)
    good = ProblemDraft.create(corrected_payload())
    checked = ProblemDomainValidator().validate(good, evidence_pack=pack)
    assert checked.ok, checked.report.to_payload()
    assert source_differences(good, pack)['differences']
    bad = ProblemDraft.create((FIXTURE / 'draft.json').read_text())
    assert any(i.code == 'extraction.problem_source_literal_unresolved'
               for i in ProblemDomainValidator().validate(bad, evidence_pack=pack).report.issues)
    mismatch = corrected_payload()
    mismatch['family_id'] = 'QuadraticPathMinimumSolver'
    assert any(i.code == 'extraction.problem_family_contract_mismatch'
               for i in ProblemDomainValidator().validate(ProblemDraft.create(mismatch), evidence_pack=pack).report.issues)


def test_review_binding_regions_and_budget_survive_recreation(tmp_path):
    _, context, store, pack = recorded_input(tmp_path)
    draft = ProblemDraft.create(corrected_payload())
    client = _SequenceProvider([review_response])
    args = dict(context_id=context.manifest.context_id, draft=draft, pack=pack, reader=store,
                provider=client, differences=source_differences(draft, pack))
    first, refs = SourceReviewer(store).review(**args)
    assert first['status'] == 'confirmed', first
    second, _ = SourceReviewer(store).review(**args)
    assert first == second and len(client.requests) == 1
    value = json.loads(review_response(client.requests[0]))
    for change in ['binding', 'page', 'bbox', 'unit']:
        invalid = deepcopy(value)
        if change == 'binding': invalid['binding'] = 'old-revision'
        if change == 'page': invalid['findings'][0]['regions'][0]['page_id'] = 'other-page'
        if change == 'bbox': invalid['findings'][0]['regions'][0]['bbox'] = [.9, 0, .1, 1]
        if change == 'unit': invalid['findings'][0]['unit_ids'] = ['entity:missing']
        with pytest.raises(ValueError): validate_review(invalid, draft, pack)
    assert refs and binding_for(draft, pack) == value['binding']


@pytest.mark.parametrize('response', ['{}', lambda r: (_ for _ in ()).throw(TimeoutError())])
def test_invalid_or_timed_out_review_blocks_and_is_not_retried(tmp_path, response):
    result, client, (_, context, store, pack) = execute(tmp_path, [json.dumps(corrected_payload()), response])
    assert result.blocked_reason == 'extraction.problem_source_uncertain'
    draft = result.attempts[-1].resulting_draft
    report, _ = SourceReviewer(store).review(context_id=context.manifest.context_id, draft=draft,
        pack=pack, reader=store, provider=client, differences=source_differences(draft, pack))
    assert report['status'] == 'uncertain' and len(client.requests) == 2


def test_clean_auxiliary_observations_need_no_review(tmp_path):
    initial, context, store, pack = recorded_input(tmp_path)
    draft = ProblemDraft.create(corrected_payload())
    text = replace(pack.printed_text[0], text=''.join(draft.graph.original_text_lines))
    clean = replace(pack, printed_text=(text,), unresolved_items=())
    assert source_differences(draft, clean)['differences'] == []
    clean = replace(clean, evidence_pack_id=f'evidence-pack:{stable_hash(clean.authority_payload())}')
    class CleanPack:
        def build(self, *args, **kwargs): return clean
    client = _SequenceProvider([json.dumps(corrected_payload())])
    run = ProblemDomainExtractionService(input_artifact_reader=store, output_artifact_store=store,
        provider=client, evidence_pack_builder=CleanPack()).run(context,
        attempt_ledger=ExtractionAttemptLedger.for_context(context), ancestor_contexts=(initial,))
    assert run.accepted and len(client.requests) == 1
    assert run.attempts[0].source_review is None


def test_ocr_typo_remains_advisory_and_does_not_change_draft(tmp_path):
    _, _, _, pack = recorded_input(tmp_path)
    draft = ProblemDraft.create(corrected_payload())
    before = draft.to_payload()
    wrong = replace(pack, printed_text=(replace(pack.printed_text[0], text='点N是射线CD上一动点，CN=2CM，最小值为100'),))
    differences = source_differences(draft, wrong)
    assert any(d['code'] == 'ocr_transcription_difference' for d in differences['differences'])
    assert ProblemDomainValidator().validate(draft, evidence_pack=wrong).ok
    assert draft.to_payload() == before


@pytest.mark.parametrize('text', ['√35', 'CN=-CM', '点N是射线CD上一动点，且满足CN=2CM'])
def test_small_numeric_or_sign_difference_is_not_hidden_by_fuzzy_match(tmp_path, text):
    _, _, _, pack = recorded_input(tmp_path)
    draft = ProblemDraft.create(corrected_payload())
    changed = replace(pack, printed_text=(replace(pack.printed_text[0], text=text),))
    assert any(d['code'] == 'ocr_transcription_difference' for d in source_differences(draft, changed)['differences'])
    assert ProblemDomainValidator().validate(draft, evidence_pack=changed).ok


def test_review_budget_and_crash_reservation_are_durable(tmp_path):
    _, context, store, pack = recorded_input(tmp_path)
    draft = ProblemDraft.create(corrected_payload())
    client = _SequenceProvider([review_response] * 3)
    for i in range(4):
        changed = ProblemDraft.from_graph(draft.graph, parent_revision_id=f'parent-{i}')
        value, _ = SourceReviewer(store).review(context_id=context.manifest.context_id,
            draft=changed, pack=pack, reader=store, provider=client, differences=source_differences(changed, pack))
        assert value['status'] == ('confirmed' if i < 3 else 'uncertain')
    assert len(client.requests) == 3
    def crash(request): raise KeyboardInterrupt('simulate process loss')
    client = _SequenceProvider([crash])
    args = dict(context_id='separate-context', draft=draft, pack=pack, reader=store,
                provider=client, differences=source_differences(draft, pack))
    with pytest.raises(KeyboardInterrupt): SourceReviewer(store).review(**args)
    value, _ = SourceReviewer(store).review(**args)
    assert value['status'] == 'uncertain' and 'unknown' in value['error']
    assert len(client.requests) == 1


def test_visual_correction_authorizes_only_affected_scope_then_rechecks(tmp_path):
    raw = corrected_payload()
    raw['root']['children'][1]['source_text'][0] = raw['root']['children'][1]['source_text'][0].replace('√34', '√35')
    def correction(request):
        result = json.loads(review_response(request, 'correction_required'))
        result['findings'][0]['message'] = '原图给定最小值是√34，候选转录是√35。'
        result['findings'][0]['source_text'] = corrected_payload()['root']['children'][1]['source_text'][0]
        return json.dumps(result)
    def repair(request):
        data = json.loads(request.prompt.user_suffix.split('当前 Draft（value 是领域 wire，unit_id 由代码分配）：\n')[1].split('\nValidator root issues：')[0])
        zooms = [i for i in request.images if i.role == 'zoom']
        assert len(zooms) == 1 and zooms[0].page_id == 'page-1'
        assert zooms[0].width == 2134 and zooms[0].height == 92
        assert 'source-review-bbox:' in request.prompt.user_suffix
        assert any(i.role == 'primary' for i in request.images)
        scope = corrected_payload()['root']['children'][1]
        return json.dumps({'schema_version': 'problem-repair/v1', 'base_revision_id': data['revision_id'],
            'replacements': [{'unit_id': 'scope:root/part2', 'value': {k: scope[k] for k in ['id', 'label', 'source_text']}}],
            'additions': [], 'removals': []})
    run, client, _ = execute(tmp_path, [json.dumps(raw), correction, repair, review_response])
    assert run.accepted, [a.to_payload() for a in run.attempts]
    assert [r.contract_version for r in client.requests] == ['problem-domain/v1', CONTRACT, 'problem-repair/v1', CONTRACT]
    assert run.attempts[0].source_review['binding'] != run.attempts[1].source_review['binding']


def test_source_review_can_remove_unsupported_annotation_ignored_by_solver_hash(tmp_path):
    raw = corrected_payload()
    fact = next(f for f in raw['root']['facts'] if f.get('construction') == 'x_axis_intercept')
    fact['side'] = 'right'
    fact['exclude_point'] = 'point_A'
    # Use the actual entity ID from this recording.
    fact['exclude_point'] = next(e['id'] for e in raw['root']['entities'] if e.get('label') == 'A')
    seen = {}
    def correction(request):
        data = json.loads(request.prompt.user_suffix)
        draft = ProblemDraft.create(data['draft'])
        target = next(f for f in draft.graph.root_scope.facts if f.attributes.get('construction') == 'x_axis_intercept')
        seen['unit'] = target.unit_id
        seen['value'] = target.wire_payload()
        seen['hash'] = draft.semantic_hash
        result = json.loads(review_response(request, 'correction_required'))
        result['findings'][0]['unit_ids'] = [target.unit_id]
        result['findings'][0]['message'] = '原题只说另一交点，删除未给定的side标注。'
        return json.dumps(result)
    def repair(request):
        data = json.loads(request.prompt.user_suffix.split('当前 Draft（value 是领域 wire，unit_id 由代码分配）：\n')[1].split('\nValidator root issues：')[0])
        value = {k: v for k, v in seen['value'].items() if k != 'side'}
        return json.dumps({'schema_version': 'problem-repair/v1', 'base_revision_id': data['revision_id'],
            'replacements': [{'unit_id': seen['unit'], 'value': value}], 'additions': [], 'removals': []})
    run, client, _ = execute(tmp_path, [json.dumps(raw), correction, repair, review_response])
    assert run.accepted, [a.to_payload() for a in run.attempts]
    assert run.verified_problem.graph.semantic_hash == seen['hash']
    assert run.attempts[0].source_review['binding'] != run.attempts[1].source_review['binding']
    assert len(client.requests) == 4


@pytest.mark.parametrize('case', [
    'tj-2026-heping-yimo-25', 'tj-2026-heping-ermo-25', 'tj-2026-nankai-yimo-25',
    'tj-2026-xiqing-yimo-25', 'tj-2026-hexi-yimo-25',
])
def test_five_matching_images_and_recorded_ocr_use_production_validator(tmp_path, case):
    initial, context, store, pack = recorded_input(tmp_path, case)
    repo = Path(__file__).resolve().parents[3]
    raw = json.loads((repo / 'internal/problem-domain-fixtures' / (case + '.json')).read_text())
    def confirm(request):
        data = json.loads(request.prompt.user_suffix)
        scope = next(k for k, v in data['units'].items() if v['kind'] == 'scope')
        return json.dumps({'schema_version': CONTRACT, 'binding': data['binding'], 'status': 'confirmed',
            'findings': [{'unit_ids': [scope], 'source_text': raw['root']['source_text'][0],
                          'message': 'Authored gold confirms the printed problem; student work is excluded.',
                          'regions': [{'region_id': None, 'page_id': 'page_1', 'bbox': [0, 0, 1, 1]}]}]})
    client = _SequenceProvider([json.dumps(raw), confirm])
    run = ProblemDomainExtractionService(input_artifact_reader=store, output_artifact_store=store, provider=client).run(
        context, attempt_ledger=ExtractionAttemptLedger.for_context(context), ancestor_contexts=(initial,))
    assert run.accepted, [a.to_payload() for a in run.attempts]
    expected = ProblemDomainValidator().validate(ProblemDraft.create(raw)).projection
    assert run.solver_projection.canonical_input == expected.canonical_input
    assert pack.images and all(r.images for r in client.requests)
    if case in {'tj-2026-heping-yimo-25', 'tj-2026-xiqing-yimo-25'}:
        # These real scans contain student work. It retains its provenance and
        # never enters the printed evidence or the accepted gold conditions.
        assert {'handwritten', 'mixed'} <= {r.origin for r in pack.region_index}
        assert all(pack.region_by_id[t.observation_id].origin == 'printed' for t in pack.printed_text)
