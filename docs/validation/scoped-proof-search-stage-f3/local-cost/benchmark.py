import sys,time,json
from pathlib import Path
root=Path(__file__).resolve().parents[4];sys.path[:0]=[str(root/'server'),str(root/'server/tools')]
from run_basic_inequality_stage4a import run
from shuxueshuo_server.solver.runtime import method_proof_integration as mi,orchestrator as om
from shuxueshuo_server.solver.runtime.scoped_proof_facts import ScopedProofFacts
counters={}
def wrap(obj,name,label):
 fn=getattr(obj,name)
 def timed(*a,**kw):
  t=time.perf_counter()
  try:return fn(*a,**kw)
  finally:
   s=counters.setdefault(label,{'seconds':0,'calls':0});s['seconds']+=time.perf_counter()-t;s['calls']+=1
 setattr(obj,name,timed)
for obj,name in [(mi,'method_search_service'),(mi,'publish_method_result'),(om,'_write_debug_attempt'),(ScopedProofFacts,'_restore_one')]:wrap(obj,name,name)
f=root/'server/tests/solver/fixtures';base=root/'internal/review-analysis/scoped-proof-search-stage-f3'
out=base/sys.argv[1]; mode=sys.argv[2] if len(sys.argv)>2 else 'full_diagnostic'
t=time.perf_counter()
r,rt=run(gold=f/'math-notation-v1/basic-inequality/q30.json',problem_ir=f/'basic-inequality-problem-ir/v1/q30/problem-ir.json',output=out,mode='recorded',replay_from=base/'live-02/planner-01',debug_artifact_mode=mode)
report={'status':r.status,'seconds':time.perf_counter()-t,'answers':r.answers,'sections':counters,'mode':mode}
(out/'timing.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
