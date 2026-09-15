"""Independent syntax and semantic near-miss tests; no five-case gold imports."""
from copy import deepcopy

import pytest

from shuxueshuo_server.solver.extraction.expression_normalization import normalize_expression_spelling as norm
from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft
from shuxueshuo_server.solver.extraction.problem_domain_validation import ProblemDomainValidator
from shuxueshuo_server.solver.extraction.semantic_diff import compare_solver_projection_semantics


@pytest.mark.parametrize('left,right', [
    ('(7*sqrt(13))/3', '7*sqrt(13)/3'), ('((p-q))', 'p-q'),
    ('x^3', 'x**3'), ('(p+q)/r', '((p+q))/(r)'),
    ('7 * (p-q) = (r)', '7*(p-q)=r'), ('-((p))', '-p'),
])
def test_spelling_equivalence(left, right):
    assert norm(left) == norm(right)
    assert norm(norm(left)) == norm(left)


@pytest.mark.parametrize('left,right', [
    ('p*q', 'p**q'), ('p*q', 'pq'), ('p/(q*r)', 'p/q*r'),
    ('(p+q)/r', 'p+q/r'), ('p-p', '0'), ('p/p', '1'),
    ('sqrt(p**2)', 'p'), ('sqrt(p*q)', 'sqrt(p)*sqrt(q)'),
    ('-p**2', '(-p)**2'), ('p-(q-r)', 'p-q-r'),
    ('p**(q**r)', '(p**q)**r'), ('p/q', 'q/p'),
    ('1.0000000000000000001', '1.0000000000000000002'),
])
def test_does_not_erase_math_or_domain_restrictions(left, right):
    assert norm(left) != norm(right)


@pytest.mark.parametrize('text', ['x[0]', 'f(x=1)', '__import__("os").system("false")', 'a<0', 'a=b=c', 'x('])
def test_unsupported_syntax_is_not_repaired(text):
    assert norm(text) == text.replace(' ', '')


def test_large_inputs_do_not_evaluate_or_overflow():
    assert norm('9**999999999') == '9**999999999'
    text = '(' * 500 + 'x' + ')' * 500
    assert norm(text) == text


def test_domain_and_projection_share_normalization_without_rewriting_revision():
    from test_understanding_holdout import gold
    payload = gold('open-boundary')
    base = ProblemDraft.create(payload)
    changed = deepcopy(payload)
    changed['root']['facts'][0]['expression'] = '(x**2)-(4)'
    alternate = ProblemDraft.create(changed)
    assert base.semantic_hash == alternate.semantic_hash
    assert base.revision_id != alternate.revision_id
    assert alternate.graph.wire_payload() == changed
    a = ProblemDomainValidator().validate(base)
    b = ProblemDomainValidator().validate(alternate)
    assert a.report.ok and b.report.ok
    assert compare_solver_projection_semantics(a.projection.canonical_input, b.projection.canonical_input).ok


@pytest.mark.parametrize('expression', ['x*2-4', 'x**2+4', 'x**2/4'])
def test_real_operator_change_fails_both_comparisons(expression):
    from test_understanding_holdout import gold
    original = gold('open-boundary')
    changed = deepcopy(original)
    changed['root']['facts'][0]['expression'] = expression
    a, b = (ProblemDomainValidator().validate(ProblemDraft.create(p)) for p in (original, changed))
    assert a.draft.semantic_hash != b.draft.semantic_hash
    assert not compare_solver_projection_semantics(a.projection.canonical_input, b.projection.canonical_input).ok


@pytest.mark.parametrize('operator', ['>=', '<=', '!=', '>', '<', '='])
def test_constraint_parser_preserves_full_operator(operator):
    from shuxueshuo_server.solver.math_kernel import SympyKernel
    from shuxueshuo_server.solver.runtime.context import _parse_constraint
    result = _parse_constraint(operator+'7/3', SympyKernel(), {})
    assert result['operator'] == operator
    assert str(result['value']) == '7/3'


def test_shared_target_cannot_hoist_sibling_local_endpoints():
    from test_understanding_holdout import gold
    from shuxueshuo_server.solver.extraction.problem_domain_canonicalization import ProblemDomainCanonicalizer
    payload = gold('sibling-local')
    result = ProblemDomainCanonicalizer().canonicalize(ProblemDraft.create(payload))
    assert not any(a.code=='materialize_shared_minimum_target' for a in result.actions)
    assert not any(f.kind=='minimum_target' for f in result.draft.graph.root_scope.facts)
    assert ProblemDomainValidator().validate(result.draft).report.ok
