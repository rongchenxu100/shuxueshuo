"""Fresh-process checker benchmark with a separate trusted authority fixture."""
import argparse
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'server'))
import sympy as sp
from shuxueshuo_server.solver.math_kernel import SympyKernel, proof_kernel
from shuxueshuo_server.solver.math_kernel.expression_parser import parse_math_relation
from shuxueshuo_server.solver.math_kernel.proof_facts import FactValidity
from shuxueshuo_server.solver.math_kernel.proof_search import SearchScheduler
from shuxueshuo_server.solver.math_kernel.proof_types import ProofContext, ProofLimits
from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.models import RuntimeScope
from shuxueshuo_server.solver.runtime.scoped_proof_facts import ProofCallAuthority, ScopedProofFacts

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--authority-sha256', required=True)
args = parser.parse_args()
raw = Path(__file__).with_name('q30-authority.json').read_bytes()
assert hashlib.sha256(raw).hexdigest() == args.authority_sha256
fixture = json.loads(raw)
symbols = {n: sp.Symbol(n, real=True) for n in fixture['symbols']}
source = ProofContext(symbols, {k: replace(parse_math_relation(p['source'], symbols), source_path=p['source_path'], step=p['step']) for k, p in fixture['premises'].items()}, ProofLimits(**fixture['limits']), fixture['scope_id'])
context = RuntimeContext(ProblemIR('q30-cold-replay', '', '', list(symbols)), SympyKernel(), symbols)
context.proof_protocol = 'scoped-facts/v2'
context.scopes = {name: RuntimeScope(name, 'question', parent_id=parent) for name, parent in fixture['scopes'].items()}
calls = [ProofCallAuthority(**{**c, 'validity': FactValidity(**c['validity'])}) for c in fixture['calls']]
store = ScopedProofFacts(context, source, fixture['bindings'], calls)
path = ROOT / 'docs/validation/scoped-proof-search-stage-e/q30-review-proof-snapshot.json.gz'
payload = json.loads(gzip.decompress(path.read_bytes()))['facts']
# Output identities are also external fixture authority, not taken from a saved
# certificate on behalf of Runtime. This benchmark checks a fixed archived run.
expected = fixture['output_hashes']
def forbidden(*a, **kw):
    raise AssertionError('cold replay called search')
from shuxueshuo_server.solver.math_kernel.real_proof_strategies import ScheduledRealSearch
ScheduledRealSearch.need = forbidden
proof_kernel._run_request = forbidden
SearchScheduler.prove = forbidden
replayed = []
original = ScopedProofFacts._restore_one
def counted(self, item):
    replayed.append(item['call_id'])
    return original(self, item)
ScopedProofFacts._restore_one = counted
start = perf_counter()
store.restore(payload, expected)
elapsed = perf_counter() - start
assert store.to_payload() == payload
assert replayed == ['rewrite', 'first', 'square', 'last', 'attain']
print(json.dumps({'seconds': elapsed, 'replayed_commits': replayed, 'search_disabled': True, 'fresh_process': True}))
