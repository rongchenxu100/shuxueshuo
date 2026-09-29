"""Offline nested timers; wraps boundaries only, not recursive math/JSON walkers."""
from pathlib import Path

source_path = Path(__file__).with_name('phase-timing.py')
source = source_path.read_text()
# Preserve the existing top-level timers, and retain full paths for attribution.
source = source.replace("'parent':parent,'inclusive_seconds'", "'parent':parent,'path':[f[0] for f in stack]+[label],'inclusive_seconds'")
source = source.replace("start=time.perf_counter();frame=[label,0]", "start=time.perf_counter();cpu_start=time.process_time();frame=[label,0,0]")
source = source.replace("elapsed=time.perf_counter()-start;stack.pop()", "elapsed=time.perf_counter()-start;cpu_elapsed=time.process_time()-cpu_start;stack.pop()")
source = source.replace("if stack:stack[-1][1]+=elapsed", "if stack:stack[-1][1]+=elapsed;stack[-1][2]+=cpu_elapsed")
source = source.replace("'exclusive_seconds':elapsed-frame[1]", "'exclusive_seconds':elapsed-frame[1],'cpu_seconds':cpu_elapsed,'exclusive_cpu_seconds':cpu_elapsed-frame[2]")
source = source.replace("start=time.perf_counter();r,rt=", "cpu_run_start=time.process_time();start=time.perf_counter();r,rt=")
source = source.replace("report={'total_seconds':elapsed,", "report={'total_seconds':elapsed,'total_cpu_seconds':time.process_time()-cpu_run_start,")
source = source.replace("mode='recorded',replay_from", "mode='recorded',debug_artifact_mode=sys.argv[2] if len(sys.argv)>2 else 'full_diagnostic',replay_from")
extra = '''
from shuxueshuo_server.solver.runtime import functional_goal_execution as fg, llm_debug as ld
from shuxueshuo_server.solver.runtime import functional_attempt_evidence as ae, scoped_proof_facts as sf
from shuxueshuo_server.solver.result_models import SolverResult
from shuxueshuo_server.solver.math_kernel import method_proof_session as ms
from shuxueshuo_server.solver.runtime.scoped_proof_facts import SessionFactOverlay
from inspect import getattr_static

def boundary(obj, name, label):
 descriptor = getattr_static(obj, name)
 if isinstance(descriptor, classmethod):
  # The existing timer wraps functions; retain descriptor binding explicitly.
  setattr(obj, name, descriptor.__func__)
  wrap(obj, name, label)
  setattr(obj, name, classmethod(getattr(obj, name)))
 else:
  wrap(obj, name, label)

for obj,name,label in [
(om.RuntimeOrchestrator,'solve_verified','solver_orchestration'),
(om.RuntimeOrchestrator,'__init__','runtime_initialization'),
(SolverResult,'to_dict','result_payload'),
(ScopedProofFacts,'_verification_key','fact_verification_key'),
(sf,'canonical','fact_canonical_json'),
(sf,'digest','fact_record_hash'),
(ms,'run_scheduled_request','search_and_check'),
(fg,'_public_runtime_result_value','public_result_projection'),
(fg,'_prompt_safe_inputs','input_projection'),
(fg,'_build_checkpoint','checkpoint_build'),
(fg,'_transaction_execution_evidence','execution_evidence_build'),
(fg,'_provisional_state_payload','state_payload'),
(fg,'_compiled_restore_authority_payload','restore_authority_payload'),
(fg,'_audit_prompt_checkpoint','prompt_audit'),
(fg,'stable_hash','checkpoint_module_hash'),
(fg.FunctionalExecutionRestoreState,'from_transaction','restore_state_build'),
(fg.FunctionalExecutionRestoreState,'_payload','restore_state_payload'),
(fg.FunctionalGoalExecutionCheckpoint,'authority_payload','checkpoint_payload'),
(fg.FunctionalGoalExecutionCheckpoint,'to_prompt_payload','checkpoint_prompt_view'),
(fg.FunctionalGoalExecutionScope,'authority_payload','scope_authority_payload'),
(tx,'proof_output_hash','output_hash'),
(ScopedProofFacts,'publish','fact_register'),
(ScopedProofFacts,'verify_snapshot','verify_snapshot'),
(SessionFactOverlay,'finish','fact_finalize'),
(ld.DebugArtifactJournal,'write_json','debug_json'),
(ld.DebugArtifactJournal,'_publish','debug_publish'),
(ld,'_atomic_text','debug_write'),
(ld.DebugArtifactJournal,'_link_latest','debug_link'),
(ae,'write_scoped_attempt_evidence','audit_artifacts'),
]:boundary(obj,name,label)
from types import SimpleNamespace
original_dumps = json.dumps
result_encoder = SimpleNamespace(dumps=original_dumps)
wrap(result_encoder, 'dumps', 'harness_result_json')
def measured_dumps(*args, **kwargs):
 if not stack and args and isinstance(args[0], dict) and 'status' in args[0] and sys._getframe(1).f_code.co_name == 'run':
  return result_encoder.dumps(*args, **kwargs)
 return original_dumps(*args, **kwargs)
json.dumps = measured_dumps
'''
source = source.replace("f=root/'server/tests/solver/fixtures'", extra+"f=root/'server/tests/solver/fixtures'")
exec(compile(source,str(source_path),'exec'),dict(__file__=str(source_path),__name__='__main__'))
