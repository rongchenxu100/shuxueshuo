"""Locate the actual unknown-function relation and original question in text."""

import re

import sympy as sp

from ...problem_understanding.review_contract import pointer
from .evaluation_surface import _formula_parts
from ..range_syntax import range_domain
from .surface_math import normalize_surface


def _call_brackets(body, function):
    """Normalize only square brackets used by the declared function call.

    Interval/set brackets and other names are left intact. This is a display
    spelling adapter, never an algebraic rewrite; source offsets stay raw.
    """
    body = re.sub(r'\\(?:left|right)\b\s*', '', body)
    chars = list(body)
    for match in re.finditer(r'(?<![\w])'+re.escape(function)+r'\s*\[', body):
        start, depth = match.end()-1, 1
        for stop in range(start+1, len(body)):
            depth += (body[stop] == '[') - (body[stop] == ']')
            if depth == 0:
                chars[start], chars[stop] = '(', ')'
                break
    return ''.join(chars)


def _real_spelling(body):
    """Textbooks also print the real set as a bold R (only in set roles)."""
    return re.sub(r'\\mathbf(?:\{R\}|\s+R)(?![A-Za-z])', 'ℝ', body)


def _formula_parts_with_domain(body, start, goal, desc, matches):
    parts = _formula_parts(body, start)
    if ('relation_domain' not in goal
            or range_domain(desc['relation_domain_ast']) != sp.S.Reals-sp.FiniteSet(0)):
        return parts
    result = []
    for begin, end, expression in parts:
        suffix = re.search(r'(?:\\left\s*)?[（(]\s*([^()]*)\s*(?:\\right\s*)?[）)]\s*$', expression)
        # An explicit nonzero annotation may follow a relation without a
        # comma. Never strip an arbitrary product, inequality or extra given.
        if suffix and matches(suffix[1], goal['variable']+'!=0'):
            result.extend([(begin, begin+suffix.start(), expression[:suffix.start()]),
                           (begin+suffix.start(1), begin+suffix.end(1), suffix[1])])
        else:
            result.append((begin, end, expression))
    return result


def _universal_pair(text, ranges, variables):
    """Bind both quantified variables and their common real domain to text."""
    found = []
    names = {','.join(variables), ','.join(reversed(variables))}
    for begin, end in ranges:
        for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end]):
            body = re.sub(r'\s+', '', normalize_surface(_real_spelling(m[1])).text).replace('，', ',')
            start, stop = begin+m.start(), begin+m.end()
            prefix = text[max(begin, start-16):start]
            symbolic = body.startswith('∀')
            body = body.removeprefix('∀')
            if ((body in {n+'∈ℝ' for n in names} and (symbolic or re.search(r'任意\s*$', prefix)))
                    or (body in names and re.search(r'任意实数\s*$', prefix))):
                word = re.search(r'(?:对)?任意(?:实数)?\s*$', prefix)
                start = start-len(word[0]) if word else start
                found.append((start, stop, text[start:stop]))
    return found


def formula_source_spans(candidate, target_ref, ranges, desc, matches):
    text, goal = candidate['original_text'], pointer(candidate, target_ref)
    source_matches = matches

    def matches(body, expected):
        return source_matches(_call_brackets(body, goal['function']), expected)

    pair = []
    if 'relation_variables' in goal:
        pair = _universal_pair(text, ranges, goal['relation_variables'])
        if len(pair) != 1 or goal.get('relation_domain') != 'ℝ':
            return None
    formulas = [part for begin, end in ranges for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
                for part in _formula_parts_with_domain(m[1], begin+m.start(1), goal, desc, matches)]
    relations = []
    for index, expression in enumerate([goal['relation'], *goal.get('additional_relations', [])]):
        found = [part for part in formulas if matches(part[2], expression)]
        if len(found) != 1:
            return None
        relations.append((found[0], [target_ref+('/relation' if index == 0 else f'/additional_relations/{index-1}')]))
    relation = relations[0][0]
    call = goal.get('expression') or goal['function']+'('+goal['variable']+')'
    targets = [part for part in formulas if part[0] > relation[1]
               and matches(re.sub(r'=\s*[_＿…\.\s]*$', '', part[2]), call)]
    if len(targets) != 1:
        return None
    target = targets[0]
    tail = text[target[1]:ranges[-1][1]]
    if goal['kind'] == 'find_function_formula' and not re.search(r'解析式|表达式|[_＿]', tail+target[2]):
        return None
    # Explicit extra givens cannot disappear just because the natural-domain
    # family was recognized. More complex layouts remain unavailable to D1.
    for pattern, field in ((r'一次函数|二次函数', 'function_type'),
                           (r'任意', 'relation_domain'),
                           (r'定义在|定义域', 'declared_domain')):
        if re.search(pattern, text) and field not in goal:
            return None
    # A0 has only one relation, with no further givens joined by 且. Do not
    # use a supplied domain as permission to discard an additional condition.
    if '且' in text and not goal.get('additional_relations') and not goal.get('function_type'):
        return None
    rows = [*relations, (target, [target_ref, target_ref+'/function', target_ref+'/variable',
                                                        *([target_ref+'/expression'] if 'expression' in goal else [])])]
    if pair:
        rows.append((pair[0], [target_ref+'/relation_domain',
                              *[f'{target_ref}/relation_variables/{i}' for i in range(2)]]))
    if goal.get('function_type'):
        expected_type = {'linear': '一次函数', 'quadratic': '二次函数'}[goal['function_type']]
        found = list(re.finditer(r'一次函数|二次函数', text))
        if len(found) != 1 or found[0][0] != expected_type:
            return None
        m = found[0]
        rows.append(((m.start(), m.end(), m[0]), [target_ref+'/function_type']))
        for part in formulas:
            if part[1] < relation[0] and matches(part[2], goal['function']+'('+goal['variable']+')'):
                rows.append((part, [target_ref+'/function']))
    for field in ('relation_domain', 'declared_domain', 'requested_domain'):
        if field not in goal:
            continue
        if pair and field == 'relation_domain':
            continue
        found = [part for part in formulas if matches(_real_spelling(part[2]), goal[field])]
        if not found and goal[field] == 'ℝ':
            # Plain R is a set only when the nearby words explicitly identify
            # the function's domain, not when R is an arbitrary parameter.
            found = [part for part in formulas if part[2].strip() == 'R'
                     and re.search(r'(?:定义在|定义域(?:为|是)?)\s*\$?\s*$', text[:part[0]])]
        if not found and field == 'relation_domain' and range_domain(desc[field+'_ast']) == sp.S.Reals-sp.FiniteSet(0):
            found = [part for part in formulas if matches(part[2], goal['variable']+'!=0')]
            if not found:
                # Bind the user's nonzero-real wording itself, rather than
                # inventing an explicit domain from the reciprocal expression.
                pattern = r'非零实数\s*\$\s*'+re.escape(goal['variable'])+r'\s*\$'
                found = [(m.start(), m.end(), m[0]) for m in re.finditer(pattern, text)]
                for part in formulas:
                    if any(a <= part[0] and part[1] <= b for a,b,_ in found):
                        rows.append((part, [target_ref+'/'+field]))
        if len(found) != 1:
            return None
        rows.append((found[0], [target_ref+'/'+field]))
    covered = {(row[0][0], row[0][1]) for row in rows}
    siblings = pointer(candidate, target_ref.rsplit('/goals/', 1)[0]).get('goals', [])
    sibling_calls = [item.get('expression') or item['function']+'('+item['variable']+')'
                     for item in siblings if item.get('relation') == goal['relation'] and 'function' in item]
    if any((part[0], part[1]) not in covered
           and not any(a <= part[0] and part[1] <= b for a,b,_ in pair)
           and not any(matches(re.sub(r'=\s*[_＿…\.\s]*$', '', part[2]), other) for other in sibling_calls)
           for part in formulas):
        return None
    return [(a, b, 'goal' if part == target else 'expression', refs) for part, refs in rows for a, b, _ in [part]]
