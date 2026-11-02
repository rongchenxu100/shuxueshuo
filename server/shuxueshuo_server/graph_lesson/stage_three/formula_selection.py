"""Select from source structure; comparison choices are not executable routes."""

import sympy as sp

from ..function_formula import source_values
from ..function_matching import available, matching_source
from .math_values import latex


def select_formula(context, contract, primary):
    # Assess each route from the original conditions, without solving the goal.
    # Several methods may fit the same source;
    # neither conclusion reads the recovered answer or a problem identifier.
    desc = context['formula_goal']
    from .coefficients_runtime import admitted as coefficients_admitted
    from .system_runtime import admitted as system_admitted
    from ..function_system import system_source
    from .assignment_runtime import admitted as assignment_admitted
    assignment = assignment_admitted(context)
    system = system_admitted(context)
    paired = system_source(desc) if system else None
    coefficients = coefficients_admitted(context)
    matching = available(desc)
    from .formula_runtime import admitted
    substitution = admitted(context)
    source = None if coefficients or system or assignment else source_values(desc) if substitution else matching_source(desc)
    x = sp.Symbol(desc['variable'], real=True)
    t = 't' if desc['variable'] != 't' else 'z'
    g, h = source.expressions(x) if source else (x, x)
    g, h = latex(g), latex(sp.expand(h) if matching else h)
    branch_id = 'substitution'
    verdicts = {
        'coefficients': {'value': 'not_triggered', 'message': '题目没有给出一次、二次等函数类型，不能直接设一般式。'},
        branch_id: {'value': 'fit', 'message': (rf'先令 ${t}={g}$，再把右边改写成 ${t}$ 的式子。' if substitution
                                               else '换元后反解会出现两个分支。这类换元步骤暂未开放，直接配凑更方便。')},
        'matching': {'value': 'fit', 'message': ('先展开函数括号里式子的平方，再把右边配成同一个式子的组合。' if matching
                                                else '可以尝试配凑。这类分式的配凑步骤暂未开放，可选换元法继续。')},
        'system': {'value': 'not_triggered', 'message': '这里没有两个相互关联的函数值，暂不需要构造方程组。'},
        'assignment': {'value': 'not_triggered', 'message': '这里不是含两个变量的恒等式；只代入几个数不能确定整个解析式。'},
    }
    if coefficients:
        verdicts.update({
            'coefficients': {'value': 'fit', 'message': '题目给了函数类型。先设含未知系数的一般式，再代入已知关系比较系数。'},
            'substitution': {'value': 'unknown', 'message': '这类题的换元路线尚未核验。可以利用题给函数类型选择待定系数法。'},
            'matching': {'value': 'unknown', 'message': '这类题的配凑路线尚未核验。可以利用题给函数类型选择待定系数法。'},
            'system': {'value': 'unknown', 'message': '本批尚未核验这类关系的联立路线，可先用题给函数类型选择待定系数法。'},
        })
    if system:
        verdicts.update({
            'system': {'value': 'fit', 'message': rf'把 ${desc["variable"]}$ 换成 ${latex(paired.transform)}$，两个函数值互换，再将两个方程联立。'},
            'substitution': {'value': 'not_triggered', 'message': '这里有两个关联函数值，需要用替换后的第二个方程与原式联立。'},
            'matching': {'value': 'unknown', 'message': '这类关系的配凑路线尚未核验；可以用关联函数值构造方程组。'},
        })
    if assignment:
        verdicts.update({
            'assignment': {'value': 'fit', 'message': '条件对两个变量恒成立。选取零或令两变量相等，消去变量，再检查完整原关系。'},
            'substitution': {'value': 'unknown', 'message': '这类二元关系的换元路线尚未核验，可以先给其中一个变量赋值。'},
            'matching': {'value': 'unknown', 'message': '这类二元关系的配凑路线尚未核验，可以选择赋值法。'},
            'system': {'value': 'unknown', 'message': '这里先用二元恒等条件作特殊代入；单变量互换的方程组路线不直接适用。'},
        })
    choices = [{'value': key, 'label': label} for key, label in (
        ('coefficients', '待定系数法'), ('substitution', '换元法'), ('matching', '配凑法'),
        ('system', '构造方程组法'), ('assignment', '赋值法'))]
    check = {
        'id': 'source_structure', 'question': '题目给了哪类条件？',
        'options': [
            {'value': 'function_type', 'label': '已知函数类型', 'note': ('题给一次函数' if desc.get('function_type') == 'linear' else '题给二次函数') if coefficients else '如一次函数、二次函数'},
            {'value': 'composite_input', 'label': '已知复合函数的解析式', 'note': r'如 $f(x-1)=x^2-2x$' if coefficients or system or assignment else rf'如 ${desc["function_name"]}\left({g}\right)={h}$'},
            {'value': 'paired_values', 'label': '出现关联函数值', 'note': (rf'${desc["function_name"]}({desc["variable"]})$ 与 ${desc["function_name"]}\left({latex(paired.transform)}\right)$' if system else r'如 $f(x)$ 与 $f(-x)$')},
            {'value': 'two_variables', 'label': '含两个变量的恒等式', 'note': r'对任意 $x,y$ 成立'},
        ],
        'resolved': '同一个等式中给出了两个相互关联的函数值。' if system else '题目明确给出了函数类型。' if coefficients else rf'函数括号里是 ${g}$。',
        'feedback': '找一个替换，让两个函数值交换位置。' if system else '注意题目给出的一次或二次函数类型。' if coefficients else '这道题的线索在函数括号里：可以换元，也可以尝试配凑。',
    }
    d3 = {
        'id': 'D3', 'title': '选择解题方法',
        'question': '根据题目条件，沿连线选择一种方法。',
        'query': {'op': 'methods', 'from': primary},
        'interaction': {'type': 'method_cards', 'layout': 'connections', 'facts': [],
                        'checks': [check], 'method_notes': {}, 'method_choices': choices,
                        'connections': [
                            {'cue': 'function_type', 'method': 'coefficients'},
                            {'cue': 'composite_input', 'method': 'substitution'},
                            {'cue': 'composite_input', 'method': 'matching'},
                            {'cue': 'paired_values', 'method': 'system'},
                            {'cue': 'two_variables', 'method': 'assignment'},
                        ],
                        'source_refs': desc['source_refs']},
        'expected_answer': {'checks': {'source_structure': 'two_variables' if assignment else 'paired_values' if system else 'function_type' if coefficients else 'composite_input'}},
        'verdicts': verdicts, 'submit_label': '确认选法',
    }
    preferred = ('assignment' if assignment else 'system' if system else 'coefficients' if coefficients else
                 'substitution' if (substitution and source.root_input) or not matching else 'matching')
    branches, options = [], []
    for row in contract['routes']:
        branch = {'function_formula': 'substitution', 'function_matching': 'matching', 'function_coefficients': 'coefficients', 'function_system': 'system', 'function_assignment': 'assignment'}[row['admission']]
        if not {'substitution': substitution, 'matching': matching, 'coefficients': coefficients, 'system': system, 'assignment': assignment}[branch]:
            continue
        recommendation = 'preferred' if branch == preferred else 'optional'
        branches.append({'branch': branch, 'target': row['method'], 'route_id': row['route_id'],
                         'trigger': 'triggered', 'applicability': 'applicable', 'recommendation': recommendation,
                         'route_plan': 'capability_gap', 'missing_capabilities': [f'execution:{row["method"]}'],
                         'checks': [{'check_id': 'supported_whole_input', 'status': 'holds', 'source_refs': desc['source_refs']}]})
        options.append({'branch': branch, 'method': row['method'], 'route_id': row['route_id'],
                        'recommendation': recommendation, 'route_plan': 'capability_gap', 'message': verdicts[branch]['message']})
    return {'status': 'no_verified_route',
            'selection': {'kind': 'method_cards', 'rule': contract['rule'], 'branches': branches,
                          'recommendation_rule': 'whole_input_structure', 'recommendation_checks': []},
            'd3': d3,
            'd4': {'id': 'D4', 'title': '按所选方法解题',
                   'options': options},
            'diagnostics': []}
