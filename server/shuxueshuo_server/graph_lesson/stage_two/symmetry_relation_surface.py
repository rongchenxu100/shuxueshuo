"""Bind general graph statements and quantified reflection scopes to printed evidence."""
import re

from ...problem_understanding.notation_parser import NotationError, parse
from ..parity_extension_math import _replace
from ..symmetry_relation_math import domain_set
from .evaluation_surface import _formula_parts, sum_source_matches
from .parity_extension_surface import (
    _domain,
    _range,
    _range_notation,
    _same,
    parity_spans,
    sibling_formula_spans,
)
from .surface_math import normalize_surface


def _prose(text):
    # Keep offsets, but punctuation/negative signs inside formulas do not split
    # or negate a surrounding assertion.
    return re.sub(r'\$[^$\n]+\$', lambda m: ' '*len(m[0]), text)


_SENTENCE_END = r'[。；;！？!?\n]'
_NOT_ASSERTED = (r'是否|求证|证明|判断|不成立|不满足|不关于|不对称|不能|并非|不是|不为|并不|'
                 r'不对所有|不对任意|不具有|不具备|没有|无法|未必|可能|不一定|吗|[?？]')


def _hypothesis(text, part):
    prose = _prose(text)
    # Keep the quantifier and its polarity across commas. A closing quotation
    # mark also cannot hide “不成立” following the formula.
    before = re.split(_SENTENCE_END, prose[:part[0]])[-1]
    tail = prose[part[1]:]
    end = re.search(r'[，,。；;！？!?\n]', tail)
    after = tail[:end.end()] if end else tail
    if end and end[0] in '，,':
        cursor = part[1]+end.end()
        # A following verbal verdict (“这个结论，不成立” / “对吗？”)
        # still belongs to this claim. Stop at a new formula or sentence.
        while cursor < len(text):
            boundary = re.search(r'[，,。；;！？!?\n]', prose[cursor:])
            finish = cursor+boundary.end() if boundary else len(text)
            if '$' in text[cursor:finish]:
                break
            after += prose[cursor:finish]
            if boundary is None or boundary[0] not in '，,':
                break
            cursor = finish
    return not re.search(_NOT_ASSERTED, before+after)


def _coordinate(body, kind):
    try:
        tree = parse(normalize_surface(_range_notation(body)).text)
    except (NotationError, ValueError, RecursionError):
        return False
    return (tree[0] == '=' and tree[1] == ['name', 'x'] if kind == 'axis'
            else tree[0] == 'tuple' and len(tree) == 3)


def _graph_statement(text, formulas, part, kind):
    """A single assertion may list several axes/centres, including in one display."""
    start = end = formulas.index(part)
    def linked(a, b):
        return (_coordinate(a[2], kind) and _coordinate(b[2], kind)
                and re.fullmatch(r'(?:\s|\$|和|与|及|以及|、|,|，|直线|点|[“”「」])*', text[a[1]:b[0]]))
    while start and linked(formulas[start-1], formulas[start]):
        start -= 1
    while end+1 < len(formulas) and linked(formulas[end], formulas[end+1]):
        end += 1
    first, last = formulas[start], formulas[end]
    prefix, suffix = text[:first[0]], text[last[1]:]
    about = (re.search(r'关于(?:直线|点|中心)?\s*\$\s*$', prefix)
             and re.match(r'\s*\$\s*(?:均|都|分别)?(?:成中心|中心|轴)?对称', suffix))
    noun = '对称轴' if kind == 'axis' else '对称中心'
    nominal = re.search(noun+r'(?:分别)?(?:为|是)(?:直线|点)?\s*\$\s*$', prefix)
    before = re.split(_SENTENCE_END, _prose(text)[:first[0]])[-1]
    return (bool(about or nominal) and _hypothesis(text, (first[0], last[1]))
            and not re.search(r'当|仅在|只在|在[^，,]*区间', before))


def _quantifier_body(text, part):
    """Identify ownership before comparing its variable or range with the extraction."""
    if re.search(r'(?:任意|所有|任何|当)\s*\$\s*$', text[:part[0]]):
        return part[2]
    explicit = re.match(r'\s*(?:∀|\\forall)\s*(.+)', part[2])
    return explicit[1] if explicit else None


def source_spans(candidate, target_ref, ranges, desc):
    text, goal = candidate['original_text'], desc['source']
    if any(candidate['root'].get(k) for k in ('uncertainties',)):
        return None
    formulas = [part for begin, end in ranges for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
                for part in _formula_parts(m[1], begin+m.start(1))]
    def matches(body, expected):
        body = re.sub(r'\\(?:tfrac|dfrac|frac)\s*([0-9])\s*([0-9])',
                      lambda m: r'\frac{' + m[1] + '}{' + m[2] + '}', body)
        return _same(body, expected, desc)
    def target(part, requested):
        body = part[2].rstrip().removesuffix('=').rstrip()
        equal = (sum_source_matches(body, requested['terms'], matches) if requested['kind'] == 'finite_sum'
                 else matches(body, requested.get('expression', '')))
        after = text[part[1]:].lstrip().removeprefix('$').lstrip()
        before = text[max(0, part[0]-8):part[0]]
        return equal and (bool(re.match(r'[_＿]|的(?:值|和)', after)) or bool(re.search(r'求\s*\$?\s*$', before)))
    targets = [p for p in formulas if target(p, goal)]
    if len(targets) != 1:
        return None
    asked = targets[0]
    rows = [(asked[0], asked[1], 'goal', [target_ref])]
    covered = {asked[:2]}
    name = desc['function']
    intro_pattern = rf'\s*(?:y\s*=\s*)?{re.escape(name)}\s*\(\s*([A-Za-z]\w*)\s*\)\s*'
    intros = [p for p in formulas if re.fullmatch(intro_pattern, p[2])
              and p[0] < asked[0] and (re.search(r'(?:函数|设|已知|奇函数|偶函数)\s*\$\s*$', text[:p[0]])
                                      or re.match(r'\s*y\s*=', p[2]))]
    if not intros:
        return None
    # One abstract function is admitted; an adjective cannot migrate from a
    # different subject merely because a nearby axis has matching coordinates.
    for p in formulas:
        if re.fullmatch(r'\s*(?:y\s*=\s*)?[A-Za-z]\w*\s*\(\s*[A-Za-z]\w*\s*\)\s*', p[2]) and p not in intros:
            return None
    def add(p, kind, refs):
        covered.add(p[:2])
        rows.append((p[0], p[1], kind, refs))
    for intro in intros:
        add(intro, 'expression', [target_ref])
    domains = [p for p in formulas if _domain(p[2]) == domain_set(desc['domain_ast'])
               and re.search(r'(?:定义在|定义域(?:为|是)|是|为)\s*\$\s*$', text[:p[0]])
               and p[0] < asked[0] and _hypothesis(text, p)]
    if len(domains) != 1:
        return None
    add(domains[0], 'given_domain', desc['domain_source_refs'])
    parities = [r for r in desc['relations'] if r['ast'][0] == 'function_parity']
    if parities:
        functions = [{'name': name, 'property': r['ast'][2], 'parity_source_ref': r['source_ref']} for r in parities]
        ps = parity_spans(text, ranges, intros[:1], functions,
                          {**desc, 'variable': re.fullmatch(intro_pattern, intros[0][2])[1]})
        if ps is None:
            return None
        for p, k, refs in ps:
            if not _hypothesis(text, p):
                return None
            add(p, k, refs)
    for r in desc['relations']:
        ast = r['ast']
        if ast[0] == 'function_parity':
            continue
        if ast[0] == 'function_graph_symmetry':
            raw = parse(r['expression'])
            # Compare source coordinates syntactically, not a solved identity.
            def render(t):
                if t[0] in ('number', 'name'):
                    return t[1]
                if t[0] == 'neg':
                    return '-'+render(t[1])
                return '('+render(t[1])+')'+t[0]+'('+render(t[2])+')'
            coords = [render(a) for a in raw[4:]]
            expected = 'x='+coords[0] if ast[2] == 'axis' else '('+','.join(coords)+')'
            hits = []
            for p in formulas:
                if p[0] >= asked[0] or not matches(p[2], expected):
                    continue
                if _graph_statement(text, formulas, p, ast[2]):
                    hits.append(p)
            if len(hits) != 1:
                return None
            add(hits[0], 'condition', [r['source_ref']])
        elif ast[0] == 'quantifier':
            prefix, equation = r['expression'].split(':', 1)
            bound = re.match(r'\s*∀\s*([A-Za-z]\w*)', prefix)
            if bound is None:
                return None
            body_hits = [p for p in formulas if p[0] < asked[0] and matches(p[2], equation) and _hypothesis(text, p)]
            if len(body_hits) != 1:
                return None
            body = body_hits[0]
            scope_ast = _replace(ast[3], ['call', 'Dom', ['ref', desc['function_ref'], 'function']], desc['domain_ast'])
            scopes = [p for p in formulas if p[1] < body[0] and _quantifier_body(text, p) is not None]
            # A later quantifier supersedes the earlier one even if its range
            # or variable does not match. Never borrow a convenient old scope.
            scope = scopes[-1] if scopes else None
            if (scope is None or not _hypothesis(text, scope)
                    or re.search(_SENTENCE_END, _prose(text)[scope[1]:body[0]])
                    or _range(_quantifier_body(text, scope), bound[1]) != domain_set(scope_ast)):
                return None
            add(scope, 'condition', [r['source_ref']])
            add(body, 'condition', [r['source_ref']])
    for r in desc['value_equations']:
        hits = [p for p in formulas if p[0] < asked[0] and matches(p[2], r['expression']) and _hypothesis(text, p)]
        if len(hits) != 1:
            return None
        add(hits[0], 'condition', [r['source_ref']])
    siblings = sibling_formula_spans(candidate, target_ref, formulas, desc)
    scope_ref, index = target_ref.rsplit('/goals/', 1)
    from ...problem_understanding.review_contract import pointer
    for i, other in enumerate(pointer(candidate, scope_ref).get('goals', [])):
        if i != int(index) and other.get('kind') == 'finite_sum':
            siblings |= {p[:2] for p in formulas if target(p, other)}
    if any(p[:2] not in covered | siblings for p in formulas):
        return None
    return sorted(rows)
