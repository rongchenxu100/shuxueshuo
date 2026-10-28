"""Teaching projections must explain the independently verified generic proof."""

from shuxueshuo_server.graph_lesson.function_equality import compare_pair
from shuxueshuo_server.graph_lesson.stage_three.equality_presentation import view
from shuxueshuo_server.graph_lesson.stage_three.equality_runtime import compare_function_pair
from tests.solver.test_graph_function_equality_math import descriptor


def pair(left, right, domain=None):
    return {'label': 'A', 'left': descriptor(left, domain=domain),
            'right': descriptor(right, domain=domain, function_ref='option:A:g')}


def test_generic_radical_proof_explains_sign_and_square_with_knowledge_basis():
    option = pair('x*sqrt(x^2+1)', 'sqrt(x^2+1)*x')
    comparison = compare_pair(option['left'], option['right'])
    text = view({'option': option, 'comparison': comparison, 'phase': 'correspondence'})['equality_explanation']
    assert '两式均为负数' in text and '两式均为正数' in text
    assert '且平方都为' in text and '这些范围覆盖整个共同定义域' in text
    runtime = compare_function_pair(option, comparison['left']['natural_domain'], comparison['right']['natural_domain'])
    assert 'signed_square_on_sign_cell' in runtime['operations']
    assert 'square_of_real_square_root' in runtime['operations']


def test_generic_rational_proof_keeps_the_original_domain_in_student_explanation():
    option = pair('(x^4-1)/(x^2-1)', 'x^2+1', 'ℝ setminus {-1,1}')
    comparison = compare_pair(option['left'], option['right'])
    text = view({'option': option, 'comparison': comparison, 'phase': 'correspondence'})['equality_explanation']
    assert '保留原式中分母不为零等限制' in text
    runtime = compare_function_pair(option, comparison['left']['natural_domain'], comparison['right']['natural_domain'])
    assert 'bounded_rational_normal_form' in runtime['operations']


def test_different_domains_explanation_does_not_claim_correspondence_was_checked():
    option = pair('sqrt(x-1)*sqrt(x+1)', 'sqrt((x+1)*(x-1))')
    comparison = compare_pair(option['left'], option['right'])
    text = view({'option': option, 'comparison': comparison, 'phase': 'verdict'})['equality_explanation']
    assert '定义域比较' in text and '对应关系' not in text
