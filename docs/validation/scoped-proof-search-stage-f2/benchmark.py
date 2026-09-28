"""Recorded q30 F2 benchmark: real proofs, cold replay, warm view, Runtime Retry."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'server'), str(ROOT / 'server/tools')]
from run_basic_inequality_stage4a import run
from shuxueshuo_server.solver.runtime.scoped_proof_facts import ScopedProofFacts
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    FunctionalTransactionalInterpreter, build_functional_execution_restore_seed,
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--work', type=Path, required=True)
parser.add_argument('--repeats', type=int, default=3)
parser.add_argument('--export-authority', type=Path)
parser.add_argument('--mode', choices=('full_diagnostic', 'compact_audit'), default='full_diagnostic')
args = parser.parse_args()
fixture = ROOT / 'server/tests/solver/fixtures'
execute = FunctionalTransactionalInterpreter.execute_attempt
restore_one = ScopedProofFacts._restore_one
from shuxueshuo_server.solver.runtime import orchestrator as orchestrator_module
write_attempt = orchestrator_module._write_debug_attempt
artifact_seconds = [0.0]
def timed_write(*a, **kw):
    start = perf_counter()
    try:
        return write_attempt(*a, **kw)
    finally:
        artifact_seconds[0] += perf_counter() - start
orchestrator_module._write_debug_attempt = timed_write
counts = {'replayed_commits': 0}
captured = []

def capture(self, **kwargs):
    result = execute(self, **kwargs)
    captured.append((self, kwargs, result))
    return result

def counted(self, payload):
    counts['replayed_commits'] += 1
    return restore_one(self, payload)

FunctionalTransactionalInterpreter.execute_attempt = capture
ScopedProofFacts._restore_one = counted
samples = []
for index in range(args.repeats):
    sample = {}
    artifact_seconds[0] = 0.0
    def measure(name, action):
        counts['replayed_commits'] = 0
        start = perf_counter()
        value = action()
        sample[name] = {'seconds': perf_counter() - start, **counts}
        return value
    result, runtime = measure('solve_with_artifacts', lambda: run(
        gold=fixture / 'math-notation-v1/basic-inequality/q30.json',
        problem_ir=fixture / 'basic-inequality-problem-ir/v1/q30/problem-ir.json',
        plan=fixture / 'basic-inequality-stage5c/q30.json',
        output=args.work / str(index), mode='recorded', proof_protocol='scoped-facts/v2', debug_artifact_mode=args.mode,
    ))
    assert result.status == 'ok' and result.answers == {'problem': {'minimum': '4'}}
    sample['artifact_seconds'] = artifact_seconds[0]
    store = runtime.last_success_artifacts.context.proof_facts
    payload = store.to_payload()
    if args.export_authority:
        # Trusted benchmark input, captured from authenticated Runtime authority,
        # stored separately from certificates. Never a production restore API.
        args.export_authority.write_text(json.dumps({
            'output_hashes': {c.call_id: c.output_hash for c in store.snapshot.commits},
            'symbols': list(store.source_context.symbols),
            'scope_id': store.source_context.scope_id,
            'limits': asdict(store.source_context.limits),
            'premises': {k: {'source': p.source, 'source_path': p.source_path, 'step': p.step}
                         for k, p in store.source_context.premises.items()},
            'bindings': store.bindings,
            'calls': [asdict(c) for c in store.calls],
            'scopes': {k: scope.parent_id for k, scope in store.context.scopes.items()},
        }, indent=2) + '\n')
    hashes = {c.call_id: c.output_hash for c in store.snapshot.commits}
    fresh = ScopedProofFacts(store.context, store.source_context, store.bindings, store.calls)
    measure('cold_restore', lambda: fresh.restore(payload, hashes))
    assert fresh.to_payload() == payload
    measure('warm_verify', fresh.verify_snapshot)
    interpreter, kwargs, original = captured[-1]
    seed = build_functional_execution_restore_seed(original.execution_report, kwargs['reconciliation'])
    retried = measure('runtime_retry', lambda: execute(interpreter, **{**kwargs, 'restored_seed': seed}))
    assert retried.execution_report.ok
    assert retried.execution_report.runtime_context.proof_facts.to_payload() == payload
    encoded = measure('snapshot_serialization', lambda: json.dumps(store.to_payload(), sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode())
    sample['snapshot_bytes'] = len(encoded)
    sample['snapshot_sha256'] = hashlib.sha256(encoded).hexdigest()
    assert not runtime.debug_journal._latest and not runtime.debug_journal._versions
    sample['artifact_metrics'] = dict(runtime.debug_journal.metrics)
    files = list((args.work / str(index)).rglob('*'))
    unique = {}
    for path in files:
        if path.is_file():
            stat = path.stat()
            unique[(stat.st_dev, stat.st_ino)] = stat.st_size
    sample['artifact_unique_bytes'] = sum(unique.values())
    sample['artifact_file_count'] = sum(p.is_file() for p in files)
    for path in (args.work / str(index)).glob('attempt-*.evidence-index.json'):
        evidence_index = json.loads(path.read_text())
        for artifact in evidence_index['artifacts'].values():
            if artifact['status'] == 'saved':
                data = (path.parent / artifact['file']).read_bytes()
                assert hashlib.sha256(data).hexdigest() == artifact['sha256']
        checkpoint = json.loads((path.parent / evidence_index['artifacts']['checkpoint']['file']).read_text())
        # The actual emitted checkpoint must retain the full proof-fact closure.
        def find_snapshot(value):
            if isinstance(value, dict):
                if value.get('manifest_hash') == payload.get('manifest_hash') and value == payload:
                    return True
                return any(find_snapshot(v) for v in value.values())
            if isinstance(value, list):
                return any(find_snapshot(v) for v in value)
            return False
        assert find_snapshot(checkpoint), 'emitted checkpoint lost proof-fact closure'
    samples.append(sample)
    print(json.dumps(sample), flush=True)
    args.output.write_text(json.dumps({'samples': samples}, indent=2) + '\n')
scenarios = ('solve_with_artifacts', 'cold_restore', 'warm_verify', 'runtime_retry', 'snapshot_serialization')
summary = {name: {'median_seconds': statistics.median(s[name]['seconds'] for s in samples), 'range_seconds': [min(s[name]['seconds'] for s in samples), max(s[name]['seconds'] for s in samples)], 'replayed_commits': [s[name]['replayed_commits'] for s in samples]} for name in scenarios}
args.output.write_text(json.dumps({'samples': samples, 'summary': summary, 'live_llm_calls': 0, 'artifact_mode': args.mode, 'note': 'Sequential repeats in one process, fresh Runtime per solve; cold restore uses a new fact store with empty verification memo. Selected artifact mode; all canonical audit roles and cold replay retained.'}, indent=2) + '\n')
