"""Bind the given expression and graph request to the transcribed source."""
import re

from .evaluation_surface import _formula_parts


def translation_matches(text, operations):
    """Conservatively bind both direction and distance; never discard an extra move."""
    from ...problem_understanding.notation_parser import NotationError
    from ..function_graph import rational
    clean = re.sub(r'[\s$]', '', text)
    number = r'(\d+(?:/\d+|\.\d+)?)'
    paired = re.compile(r'向([左右上下])[、，,]向([左右上下])分别平移'+number+r'个?[、，,]'+number+r'个?单位(?:长度)?')
    single = re.compile(r'向([左右上下])平移'+number+r'个?单位(?:长度)?')
    directions = {'左': 'left', '右': 'right', '上': 'up', '下': 'down'}
    found = []
    for match in paired.finditer(clean):
        d1, d2, n1, n2 = match.groups()
        found.extend([(match.start(), directions[d1], n1), (match.start()+1, directions[d2], n2)])
    remainder = paired.sub('', clean)
    found.extend((m.start(), directions[m[1]], m[2]) for m in single.finditer(clean))
    # A reflection, stretch, or unparsed translation cannot disappear from the target.
    if re.search(r'平移|移动|[左右上下]移|翻折|对称|伸缩|拉伸|压缩|旋转', single.sub('', remainder)):
        return False
    try:
        return [(d, rational(n)) for _, d, n in sorted(found)] == [(o['direction'], rational(o['distance'])) for o in operations]
    except (ValueError, NotationError, KeyError):
        return False


def graph_source_spans(candidate, target_ref, ranges, description, matches):
    text, goal = candidate['original_text'], description['source']
    formulas = [part for begin, end in ranges for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
                for part in _formula_parts(m[1], begin+m.start(1))]
    if 'source_graph' in goal:
        name = goal['source_graph']['function']
        original = [r for r in formulas if matches(r[2], f'{name}({goal["variable"]})', call=True)]
        target = [r for r in formulas if matches(r[2], goal['expression'], call=True)]
        if len(original) != 1 or len(target) != 1 or original[0][1] >= target[0][0]:
            return None
        if (not re.search(r'图[像象]如[^。\n]{0,12}所示', text[original[0][1]:target[0][0]])
                or not re.match(r'\s*\$?\s*的?图[像象](?:大致)?为', text[target[0][1]:])
                or re.search(r'定义域|取值范围|且|平移|翻折|对称|伸缩|旋转', text)):
            return None
        return [(original[0][0], target[0][1], 'goal',
                 [target_ref, target_ref+'/source_graph', target_ref+'/expression', target_ref+'/variable'])]
    given = [row for row in formulas if matches(row[2], goal['expression'], call=True,
                                                alias_variables=(goal['variable'],))]
    if len(given) != 1:
        return None
    if goal['kind'] in ('draw_function_graph', 'solve_graph_inequality'):
        refs = [target_ref, target_ref+'/expression', target_ref+'/variable']
        rows = [(*given[0][:2], 'goal', refs)]
        if goal['kind'] == 'draw_function_graph':
            requests = [(begin+m.start(), begin+m.end()) for begin, end in ranges
                        for m in re.finditer(r'(?:画|作)出?(?:它|函数)?的?图[像象]', text[begin:end])]
            if len(requests) != 1:
                return None
            rows.append((*requests[0], 'goal', [target_ref]))
        else:
            relation = f'f({goal["variable"]}){goal["operator"]}{goal["level"]}'
            requests = [r for r in formulas if matches(r[2], relation, alias_variables=(goal['variable'],))]
            if len(requests) != 1:
                return None
            rows.append((*requests[0][:2], 'goal', [target_ref, target_ref+'/operator', target_ref+'/level']))
        if 'input_domain' in goal:
            domains = [r for r in formulas if matches(r[2], goal['variable']+'∈'+goal['input_domain'])]
            if len(domains) != 1:
                return None
            rows.append((*domains[0][:2], 'given_domain', [target_ref+'/input_domain']))
        return rows
    requests = [(begin+m.start(), begin+m.end()) for begin, end in ranges
                for m in re.finditer(r'(?:部分)?图[像象](?:大致|大概)?(?:是|为)|(?:选择|选出)[^。\n]{0,12}图[像象]', text[begin:end])]
    if len(requests) != 1 or requests[0][0] < given[0][1]:
        return None
    movement_text = text[given[0][1]:requests[0][0]]
    if not translation_matches(movement_text, goal.get('transformations', [])):
        return None
    refs = [target_ref, target_ref+'/expression', target_ref+'/variable']
    if 'transformations' in goal:
        refs.append(target_ref+'/transformations')
    rows = [(given[0][0], requests[0][1], 'goal', refs)]
    if 'input_domain' in goal:
        domains = [r for r in formulas if matches(r[2], goal['variable']+'∈'+goal['input_domain'])]
        if len(domains) != 1:
            return None
        rows.append((*domains[0][:2], 'given_domain', [target_ref+'/input_domain']))
    elif re.search('定义域|取值范围|且', text):
        return None
    return rows
