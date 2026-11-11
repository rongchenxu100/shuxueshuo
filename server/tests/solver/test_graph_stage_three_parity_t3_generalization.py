"""Recognition, execution, certificate and teaching export for the generalized FP-T3 mechanisms."""
import pytest

from shuxueshuo_server.graph_lesson.stage_three import runner
from tests.solver.test_graph_function_parity_recognition import recognize
from tests.solver.test_graph_parity_extension import candidate
from tests.solver.test_graph_parity_t3_generalization import multi_rule_candidate
from tests.solver.test_graph_symmetry_value import candidate as value_candidate
from tests.solver.test_graph_symmetry_value import pair_goal, rule_goal
from tools.export_graph_walk_course import export_course


def generalized_candidate(name):
    if name == 'multiple_rules':
        return multi_rule_candidate(consistent=True)
    if name == 'absolute':
        return candidate('a07', rule='abs(x-1)',
                         text=r'已知函数 $f(x)$ 是定义域为 $\mathbf R$ 的偶函数，当 $x\ge0$ 时，$f(x)=|x-1|$，'
                              r'则当 $x<0$ 时，$f(x)=$____．')
    if name == 'both':
        return candidate('a08', prop='both', rule='0', known='(1,2)', requested='ℝ',
                         text=r'函数 $f(x)$ 是定义在 $\mathbf R$ 上既是奇函数又是偶函数，当 $1<x<2$ 时，$f(x)=0$，'
                              r'则当 $x\in\mathbf R$ 时，$f(x)=$____．')
    if name == 'rational':
        value = candidate('a07', domain='ℝ∖{-1,1}', rule='(x^2-1)/(x-1)',
                          text=r'已知函数 $f(x)$ 是定义域为 $\mathbf R\setminus\{-1,1\}$ 的偶函数，'
                               r'当 $x\ge0$ 时，$f(x)=\frac{x^2-1}{x-1}$，则 $f(x)$ 的解析式是____．')
        del value['root']['goals'][0]['requested_domain']
        return value
    if name == 'irrational_input':
        return value_candidate(goal=rule_goal('f(-sqrt(2))', rule='x^2+x'),
                               text=r'已知函数 $f(x)$ 是定义在 $\mathbf R$ 上的奇函数，当 $x>0$ 时，$f(x)=x^2+x$，'
                                    r'则 $f(-sqrt(2))=$____．')
    if name == 'irrational_endpoint':
        return candidate('a08', domain='[-sqrt(2),sqrt(2)]', rule='x^2', known='(0,sqrt(2)]', requested='[-sqrt(2),0]',
                         text=r'已知函数 $f(x)$ 是定义在 $[-\sqrt{2},\sqrt{2}]$ 上的奇函数，'
                              r'当 $0<x\le\sqrt{2}$ 时，$f(x)=x^2$，则当 $-\sqrt{2}\le x\le0$ 时，$f(x)=$____．')
    if name == 'local_value':
        return value_candidate(facts=['parity(f,odd)', '∀x∈(0,2):f(x)=x', '∀x∈(-2,0):f(x)=x'],
                               goal={'kind': 'find_value', 'expression': 'f(-1)'},
                               text=r'已知函数 $f(x)$ 是奇函数，当 $0<x<2$ 时，$f(x)=x$，'
                                    r'当 $-2<x<0$ 时，$f(x)=x$，则 $f(-1)=$____．')
    return value_candidate('a03', goal=pair_goal('f(x)+g(x)=sqrt(x^2+1)', 'g(1)'),
                           text=r'已知 $f(x)$ 是奇函数，$g(x)$ 是偶函数，且 $f(x)+g(x)=sqrt(x^2+1)$，则 $g(1)=$____．')


@pytest.mark.parametrize('name', ['multiple_rules', 'absolute', 'both', 'rational', 'irrational_input',
                                  'irrational_endpoint', 'local_value', 'radical_identity'])
def test_generalized_route_exports_and_resumes(name, tmp_path):
    value = generalized_candidate(name)
    recognize(value, tmp_path)
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    goal, = result['goals']
    assert goal['status'] == 'solved', goal
    assert goal['answer'] is not None
    evidence = export_course(output, 'function-parity-generalization-' + name)
    assert evidence['stream']['handoffs'][0]['answer'] == goal['answer']
    assert runner.resume_sample(output)['goals'][0]['answer'] == goal['answer']
