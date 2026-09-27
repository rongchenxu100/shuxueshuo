"""Natural connectors preserve proof obligations and source positions."""
import pytest
import sympy as sp
from shuxueshuo_server.solver.math_kernel.derivation_math import parse_derivation
from shuxueshuo_server.solver.math_kernel.expression_parser import MathParseError, parse_math_relation
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
from shuxueshuo_server.solver.math_kernel.proof_kernel import ProofContext, verify_relation_sequence
from shuxueshuo_server.solver.math_kernel.expression_rewrite import verify_chain

SYMBOLS = {s: sp.Symbol(s, real=True) for s in 'abc'}


def test_conjunction_preserves_roles_positions_and_verifies_each_claim():
    source = '因为 a>b>c>0，所以 b>0 且 a-b>0'
    rows = parse_derivation([{'math': source}], SYMBOLS)
    assert [r.origin['marker'] for r in rows[-2:]] == ['∴', '∴']
    assert rows[-1].origin['language_tokens'][-1]['text'] == '且'
    for r in rows:
        assert r.parsed.source == ' '.join(source[a:b] for a, b in r.origin['segments'])
    ctx = ProofContext(SYMBOLS, {str(i): parse_math_relation(s, SYMBOLS)
                               for i, s in enumerate(['a>b', 'b>c', 'c>0'])})
    proofs = verify_relation_sequence([r.parsed for r in rows], ctx)
    verify_relation_sequence([r.parsed for r in rows], ctx, certificates=proofs)
    bad = parse_derivation([{'math': '∵ a>b；∴ a-b>0 且 b-a>0'}], SYMBOLS)
    with pytest.raises(ProofFailure):
        verify_relation_sequence([r.parsed for r in bad], ctx)


@pytest.mark.parametrize('source', ['且 a>0', 'a>0 且', 'a>0 且 且 b>0',
                                   'a>0 且 b', 'a>0 或 b>0', 'a>0 且 ∵ b>0'])
def test_conjunction_requires_complete_relations_with_same_role(source):
    with pytest.raises(MathParseError):
        parse_derivation([{'math': source}], SYMBOLS)


@pytest.mark.parametrize('source', [
    '因为 a>0，所以 a^2>0', '由于 a>0；因此 a^2>0',
    '由 a>0可得 a^2>0', '∵ a>0；∴ 满足 a^2>0',
    '因为 a>0，因此满足 a^2>0',
    '∵ a>0；满足 a^2>0',
])
def test_connectors_are_roles_with_exact_original_sources(source):
    rows = parse_derivation([{'math': source}], SYMBOLS)
    assert [r.origin['marker'] for r in rows] == ['∵', '∴']
    assert all(r.origin['source'] == source for r in rows)
    for r in rows:
        assert r.parsed.source == ' '.join(source[a:b] for a, b in r.origin['segments'])
    ctx = ProofContext(SYMBOLS, {'c': parse_math_relation('a>0', SYMBOLS)})
    proofs = verify_relation_sequence([r.parsed for r in rows], ctx)
    verify_relation_sequence([r.parsed for r in rows], ctx, certificates=proofs)


@pytest.mark.parametrize('source', [
    '∴ 不满足 a>0', '假设 a>0', '设 a=1', '取 a=1',
    '当且仅当 a=b 时取等', '取等条件为 a=b',
    'a+满足b>0', '∵ 因此 a>0', '∴ 因为 a>0',
    '因为', '所以满足', 'a>0满足b>0', '显然 a>0',
])
def test_no_silent_deletion_or_role_change(source):
    with pytest.raises(MathParseError) as caught:
        parse_derivation([{'math': source}], SYMBOLS)
    assert caught.value.source == source
    assert caught.value.source_path == '/parameters/steps/0/math'
    assert caught.value.span is not None


def test_false_because_is_not_an_assumption():
    rows = parse_derivation([{'math': '因为 a=b，所以 a=b'}], SYMBOLS)
    with pytest.raises(ProofFailure):
        verify_relation_sequence([r.parsed for r in rows], ProofContext(SYMBOLS))


def test_natural_local_rewrite_is_proved_and_whole_preserved():
    source = 'c^2+1/a+2/a'
    result = verify_chain(sp.sympify(source, locals=SYMBOLS), ['a>0'],
                         [{'math': '因为 1/a+2/a=3/a，所以 c^2+1/a+2/a=c^2+3/a'}],
                         SYMBOLS, input_source=source)
    assert sp.cancel(result['value']-sp.sympify(source, locals=SYMBOLS)) == 0


def test_historical_satisfies_clause_keeps_all_order_relations():
    source = '∵ √2>√2/2>√2/5>0；∴ 满足 a>b>c>0'
    rows = parse_derivation([{'math': source}], SYMBOLS)
    assert len(rows) == 8
    assert rows[-1].origin['chain_endpoint']
    assert rows[-1].origin['marker'] == '∴'


def test_scalar_relation_parser_stays_strict():
    with pytest.raises(MathParseError):
        parse_math_relation('因为 a>0', SYMBOLS)
