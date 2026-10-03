"""Chapter 2: each shared route follows one step catalog across problems."""
import json
import re

from .test_local_practice import ROOT
from .test_q11 import template

BOUNDARY_QUESTION = r'上一步的范围以 \$.+\$ 为边界。(逐个代回原不等式，它们|代回原不等式，它)要保留吗？'
RANGE_QUESTION = r'把 \$.+\$ 看成关于 \$\w\$ 的一元二次不等式(，并结合 \$.+\$)?，\$\w\$ 在什么范围内？'
CATALOG = ['d_basis', 'd_rewrite', 'd_degenerate', 'd_position', 'd_delta', 'd_range', 'd_merge', 'd_boundary']
REQUIRED = {'d_basis', 'd_position', 'd_delta', 'd_range', 'd_boundary'}
QUESTIONS = {
    'd_basis': r'判别式法需要两个前提。逐项看看，本题是否满足？',
    'd_rewrite': r'哪一个式子与原不等式等价？',
    'd_degenerate': r'当 \$.+\$ 时，原不等式变成什么？它对所有实数 \$x\$ 成立吗？',
    'd_position': r'.+。要使 \$[fg]\(x\).+0\$ 对所有实数 \$x\$ 成立，图像应满足什么？',
    'd_delta': r'上一步：.+。这对应哪个判别式条件？',
    'd_range': RANGE_QUESTION,
    'd_merge': r'情况①得到 \$.+\$，情况②得到 \$.+\$。把两种情况的结果合并，\$\w\$ 的取值范围是什么？',
    'd_boundary': BOUNDARY_QUESTION,
}
SEPARATION = ['e_basis', 'e_separate', 'e_condition', 'e_graph', 'e_extremum', 'e_range', 'e_boundary']
SEPARATION_REQUIRED = {'e_basis', 'e_condition', 'e_extremum', 'e_boundary'}
SEPARATION_QUESTIONS = {
    'e_basis': r'分离参数法需要两个前提。逐项看看，本题是否满足？',
    'e_separate': r'.+，得到哪个不等式？',
    'e_condition': r'要使( \$.+\$ 对所有.+成立|存在 \$.+\$，使 \$.+\$)，\$\w\$ 应满足哪个条件？',
    'e_graph': r'\$.+\$.+。逐项确定它的图像特征。',
    'e_extremum': r'.+',
    'e_range': RANGE_QUESTION,
    'e_boundary': BOUNDARY_QUESTION,
}

INTERVAL = ['i_basis', 'i_condition', 'i_extremum', 'i_range', 'i_boundary']
INTERVAL_QUESTIONS = {
    'i_basis': r'区间最值法需要一个前提。看看本题是否满足？',
    'i_condition': r'要使( \$.+\$ 对所有.+成立|存在 \$.+\$，使 \$.+\$)，\$.+\$ 应满足哪个条件？',
    'i_extremum': r'.+逐项确定 \$.+\$ 在 \$.+\$ 上(的最[大小]值|取值范围的[上下]端)。',
    'i_range': r'.+\$\w\$ 的取值范围是什么？',
    'i_boundary': BOUNDARY_QUESTION,
}
# On an open interval the extremum may not be attained, so existence problems speak of the range's upper end.
TITLE_VARIANTS = {
    'i_condition': {'转化为最值条件', '转化为范围条件'},
    'e_condition': {'转化为最值条件', '转化为范围条件'},
    'i_extremum': {'分类讨论最值', '分类讨论取值范围'},
    'e_extremum': {'求最值', '求取值范围'},
}
VARIABLE = ['v_basis', 'v_rewrite', 'v_condition', 'v_extremum', 'v_range', 'v_boundary']
VARIABLE_QUESTIONS = {
    'v_basis': r'更换主元法需要两个前提。逐项看看，本题是否满足？',
    'v_rewrite': r'把 \$\w\$ 当作常数、\$\w\$ 当作自变量，\$y\$ 可以整理成哪个函数？',
    'v_condition': r'要使 \$.+\$ 对所有.+成立，\$.+\$ 应满足哪个条件？',
    'v_extremum': r'.+',
    'v_range': r'.+\$\w\$ 在什么范围内？',
    'v_boundary': BOUNDARY_QUESTION,
}
# Labels name the quantified variable, which is config['variables'][0].
BOUNDARY_LABELS = {
    'forall': lambda v: [('holds', f'对所有 ${v}$ 成立，保留'), ('fails', f'有 ${v}$ 不成立，排除')],
    'exists': lambda v: [('holds', f'存在 ${v}$ 成立，保留'), ('fails', f'没有 ${v}$ 成立，排除')],
}

BASIS_BOARDS = {
    'discriminant': ('d_basis', 'discriminant-board'),
    'extremum': ('e_basis', 'separation-board'),
    'interval': ('i_basis', 'interval-board'),
    'variable': ('v_basis', 'variable-board'),
}
BASIS_VERDICT = (r'两个前提都满足，(可以直接用判别式法|可以用分离参数法|把 \$\w\$ 作为主元)'
                 r'|前提满足，可以用区间最值法|先讨论 \$.+=0\$，再讨论 \$.+\\ne0\$')
BASIS_OPENING = r'由题意，(对任意 \$.+\$，\$.+\$ 恒成立|存在 \$.+\$，使 \$.+\$)。'
# The three labels of a condition step: what is required, which point decides it, and why that point suffices.
CONDITION_LABELS = (
    r'对所有(实数)? \$.+\$ 都成立|存在 \$.+\$ 使之成立',
    r'只需比 .+的最[高低]点|只需看 .+的最[高低]处',
    r'(最大值|最小值)(.+)，其余的值都\2'
    r'|([上下]端)(.+)，(每个值都|靠近\3的值也)\4；\3取不到也可以'
    r'|(小于|大于|不小于|不大于)(最[大小]的|[上下]端)，就\6(每一个|靠近\7的值)(；.+)?',
)
GRAPH = r'data-(?:quadratic|linear|reciprocal-sum)-graph='

def pages(route):
    for path in sorted(ROOT.glob('site/2/q*/index.html')):
        text = path.read_text()
        config = json.loads(re.search(r'id="practice-config">\s*(.*?)</script>', text, re.S)[1])
        if route in config['routes']:
            yield path.parent.name, text, config

def test_discriminant_steps_follow_the_catalog():
    seen = {}
    for name, text, config in pages('discriminant'):
        nodes = config['routes']['discriminant']
        ids = [node['id'] for node in nodes]
        assert ids == [i for i in CATALOG if i in ids], name
        assert REQUIRED <= set(ids) and ('d_degenerate' in ids) == ('d_merge' in ids), name
        parameter = config['variables'][1]
        for node in nodes:
            assert re.fullmatch(QUESTIONS[node['id']], node['question']), (name, node['id'])
            interaction = node['interaction']
            shape = {
                'title': node['title'] if node['id'] != 'd_degenerate' else node['title'][:2],
                'type': interaction['type'],
                'submit_label': node['submit_label'],
            }
            if node['id'] == 'd_basis':
                slots = json.loads(json.dumps(interaction['slots']))
                assert slots[1].pop('hint') == f'只看 $x$，把 ${parameter}$ 当作常数', name
                shape['slots'] = slots
            if node['id'] == 'd_delta':
                shape['options'] = interaction['options']
            assert seen.setdefault(node['id'], (name, shape))[1] == shape, (name, node['id'], seen[node['id']][0])

def test_discriminant_step_visuals_and_function_definition():
    for name, text, config in pages('discriminant'):
        nodes = {node['id']: node for node in config['routes']['discriminant']}
        assert 'class="graph-cases"' in template(text, nodes['d_position']['display'])
        assert 'class="case-merge"' in template(text, nodes['d_delta']['display'])
        assert nodes['d_range']['board'] == 'range-board'
        function = re.search(r'\$([fg])\(x\)', nodes['d_position']['question'])[1]
        earlier = list(nodes)[:list(nodes).index('d_position')]
        assert any(re.search(rf'[记令] \${function}\(x\)=', template(text, nodes[i]['display'])) for i in earlier), name

def test_separation_steps_follow_the_catalog():
    seen = {}
    for name, text, config in pages('extremum'):
        nodes = config['routes']['extremum']
        ids = [node['id'] for node in nodes]
        assert ids == [i for i in SEPARATION if i in ids], name
        assert SEPARATION_REQUIRED <= set(ids), name
        for node in nodes:
            assert re.fullmatch(SEPARATION_QUESTIONS[node['id']], node['question']), (name, node['id'])
            shape = {'title': node['title']}
            if node['id'] != 'e_extremum':
                shape |= {'type': node['interaction']['type'], 'submit_label': node['submit_label']}
            if node['id'] == 'e_basis':
                shape['interaction'] = node['interaction']
                assert node['board'] == 'separation-board', name
            if node['id'] == 'e_condition':
                shape['values'] = sorted(option['value'] for option in node['interaction']['options'])
                assert 'class="function-conversion"' in template(text, node['display']), name
            if node['id'] == 'e_graph':
                assert re.search(r'data-(quadratic|reciprocal-sum)-graph=', template(text, node['display'])), name
            assert node['title'] in TITLE_VARIANTS.get(node['id'], {node['title']}), (name, node['id'])
            key = (node['id'], node['title'])
            assert seen.setdefault(key, (name, shape))[1] == shape, (name, node['id'], seen[key][0])
        by_id = {node['id']: node for node in nodes}
        function = re.search(r'([fgh])\(x\)', by_id['e_condition']['question'])[1]
        earlier = ids[:ids.index('e_condition')]
        assert any(re.search(rf'[记令] \${function}\(x\)=', template(text, by_id[i]['display'])) for i in earlier), name

def test_interval_steps_follow_the_catalog():
    seen = {}
    for name, text, config in pages('interval'):
        nodes = config['routes']['interval']
        assert [node['id'] for node in nodes] == INTERVAL, name
        for node in nodes:
            assert re.fullmatch(INTERVAL_QUESTIONS[node['id']], node['question']), (name, node['id'])
            shape = {'title': node['title'], 'type': node['interaction']['type'], 'submit_label': node['submit_label']}
            if node['id'] == 'i_basis':
                shape['interaction'] = node['interaction']
            if node['id'] == 'i_condition':
                shape['values'] = sorted(option['value'] for option in node['interaction']['options'])
                assert 'class="function-conversion"' in template(text, node['display']), name
            if node['id'] == 'i_range':
                assert '取并集' in template(text, node['display']), name
            assert node['title'] in TITLE_VARIANTS.get(node['id'], {node['title']}), (name, node['id'])
            key = (node['id'], node['title'])
            assert seen.setdefault(key, (name, shape))[1] == shape, (name, node['id'], seen[key][0])

def test_variable_steps_follow_the_catalog():
    seen = {}
    for name, text, config in pages('variable'):
        nodes = config['routes']['variable']
        assert [node['id'] for node in nodes] == VARIABLE, name
        for node in nodes:
            assert re.fullmatch(VARIABLE_QUESTIONS[node['id']], node['question']), (name, node['id'])
            shape = {'title': node['title'], 'type': node['interaction']['type'], 'submit_label': node['submit_label']}
            if node['id'] == 'v_basis':
                interaction = node['interaction']
                shape['interaction'] = (interaction['title'], [(s['label'], s['hint'], [o['value'] for o in s['options']]) for s in interaction['slots']])
                assert node['board'] == 'variable-board', name
            if node['id'] == 'v_condition':
                assert 'class="function-conversion"' in template(text, node['display']), name
            if node['id'] == 'v_extremum':
                assert 'data-linear-graph=' in template(text, node['display']), name
            assert seen.setdefault(node['id'], (name, shape))[1] == shape, (name, node['id'], seen[node['id']][0])
        rewrite = {node['id']: node for node in nodes}['v_rewrite']
        assert re.search(r'[记令] \$f\(\w\)=', template(text, rewrite['display'])), name

def test_both_condition_steps_share_option_values():
    values = {
        (name, route): sorted(option['value'] for option in node['interaction']['options'])
        for route, step in (('interval', 'i_condition'), ('extremum', 'e_condition'), ('variable', 'v_condition'))
        for name, _, config in pages(route)
        for node in config['routes'][route] if node['id'] == step
    }
    assert values and all(v == ['max', 'min', 'one_point'] for v in values.values()), values

def test_choices_have_no_option_previews():
    for path in sorted(ROOT.glob('site/2/q*/index.html')):
        text = path.read_text()
        config = json.loads(re.search(r'id="practice-config">\s*(.*?)</script>', text, re.S)[1])
        assert all('preview' not in node for nodes in config['routes'].values() for node in nodes), path.parent.name
        assert '-preview-' not in text, path.parent.name

def test_boundary_step_is_shared_by_every_route():
    seen = None
    for path in sorted(ROOT.glob('site/2/q*/index.html')):
        text = path.read_text()
        config = json.loads(re.search(r'id="practice-config">\s*(.*?)</script>', text, re.S)[1])
        for route, nodes in config['routes'].items():
            node = nodes[-1]
            where = (path.parent.name, route)
            assert node['id'].endswith('_boundary') and node['title'] == '检查边界', where
            assert re.fullmatch(BOUNDARY_QUESTION, node['question']), where
            interaction = node['interaction']
            assert all(slot['hint'].startswith('此时') and '原不等式变为' in slot['hint'] for slot in interaction['slots']), where
            assert node['board'] == 'boundary-board', where
            assert '<div class="board-caption">上一步得到的范围</div>' in template(text, 'boundary-board'), where
            quantifier = 'exists' if '\\exists' in text else 'forall'
            for slot in interaction['slots']:
                assert [(o['value'], o['label']) for o in slot['options']] == BOUNDARY_LABELS[quantifier](config['variables'][0]), where
            shape = (interaction['type'], interaction['title'], node['submit_label'])
            seen = seen or (where, shape)
            assert shape == seen[1], (where, seen[0])

def all_pages():
    for path in sorted(ROOT.glob('site/2/q*/index.html')):
        text = path.read_text()
        yield path.parent.name, text, json.loads(re.search(r'id="practice-config">\s*(.*?)</script>', text, re.S)[1])

def test_basis_step_shows_the_original_inequality_and_one_verdict_style():
    focus = {}
    for name, text, config in all_pages():
        labels = {method['id']: method['label'] for method in config['methods']}
        for route, nodes in config['routes'].items():
            step, board = BASIS_BOARDS[route]
            node = nodes[0]
            assert (node['id'], node['board']) == (step, board), (name, route)
            card = template(text, board)
            assert re.search(r'<div class="board-caption">(.*?)</div>', card)[1] == labels[route], (name, route)
            assert '<div class="formula" data-math-text>' in card, (name, route)
            sentence = re.search(r'class="board-focus"[^>]*>(.*?)</p>', card)[1].replace(f'${config["variables"][1]}$', '$P$')
            assert focus.setdefault(route, (name, sentence))[1] == sentence, (name, route, focus[route][0])
            done = template(text, node['display'])
            assert re.fullmatch(BASIS_VERDICT, re.search(r'class="checklist-verdict"[^>]*>(.*?)</p>', done)[1]), (name, route)
            opening = re.search(r'<summary>完整推导</summary><p[^>]*>(.*?)</p>', done)[1]
            assert re.fullmatch(BASIS_OPENING, opening), (name, route, opening)

def test_condition_step_uses_three_fixed_label_roles():
    for name, text, config in all_pages():
        for route, nodes in config['routes'].items():
            for node in nodes:
                if not node['id'].endswith('_condition'):
                    continue
                assert not any('：' in option['label'] for option in node['interaction']['options']), (name, node['id'])
                conversion = template(text, node['display'])
                labels = re.findall(r'class="conversion-label"[^>]*>(.*?)</span>', conversion)
                assert len(labels) == 3, (name, node['id'])
                for pattern, label in zip(CONDITION_LABELS, labels):
                    assert re.fullmatch(pattern, label), (name, node['id'], label)

def test_extremum_choices_share_one_option_set():
    seen = {}
    for name, text, config in all_pages():
        for nodes in config['routes'].values():
            for node in nodes:
                interaction = node['interaction']
                key = (node['id'], interaction.get('title'))
                if node['id'] == 'v_extremum' or key == ('e_extremum', '区间与最低点的位置'):
                    shape = [[option['value'] for option in slot['options']] for slot in interaction['slots']]
                    if node['id'] == 'e_extremum':
                        assert shape[0] == ['left', 'right', 'around'], name
                        shape = shape[:1]
                    else:
                        assert shape[1] == ['left', 'right', 'ends'], name
                    assert seen.setdefault(key, (name, shape))[1] == shape, (name, key, seen[key][0])
    assert ('v_extremum', '看斜率判断最值') in seen and ('e_extremum', '区间与最低点的位置') in seen, seen

def test_delta_merge_names_the_opening_it_keeps():
    for name, text, config in pages('discriminant'):
        node = {node['id']: node for node in config['routes']['discriminant']}['d_delta']
        caption = re.search(r'class="case-merge-caption"[^>]*>(.*?)</p>', template(text, node['display']))
        assert caption and re.fullmatch(r'(\$[fg]\(x\)\$ )?开口向[上下](（\$.+\$）时)?', caption[1]), name

def test_every_distinct_boundary_case_gets_its_own_graph():
    for name, text, config in all_pages():
        for route, nodes in config['routes'].items():
            node = nodes[-1]
            done = template(text, node['display'])
            cases = {slot['hint'] for slot in node['interaction']['slots']}
            assert len(re.findall(GRAPH, done)) == len(cases), (name, route)
            assert ('class="graph-comparison"' in done) == (len(cases) > 1), (name, route)
