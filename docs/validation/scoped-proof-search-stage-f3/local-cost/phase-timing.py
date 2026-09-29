import sys,time,json,functools,collections
from pathlib import Path
root=Path(__file__).resolve().parents[4];sys.path[:0]=[str(root/'server'),str(root/'server/tools')]
import run_basic_inequality_stage4a as harness
from shuxueshuo_server.solver.runtime import method_proof_integration as mi,orchestrator as om,proof_fact_transactions as tx
from shuxueshuo_server.solver.runtime.scoped_proof_facts import ScopedProofFacts
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import StrategyPlanner
from shuxueshuo_server.solver.runtime.functional_goal_execution import ScopedFunctionalGoalExecutionService
from shuxueshuo_server.solver.runtime.functional_transaction_execution import FunctionalTransactionalInterpreter
from shuxueshuo_server.solver.runtime.executor import InvocationExecutor
from shuxueshuo_server.solver.runtime.methods.organize_expressions import OrganizeExpressionsMethod
from shuxueshuo_server.solver.runtime.methods.apply_two_term_amgm import ApplyTwoTermAmgmMethod
from shuxueshuo_server.solver.runtime.methods.bound_univariate_quadratic import BoundUnivariateQuadraticMethod
from shuxueshuo_server.solver.runtime.methods.close_equality_and_restore import CloseEqualityAndRestoreMethod
from shuxueshuo_server.solver.math_kernel import bound_chain,proof_search
from shuxueshuo_server.solver.math_kernel.proof_rule_registry import RuleRegistry
stack=[];events=[];details=collections.defaultdict(lambda:{'seconds':0,'calls':0});active=set()
def wrap(obj,name,label):
 fn=getattr(obj,name)
 @functools.wraps(fn)
 def timed(*args,**kw):
  start=time.perf_counter();frame=[label,0];parent=stack[-1][0] if stack else None;stack.append(frame)
  try:return fn(*args,**kw)
  finally:
   elapsed=time.perf_counter()-start;stack.pop()
   if stack:stack[-1][1]+=elapsed
   events.append({'phase':label,'parent':parent,'inclusive_seconds':elapsed,'exclusive_seconds':elapsed-frame[1]})
 setattr(obj,name,timed)
def detail(obj,name,label):
 fn=getattr(obj,name)
 @functools.wraps(fn)
 def timed(*a,**kw):
  if label in active:return fn(*a,**kw)
  active.add(label);phase=stack[-1][0] if stack else 'unclassified';start=time.perf_counter()
  try:return fn(*a,**kw)
  finally:
   active.remove(label);r=details[phase+' / '+label];r['seconds']+=time.perf_counter()-start;r['calls']+=1
 setattr(obj,name,timed)
for obj,name,label in [
(harness,'load_frozen_authoring_bundle','input_bundle'),(harness.ReplayClient,'complete','recorded_response_read'),
(StrategyPlanner,'run_scoped','planner_orchestration'),(ScopedFunctionalGoalExecutionService,'execute_raw_json','plan_compilation_binding'),
(FunctionalTransactionalInterpreter,'execute_attempt','transaction_orchestration'),(InvocationExecutor,'execute_invocation','invocation_io'),
(mi,'prepare_scoped_call','fact_authority'),(mi,'method_search_service','fact_index'),(mi,'publish_method_result','fact_publication'),
(tx,'finalize_call','fact_commit'),(om,'_write_debug_attempt','debug_artifacts'),
(OrganizeExpressionsMethod,'run','M01'),(ApplyTwoTermAmgmMethod,'run','M11'),(BoundUnivariateQuadraticMethod,'run','M12'),(CloseEqualityAndRestoreMethod,'run','M13')]:wrap(obj,name,label)
for obj,name,label in [(mi.PremiseFactIndex,'extend','premise_index_extend'),(mi,'match_premise_fact','premise_fact_match'),(ScopedProofFacts,'_restore_one','commit_replay'),(bound_chain,'replay_bound','historical_bound_replay'),(RuleRegistry,'replay','checker_replay'),(proof_search,'run_scheduled_request','search')]:detail(obj,name,label)
f=root/'server/tests/solver/fixtures';base=root/'internal/review-analysis/scoped-proof-search-stage-f3';out=base/sys.argv[1]
start=time.perf_counter();r,rt=harness.run(gold=f/'math-notation-v1/basic-inequality/q30.json',problem_ir=f/'basic-inequality-problem-ir/v1/q30/problem-ir.json',output=out,mode='recorded',replay_from=base/'live-02/planner-01');elapsed=time.perf_counter()-start
phases=collections.defaultdict(lambda:{'seconds':0,'calls':0})
for e in events:
 p=phases[e['phase']];p['seconds']+=e['exclusive_seconds'];p['calls']+=1
phases['unclassified']={'seconds':elapsed-sum(p['seconds'] for p in phases.values()),'calls':1}
report={'total_seconds':elapsed,'status':r.status,'answers':r.answers,'exclusive_phases':dict(phases),'inclusive_details':dict(details),'events':events,'note':'Lightweight nested timers. exclusive_phases are disjoint and sum to total; inclusive_details overlap and must not be summed. No provider call. Timers include incremental premise-index construction.'}
(out/'timing.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False),flush=True)
