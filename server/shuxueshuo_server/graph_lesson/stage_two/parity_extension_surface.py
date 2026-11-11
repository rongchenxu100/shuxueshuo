"""Bind parity, the one-sided rule and both input ranges to their source text."""
import re

import sympy as sp

from ...problem_understanding.notation_parser import NotationError, parse
from ...problem_understanding.review_contract import pointer
from ..function_cells import constant, input_set
from ..parity_extension_math import region, rule_rows
from .evaluation_surface import _formula_parts
from .formula_surface import _call_brackets, _real_spelling
from .fragments import _domain_formula_body_matches
from .surface_math import normalize_surface

PROPERTY = {'odd': '奇函数', 'even': '偶函数', 'both': '既是奇函数又是偶函数'}


def function_intro(prefix):
    return re.search(r'(?:^(?:\s*\d+\s*[.．、])?|函数|设|已知)\s*\$\s*$', prefix)


def parity_spans(text, ranges, intros, functions, desc):
    """Bind each property to its function; an unordered bag of parity words is insufficient."""
    words = [(begin + m.start(), begin + m.end(), m[0]) for begin, end in ranges
             for m in re.finditer(r'奇函数|偶函数', text[begin:end])]
    calls = []
    for part in intros:
        matches = [f for f in functions if _same(re.sub(r'^\s*y\s*=', '', part[2]),
                                                f"{f['name']}({desc['variable']})", desc)]
        if len(matches) != 1:
            return None
        calls.append((part, matches[0]))
    calls.sort(key=lambda row: row[0][0])
    if not words or len(calls) != len(functions):
        return None
    first = min([p[0] for p, _ in calls] + [w[0] for w in words])
    last = max([p[1] for p, _ in calls] + [w[1] for w in words])
    statement = text[first:last]
    if re.search(r'非|不是|不为|不一定|未必|可能', text[max(0, first-6):last]):
        return None
    assigned = {f['name']: [] for f in functions}
    if len(functions) == 1:
        assigned[functions[0]['name']] = words
    elif '分别' in statement:
        if len(words) != len(calls) or max(p[1] for p, _ in calls) > words[0][0]:
            return None
        for (_, f), word in zip(calls, words):
            assigned[f['name']].append(word)
    elif len(words) == 1 and re.search(r'均|都|皆|同为', statement):
        for f in functions:
            assigned[f['name']].append(words[0])
    else:
        # Each adjective can precede its function (“奇函数 f 与偶函数 g”)
        # or follow its subject (“f 是奇函数，g 是偶函数”). Punctuation is not ownership.
        for word in words:
            following = [f for p, f in calls if p[0] >= word[1]
                         and re.fullmatch(r'\s*\$\s*', text[word[1]:p[0]])]
            preceding = [f for p, f in calls if p[1] <= word[0]]
            owners = following or preceding[-1:]
            if len(owners) != 1:
                return None
            assigned[owners[0]['name']].append(word)
    rows = []
    for f in functions:
        actual = assigned[f['name']]
        expected = {'奇函数', '偶函数'} if f['property'] == 'both' else {PROPERTY[f['property']]}
        if {w[2] for w in actual} != expected or len(actual) != len(expected):
            return None
        rows.extend((word, 'condition', [f['parity_source_ref']]) for word in actual)
    merged = {}
    for word, _, refs in rows:
        merged.setdefault(word, []).extend(refs)
    return [(word, 'condition', refs) for word, refs in merged.items()]


def _product_spelling(ast, variable):
    """Printed x(1+x) is a product of the scalar variable, never a call of it."""
    if not isinstance(ast, list):
        return ast
    if len(ast) == 3 and ast[:2] == ['call', variable]:
        return ['*', ['name', variable], _product_spelling(ast[2], variable)]
    return [_product_spelling(item, variable) for item in ast]


def _same(body, expected, desc):
    body = _call_brackets(body, desc['function'])
    try:
        actual = parse(normalize_surface(_range_notation(body)).text)
        if _product_spelling(actual, desc['variable']) == parse(expected):
            return True
    except (NotationError, ValueError, RecursionError):
        pass
    # TeX \sqrt{}/\frac{}{} spellings are read as the same original tree.
    return _domain_formula_body_matches(body, expected)


_BOUNDS = {'<': lambda v: sp.Interval.open(-sp.oo, v), '<=': lambda v: sp.Interval(-sp.oo, v),
           '>': lambda v: sp.Interval.open(v, sp.oo), '>=': lambda v: sp.Interval(v, sp.oo)}
_FLIP = {'<': '>', '<=': '>=', '>': '<', '>=': '<='}


def _range_notation(body):
    """Bounded TeX adapter for exact endpoints and set operations; unknown commands still fail."""
    if len(body) > 4096:
        raise ValueError('parity_ext.display_budget')
    text = _real_spelling(body)
    for command, symbol in [('setminus', '∖'), ('cup', '∪'), ('cap', '∩')]:
        text = re.sub(r'\\' + command + r'(?![A-Za-z])', lambda _, symbol=symbol: symbol, text)
    for _ in range(24):
        before = text
        text = re.sub(r'\\sqrt\s*\{([^{}]*)\}', lambda m: ' sqrt(' + m[1] + ')', text)
        text = re.sub(r'\\(?:dfrac|tfrac|frac)\s*\{([^{}]*)\}\s*\{([^{}]*)\}',
                      lambda m: '((' + m[1] + ')/(' + m[2] + '))', text)
        if text == before:
            break
    return text


def _set_value(ast):
    """A printed set: (a,b) parses as a pair, so it is read as the open interval here."""
    if ast[0] == 'tuple' and len(ast) == 3:
        ast = ['interval', False, False, ast[1], ast[2]]
    if ast in (['name', 'R'], ['name', 'ℝ']):
        ast = ['real']
    if ast[0] in ('∪', '∩', 'set_difference'):
        a, b = (_set_value(child) for child in ast[1:])
        if a is None or b is None:
            return None
        return {'∪': lambda: a | b, '∩': lambda: a & b, 'set_difference': lambda: a - b}[ast[0]]()
    try:
        value = input_set(ast)
    except (NotationError, ValueError, TypeError, IndexError):
        return None
    return value if value != sp.S.EmptySet else None


def _range_value(ast, variable):
    x = ['name', variable]
    if ast[0] == 'and' and len(ast) == 3:
        parts = [_range_value(part, variable) for part in ast[1:]]
        return None if None in parts or parts[0] & parts[1] == sp.S.EmptySet else parts[0] & parts[1]
    if ast[0] == '∈' and len(ast) == 3 and ast[1] == x:
        return _set_value(ast[2])
    if len(ast) != 3 or ast[0] not in _BOUNDS or x not in ast[1:]:
        return None
    op, other = (ast[0], ast[2]) if ast[1] == x else (_FLIP[ast[0]], ast[1])
    try:
        return _BOUNDS[op](constant(other))
    except (NotationError, ValueError):
        return None


def _range(body, variable):
    try:
        return _range_value(parse(normalize_surface(_range_notation(body)).text), variable)
    except (NotationError, ValueError, RecursionError):
        return None


def _domain(body):
    if _real_spelling(body).strip() in ('ℝ', 'R'):
        return sp.S.Reals
    try:
        return _set_value(parse(normalize_surface(_range_notation(body)).text))
    except (NotationError, ValueError, RecursionError):
        return None


def range_question(candidate, target_ref, formulas, desc):
    """Locate a range question whether its relation is a goal field or a fact.

    A bare range goal owns only one explicitly asked inequality. Multiple bare
    range goals are ambiguous; an arbitrary later condition cannot become one.
    The returned reference always points into the unchanged candidate.
    """
    scope_ref, _ = target_ref.rsplit('/goals/', 1)
    scope, goal = pointer(candidate, scope_ref), pointer(candidate, target_ref)
    if goal.get('kind') != 'find_range':
        return None
    if goal.get('expression'):
        sources = [(target_ref + '/expression', goal['expression'])]
    else:
        bare = [g for g in scope.get('goals', []) if g.get('kind') == 'find_range' and not g.get('expression')]
        if len(bare) != 1:
            return None
        sources = [(f'{scope_ref}/facts/{i}', value) for i, value in enumerate(scope.get('facts', []))]
    text = candidate['original_text']
    hits = []
    for ref, value in sources:
        try:
            ast = parse(value)
        except (NotationError, ValueError):
            continue
        if ast[0] not in ('<', '<=', '>', '>='):
            continue
        for part in formulas:
            if not _same(part[2], value, desc):
                continue
            if (re.search(r'不等式\s*\$\s*$', text[:part[0]])
                    or re.match(r'\s*\$\s*(?:的解集|成立的|的解)', text[part[1]:])):
                hits.append({'part': part, 'expression': value, 'source_ref': ref})
    return hits[0] if len(hits) == 1 else None


def sibling_question_fact_refs(candidate, target_ref, entries, desc):
    """Facts representing a different, source-bound question are not hypotheses."""
    from .fragments import _scope_ranges
    text = candidate['original_text']
    formulas = [part for begin, end in _scope_ranges(candidate, target_ref)
                for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
                for part in _formula_parts(m[1], begin + m.start(1))]
    scope_ref, index = target_ref.rsplit('/goals/', 1)
    refs = set()
    for i, goal in enumerate(pointer(candidate, scope_ref).get('goals', [])):
        if i == int(index) or goal.get('kind') != 'find_range':
            continue
        bound = range_question(candidate, f'{scope_ref}/goals/{i}', formulas, desc)
        if bound:
            refs.update(r['source_ref'] for r in entries if _same(r['expression'], bound['expression'], desc))
    return refs


def sibling_formula_spans(candidate, target_ref, formulas, desc):
    """Only another goal's actual question and its attached range belong to it.

    Position alone never owns a formula: an extra condition after a question
    must still be bound, even on a worksheet with several blanks.
    """
    text = candidate['original_text']
    scope_ref, index = target_ref.rsplit('/goals/', 1)
    goals = pointer(candidate, scope_ref).get('goals', [])
    owned = set()
    for i, goal in enumerate(goals):
        if i == int(index):
            continue
        if goal.get('kind') == 'find_range':
            bound = range_question(candidate, f'{scope_ref}/goals/{i}', formulas, desc)
            hits = [bound['part']] if bound else []
            if len(hits) == 1:
                owned.add(hits[0][:2])
                requested = goal.get('input_domain')
                if requested:
                    bounds = [p for p in formulas if p[0] > hits[0][1]
                              and _range(p[2], goal.get('symbol', desc['variable'])) == _domain(requested)]
                    if len(bounds) == 1:
                        owned.add(bounds[0][:2])
        elif goal.get('kind') == 'find_value' and goal.get('expression'):
            hits = [p for p in formulas if
                    (p[2].rstrip().endswith('=') and _same(p[2].rstrip()[:-1], goal['expression'], desc)
                     and re.match(r'\s*\$\s*[_＿]', text[p[1]:]))
                    or (_same(p[2], goal['expression'], desc)
                        and re.match(r'\s*\$\s*的值(?:为|是)\s*[_＿]', text[p[1]:]))]
            if len(hits) == 1:
                owned.add(hits[0][:2])
        elif goal.get('kind') == 'find_function_formula':
            shape = {**desc, 'function': goal['function'], 'variable': goal['variable']}
            call = f"{goal['function']}({goal['variable']})"
            hits = [p for p in formulas if
                    (p[2].rstrip().endswith('=') and _same(p[2].rstrip()[:-1], call, shape)
                     and re.match(r'\s*\$\s*[_＿]', text[p[1]:]))
                    or (_same(p[2], call, shape)
                        and re.match(r'\s*\$\s*的?(?:解析式|表达式)', text[p[1]:]))]
            if len(hits) != 1:
                continue
            target = hits[0]
            requested = goal.get('requested_domain')
            if requested:
                previous = [p for p in formulas if p[1] < target[0]]
                if not previous:
                    continue
                part = previous[-1]
                if (not re.search(r'(?:当|且|则)\s*\$\s*$', text[:part[0]])
                        or not re.fullmatch(r'\s*\$\s*时\s*[，,]?\s*\$\s*', text[part[1]:target[0]])
                        or _range(part[2], goal['variable']) != _domain(requested)):
                    continue
                owned.add(part[:2])
            owned.add(target[:2])
    return owned


def bind_local_rules(candidate, formulas, desc, target_start):
    """Pair each printed local equality with its own range, not another rule's range."""
    text, bindings, used = candidate['original_text'], [], set()
    for row in rule_rows(desc):
        printed = pointer(candidate, row['source_ref'])
        binder = re.match(r'^\s*∀\s*([A-Za-z]\w*)', printed)
        variable = binder[1] if binder else desc['variable']
        printed = re.sub(r'^\s*∀[^:]*:', '', printed)
        found = []
        for relation in formulas:
            if relation[1] >= target_start or not _same(relation[2], printed, desc):
                continue
            preceding = [p for p in formulas if p[1] < relation[0]]
            if not preceding:
                continue
            known = preceding[-1]
            if (_range(known[2], variable) != region(row['domain_ast'])
                    or not re.search(r'(?:当|且|任意|一切|所有|任何)(?:的)?\s*\$\s*$', text[:known[0]])
                    or not re.match(r'\s*\$\s*(?:时|都有|均有|有)', text[known[1]:])):
                continue
            if (known[0], relation[0]) not in used:
                found.append((known, relation))
        if len(found) != 1:
            return None
        known, relation = found[0]
        used.add((known[0], relation[0]))
        refs = row.get('source_refs', [row['source_ref']])
        bindings.extend([(known, 'condition', refs), (relation, 'expression', refs)])
    return bindings


def source_spans(candidate, target_ref, ranges, desc):
    text = candidate['original_text']
    formulas = [part for begin, end in ranges for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
                for part in _formula_parts(m[1], begin + m.start(1))]
    call = f"{desc['function']}({desc['variable']})"

    def when(part):
        return (re.search(r'(?:当|且|则)\s*\$\s*$', text[:part[0]])
                and re.match(r'\s*\$\s*时', text[part[1]:]))

    def asked(part):
        after = text[part[1]:]
        blank = (part[2].rstrip().endswith('=') and _same(part[2].rstrip()[:-1], call, desc)
                 and re.match(r'\s*\$\s*[_＿]', after))
        named = _same(part[2], call, desc) and re.match(r'\s*\$\s*的?(?:解析式|表达式)', after)
        return bool(blank or named)

    targets = [part for part in formulas if asked(part)]
    if len(targets) != 1:
        return None
    target = targets[0]
    bindings = bind_local_rules(candidate, formulas, desc, target[0])
    if not bindings:
        return None
    first, last = min(p[0] for p, *_ in bindings), max(p[1] for p, *_ in bindings)
    whole = desc['requested_domain_ast'] is None
    requested = [part for part in formulas if last < part[0] < target[0] and when(part)
                 and (whole or _range(part[2], desc['variable']) == region(desc['requested_domain_ast']))]
    abstract = desc['domain_ast'] is None
    domains = [part for part in formulas if re.search(r'(?:定义在|定义域(?:都|均)?(?:为|是))\s*\$\s*$', text[:part[0]])
               and (abstract or _domain(part[2]) == region(desc['domain_ast']))]
    intros = [part for part in formulas if part[1] < first and _same(part[2], call, desc)
              and function_intro(text[:part[0]])]
    functions = [{'name': desc['function'], 'property': desc['property'],
                  'parity_source_ref': desc['parity_source_ref']}]
    properties = parity_spans(text, ranges, intros, functions, desc)
    if (len(requested) != (0 if whole else 1) or len(domains) != (0 if abstract else 1)
            or properties is None):
        return None
    if whole and not re.match(r'\s*\$\s*的?(?:解析式|表达式)', text[target[1]:]):
        return None
    point_rows = []
    for row in desc['point_rules']:
        printed = pointer(candidate, row['source_ref'])
        found = [part for part in formulas if part[1] < target[0] and part not in point_rows
                 and _same(part[2], printed, desc)]
        if len(found) != 1:
            return None
        point_rows.append(found[0])
    rows = [*bindings, *properties,
            *((part, 'condition', [row['source_ref']]) for part, row in zip(point_rows, desc['point_rules'])),
            *((part, 'goal', [target_ref + '/requested_domain']) for part in requested),
            (target, 'goal', [target_ref, target_ref + '/function', target_ref + '/variable']),
            *((part, 'given_domain', list(desc['domain_source_refs'])) for part in domains),
            *((part, 'expression', [target_ref + '/function']) for part in intros)]
    covered = {(part[0], part[1]) for part, *_ in rows}
    siblings = sibling_formula_spans(candidate, target_ref, formulas, desc)
    if any(part[:2] not in covered | siblings for part in formulas):
        return None
    return [(part[0], part[1], kind, refs) for part, kind, refs in sorted(rows, key=lambda row: row[0][0])]
