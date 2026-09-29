"""Re-prove exactly the Stage D requests, without recapturing Method execution."""
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'server'), str(ROOT / 'server/tools')]
import sympy as sp
from proof_search_legacy import LegacySearch
from shuxueshuo_server.solver.math_kernel.expression_parser import parse_math_relation
from shuxueshuo_server.solver.math_kernel.proof_checker import replay_proof
from shuxueshuo_server.solver.math_kernel.proof_search import run_scheduled_request
from shuxueshuo_server.solver.math_kernel.proof_types import ProofContext, ProofLimits, _Budget

out = Path(__file__).parent
source = out.parent / 'scoped-proof-search-stage-d'
report = {'input_archives': {}, 'proved': 0, 'deferred_witness_drivers': 0, 'failures': []}
def forbidden(*args, **kwargs):
    raise AssertionError('new search called historical implementation')
with patch.object(LegacySearch, 'need', forbidden):
    for path in sorted(source.glob('live*.json.gz')):
        report['input_archives'][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        rows = json.loads(gzip.decompress(path.read_bytes()))
        output = []
        for index, row in enumerate(rows):
            if row.get('status') == 'witness_driver_stage_e':
                report['deferred_witness_drivers'] += 1
                output.append(row)
                continue
            raw = row['context']
            symbols = {n: sp.Symbol(n, real=True) for n in raw['symbols']}
            ctx = ProofContext(symbols, {k: replace(parse_math_relation(v['source'], symbols), source_path=v['source_path'], step=v['step']) for k, v in raw['premises'].items()}, ProofLimits(**raw['limits']), raw['scope_id'])
            run = run_scheduled_request(ctx, row['request'], budget=_Budget(ProofLimits(**row['effective_limits'])))
            replay = replay_proof(run.result.proof, ctx) if run.result.status == 'proved' else None
            if replay is None or replay.status != 'proved':
                report['failures'].append({'archive':path.name,'index':index,'result':run.result.to_payload()})
            else:
                report['proved'] += 1
            output.append({**row, 'result':run.result.to_payload(), 'replay':replay.status if replay else None,'diagnostics':run.diagnostics})
        (out / 'proofs' / path.name).write_bytes(gzip.compress(json.dumps(output,ensure_ascii=False).encode(),mtime=0))
(out / 'exact-frozen-search.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False))
raise SystemExit(bool(report['failures']))
