"""Frozen synthetic holdout; production evidence/validation/projection, no DB.

Offline replay proves wiring and negative checks, not LLM accuracy. Live tests
use real images and synthetic matching OCR (not a paid OCR integration).
"""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import ExtractionAttemptLedger, ExtractionRetryState, ProblemExtractionContextBuilder
from shuxueshuo_server.solver.extraction.handwriting import ConservativeInkOriginAnalyzer
from shuxueshuo_server.solver.extraction.multimodal_evidence import MultimodalEvidencePackBuilder, _selection_canvas
from shuxueshuo_server.solver.extraction.observation_context import ObservationContextTransitionService, f2_semantic_config
from shuxueshuo_server.solver.extraction.observation_pipeline import F2ObservationPipeline
from shuxueshuo_server.solver.extraction.observations import PaddleProviderRecord
from shuxueshuo_server.solver.extraction.source_identity import ExtractionDependencyManifest, ProblemSourceFingerprintService, SourceAssetInput, SourceSelection, SelectionRegion
from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft
from shuxueshuo_server.solver.extraction.problem_domain_service import ProblemDomainExtractionService
from shuxueshuo_server.solver.extraction.problem_domain_validation import ProblemDomainValidator
from shuxueshuo_server.solver.extraction.problem_domain_debug import ProblemDomainDebugWriter
from shuxueshuo_server.solver.extraction.semantic_diff import compare_solver_projection_semantics
from shuxueshuo_server.solver.extraction.multimodal_provider import create_vision_provider
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from _problem_extraction_f2_support import provider, successful_ledger

FIXTURES = Path(__file__).parent / 'fixtures/understanding-holdout-v1'
CASES = ('open-boundary', 'closed-boundary', 'sibling-local')


def gold(case):
    return json.loads((FIXTURES / case / 'gold.json').read_text())


def holdout_input(output, case):
    manifest = json.loads((FIXTURES / 'manifest.json').read_text())
    expected = next(item for item in manifest['cases'] if item['id'] == case)
    for name, digest in expected['files'].items():
        assert sha256((FIXTURES / case / name).read_bytes()).hexdigest() == digest
    content = (FIXTURES / case / 'source.png').read_bytes()
    raw = json.loads((FIXTURES / case / 'observation.json').read_text())
    source = ProblemSourceFingerprintService().fingerprint((SourceAssetInput(
        page_id='page_1', media_type='image/png', content_bytes=content, locator='fixture://source.png'),))
    selection = SourceSelection.create(source, mode='user_confirmed', revision=0,
        regions=(SelectionRegion('question', 'page_1', ((0,0),(1,0),(1,1),(0,1))),))
    lp, tp = provider('layout', 'authored-layout'), provider('text_ocr', 'authored-transcript')
    manifests = (lp, tp, ConservativeInkOriginAnalyzer().provider)
    dependency = ExtractionDependencyManifest.create(source, selection,
        semantic_config=f2_semantic_config([p.to_payload() for p in manifests]))
    initial = ProblemExtractionContextBuilder.initial(source=source, selection=selection, dependency=dependency,
        retry=ExtractionRetryState(attempt_budget=8), quality={'problem_id': gold(case)['problem_id']})
    records=[]
    for component, p in [('layout',lp),('text_ocr',tp)]:
        items = raw['items'] if component == 'text_ocr' else [
            {'label':'text','confidence':0.99,'polygon':i['polygon']} for i in raw['items']]
        records.append(PaddleProviderRecord.create(component=component, provider=p,
            source_revision_hash=source.source_revision_hash, page_id='page_1',
            width=raw['width'],height=raw['height'],items=items))
    store=ExtractionArtifactStore(output/'artifacts')
    crop=store.put_bytes(kind='selection_crop', content=_selection_canvas(initial,'page_1',content),media_type='image/png',suffix='.png')
    result=F2ObservationPipeline(artifact_store=store).assemble(source=source,selection=selection,dependency=dependency,
        page_bytes={'page_1':content},layout_records=(records[0],),text_records=(records[1],),extra_artifacts=(crop,))
    context=ObservationContextTransitionService().attach(initial,result.observation,artifacts=result.artifacts,
        attempt_ledger=successful_ledger(initial,result.artifacts))
    pack=MultimodalEvidencePackBuilder().build(context,artifact_reader=store,observation=result.observation)
    return initial,context,store,pack


def run_case(output, case, client):
    __tracebackhide__ = True  # Do not let pytest render the authenticated client argument.
    initial,context,store,pack=holdout_input(output,case)
    run=ProblemDomainExtractionService(input_artifact_reader=store,output_artifact_store=store,provider=client).run(
        context,attempt_ledger=ExtractionAttemptLedger.for_context(context),ancestor_contexts=(initial,),max_attempts=3)
    ProblemDomainDebugWriter().write(run,output)
    expected=ProblemDomainValidator().validate(ProblemDraft.create(gold(case)))
    actual=run.verified_problem.graph if run.verified_problem else None
    diff=compare_solver_projection_semantics(expected.projection.canonical_input,run.solver_projection.canonical_input) if run.solver_projection else None
    reviews=[a.source_review for a in run.attempts if a.source_review]
    networks=sum(len(a.provider_response.provider_attempts) if a.provider_response else
                 len(a.attempt_record.usage.get('provider_attempts',[])) for a in run.attempts)
    networks+=sum(len(r.get('usage',{}).get('provider_attempts',[])) for r in reviews)
    assert len(run.attempts)<=3 and len(reviews)<=3 and len(run.attempts)+len(reviews)<=6 and networks<=12
    for attempt in run.attempts:
        assert attempt.request.images and attempt.request.thinking_mode=='enabled' and attempt.request.reasoning_effort=='low'
        assert all(sha256(i.content).hexdigest()==i.artifact.sha256 for i in attempt.request.images)
    for review in reviews:
        assert review['usage']['thinking_mode']=='enabled' and review['usage']['reasoning_effort']=='low'
    summary={'reviews':reviews,'network_attempts':networks,'case':case,'accepted':run.accepted,'domain_ok':bool(actual and actual.semantic_hash==expected.draft.semantic_hash),
        'projection_diff':diff.to_payload() if diff else None,'attempts':len(run.attempts)}
    (output/'holdout-result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    assert run.accepted and summary['domain_ok'] and diff.ok, summary
    return run,pack


@pytest.mark.parametrize('case',CASES)
def test_holdout_gold_and_production_replay(tmp_path,case):
    from test_deepseek_vision import response, client_factory
    calls=[]
    def create(**options):
        calls.append(options)
        data=options['messages'][1]['content'][-1]['text']
        if '"binding"' in data and 'problem-source-review/v1' in data:
            data=json.loads(data)
            scope=next(k for k,v in data['units'].items() if v['kind']=='scope')
            return response(json.dumps({'schema_version':'problem-source-review/v1','binding':data['binding'],'status':'confirmed',
                'findings':[{'unit_ids':[scope],'source_text':gold(case)['root']['source_text'][0],
                    'message':'Synthetic recorded confirmation, not a live judgment.',
                    'regions':[{'region_id':None,'page_id':'page_1','bbox':[0,0,1,1]}]}]}))
        return response(json.dumps(gold(case),ensure_ascii=False))
    client=create_vision_provider(SolverRuntimeConfig(deepseek_api_key='test'),client_factory=client_factory([],[],{}))
    client._client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    run,pack=run_case(tmp_path,case,client)
    assert pack.images
    assert calls and all(c['extra_body']=={'thinking':{'type':'enabled'}} and c['reasoning_effort']=='low' for c in calls)


@pytest.mark.parametrize('mutation',['bound','coordinate','membership','goal','scope'])
def test_near_miss_conditions_remain_significant(mutation):
    original=gold('sibling-local' if mutation=='scope' else 'open-boundary')
    changed=deepcopy(original)
    root=changed['root']
    if mutation=='bound':next(f for f in root['facts'] if f['kind']=='symbol_constraint')['operator']='>='
    if mutation=='coordinate':next(f for f in root['facts'] if f['kind']=='point_coordinate')['value'][0]='-4'
    if mutation=='membership':root['facts']=[f for f in root['facts'] if f['kind']!='point_on_curve']
    if mutation=='goal':root['goals'][0]['expression']['terms'][0]['scale']='2'
    if mutation=='scope':root['children'][0]['facts'],root['children'][1]['facts']=root['children'][1]['facts'],root['children'][0]['facts']
    a,b=(ProblemDomainValidator().validate(ProblemDraft.create(p)) for p in (original,changed))
    assert a.report.ok
    assert a.draft.semantic_hash!=b.draft.semantic_hash
    # Domain identity is the acceptance authority for target payload and scope;
    # the legacy projection comparator deliberately discards some of these.
    if mutation not in {'goal', 'scope'}:
        assert b.projection is None or not compare_solver_projection_semantics(a.projection.canonical_input,b.projection.canonical_input).ok


@pytest.mark.live_llm
@pytest.mark.parametrize('case',CASES)
def test_live_frozen_holdout(tmp_path,case):
    from test_deepseek_vision import live_config
    config=live_config()
    output=Path(os.environ.get('UNDERSTANDING_HOLDOUT_OUTPUT',str(tmp_path)))/case
    output.mkdir(parents=True,exist_ok=False)
    from shuxueshuo_server.solver.extraction.problem_domain_smoke import _implementation_hashes
    repo=Path(__file__).resolve().parents[3]
    protocol={'implementation':_implementation_hashes(repo),
              'fixture_manifest_sha256':sha256((FIXTURES/'manifest.json').read_bytes()).hexdigest()}
    protocol_path=output.parent/'protocol.json'
    try:
        with protocol_path.open('x') as stream:
            json.dump(protocol,stream,indent=2,sort_keys=True)
    except FileExistsError:
        assert json.loads(protocol_path.read_text())==protocol, 'Implementation changed during batch'
    run_case(output,case,create_vision_provider(config))


@pytest.mark.parametrize('status',['correction_required','uncertain'])
def test_independent_negative_review_blocks_adoption(tmp_path,status):
    from test_problem_domain_recorded import _RecordedProvider
    initial,context,store,_=holdout_input(tmp_path,'open-boundary')
    wrong=gold('open-boundary')
    next(f for f in wrong['root']['facts'] if f['kind']=='point_coordinate')['value'][0]='-4'
    class Client(_RecordedProvider):
        def complete(self,request):
            if request.contract_version!='problem-source-review/v1':
                return super().complete(request)
            data=json.loads(request.prompt.user_suffix)
            root=next(k for k,v in data['units'].items() if v['kind']=='scope')
            result={'schema_version':'problem-source-review/v1','binding':data['binding'],'status':status,
                'findings':[{'unit_ids':[root],'source_text':'P(-3,5)',
                    'message':'候选横坐标与原图不同' if status=='correction_required' else '无法确定该区域',
                    'regions':[{'region_id':None,'page_id':'page_1','bbox':[0,0,1,1]}]}]}
            return _RecordedProvider(json.dumps(result)).complete(request)
    client=Client(json.dumps(wrong))
    run=ProblemDomainExtractionService(input_artifact_reader=store,output_artifact_store=store,provider=client).run(
        context,attempt_ledger=ExtractionAttemptLedger.for_context(context),ancestor_contexts=(initial,),max_attempts=1)
    assert not run.accepted and run.verified_problem is None
    assert run.attempts[0].source_review['status']==status


def test_review_and_extraction_share_conditional_representation_rules(tmp_path):
    from shuxueshuo_server.solver.extraction.problem_source_review import build_review_request
    from shuxueshuo_server.solver.extraction.problem_domain_prompt_rules import DOMAIN_RULES, REPRESENTATION_RULES
    _,_,store,pack=holdout_input(tmp_path,'open-boundary')
    request=build_review_request(ProblemDraft.create(gold('open-boundary')),pack,store,{'differences':[]},'json_object')
    assert json.loads(request.prompt.user_suffix)['representation_rules']==REPRESENTATION_RULES
    assert REPRESENTATION_RULES in DOMAIN_RULES
    assert '不能作为候选正确的证据' in REPRESENTATION_RULES
