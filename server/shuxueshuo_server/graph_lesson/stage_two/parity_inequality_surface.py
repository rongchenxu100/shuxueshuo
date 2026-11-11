"""Bind parity, the one-sided rule or printed direction, the domain and the asked inequality to their source text."""
import re

from ...problem_understanding.review_contract import pointer
from ..parity_extension_math import region
from .evaluation_surface import _formula_parts
from .parity_extension_surface import (
    _domain, _range, _same, bind_local_rules, function_intro, parity_spans, range_question, sibling_formula_spans,
)

DOMAIN = r'(?:定义在|定义域(?:都|均)?(?:为|是))\s*\$\s*$'
DIRECTION_WORDS = {'increasing': r'(?:单调)?递增|增函数|单调增', 'decreasing': r'(?:单调)?递减|减函数|单调减'}


def _formulas(text, ranges):
    return [part for begin, end in ranges for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
            for part in _formula_parts(m[1], begin + m.start(1))]


def _domains(text, formulas, value):
    return [part for part in formulas
            if (re.search(DOMAIN, text[:part[0]])
                or (re.search(r'(?:是|为)\s*\$\s*$', text[:part[0]])
                    and re.match(r'\s*\$\s*上的\s*(?:奇|偶)函数', text[part[1]:])))
            and (value is None or _domain(part[2]) == value)]


def _input_rows(candidate, target_ref, formulas, desc, rows):
    from ..parity_inequality_inputs import constraint_rows
    covered = {part[:2] for part, *_ in rows}
    covered |= sibling_formula_spans(candidate, target_ref, formulas, desc)
    added = []
    for row in constraint_rows(desc['given_entries'], desc['variable']):
        if row['ast'][0] == 'default_domain' and row['ast'][2] == 'real':
            labels = [p for p in formulas if p[2].strip() == desc['variable']
                      and re.search(r'实数\s*\$\s*$', candidate['original_text'][:p[0]])]
            if len(labels) == 1:
                shared = next((r for r in rows if r[0][:2] == labels[0][:2]), None)
                if shared:
                    shared[2].append(row['source_ref'])
                else:
                    added.append((labels[0], 'condition', [row['source_ref']]))
                continue
        found = [p for p in formulas if p[:2] not in covered and _same(p[2], row['expression'], desc)]
        if len(found) != 1:
            return None
        added.append((found[0], 'condition', [row['source_ref']]))
        covered.add(found[0][:2])
    requested = desc['source'].get('input_domain')
    if requested is not None:
        found = [p for p in formulas if p[:2] not in covered
                 and _range(p[2], desc['variable']) == _domain(requested)]
        if len(found) != 1:
            return None
        added.append((found[0], 'condition', [target_ref + '/input_domain']))
    return added


def source_spans(candidate, target_ref, ranges, desc):
    if desc.get('route') in ('order', 'sign') and desc['direction_source']['kind'] == 'given':
        return _given_spans(candidate, target_ref, ranges, desc)
    ext = desc['extension'] if desc.get('route') != 'order' else desc['direction_source']['extension']
    text = candidate['original_text']
    formulas = _formulas(text, ranges)
    call = f"{desc['function']}({desc['variable']})"
    bound = range_question(candidate, target_ref, formulas, ext)
    if bound is None or bound['source_ref'] != desc['relation_source_ref']:
        return None
    target = bound['part']
    bindings = bind_local_rules(candidate, formulas, ext, target[0])
    if not bindings:
        return None
    first = min(p[0] for p, *_ in bindings)
    abstract = ext['domain_ast'] is None
    domains = _domains(text, formulas, None if abstract else region(ext['domain_ast']))
    intros = [part for part in formulas if part[1] < first
              and _same(re.sub(r'^\s*y\s*=', '', part[2]), call, ext)
              and function_intro(text[:part[0]])]
    functions = [{'name': desc['function'], 'property': desc['property'],
                  'parity_source_ref': desc['parity_source_ref']}]
    properties = parity_spans(text, ranges, intros, functions, ext)
    if len(domains) != (0 if abstract else 1) or properties is None:
        return None
    rows = [*bindings, *properties,
            (target, 'goal', [target_ref, desc['relation_source_ref'], target_ref + '/symbol']),
            *((part, 'given_domain', list(desc['domain_source_refs'])) for part in domains),
            *((part, 'expression', [desc['parity_source_ref']]) for part in intros)]
    inputs = _input_rows(candidate, target_ref, formulas, desc, rows)
    if inputs is None:
        return None
    rows.extend(inputs)
    covered = {(part[0], part[1]) for part, *_ in rows}
    siblings = sibling_formula_spans(candidate, target_ref, formulas, desc)
    if any(part[:2] not in covered | siblings for part in formulas):
        return None
    return [(part[0], part[1], kind, refs) for part, kind, refs in sorted(rows, key=lambda row: row[0][0])]


def _given_spans(candidate, target_ref, ranges, desc):
    """A printed direction (stated words or a difference quotient/product) on a printed domain; the sign
    route may leave the domain unprinted and binds each printed zero value."""
    text = candidate['original_text']
    formulas = _formulas(text, ranges)
    source = desc['direction_source']
    name, variable = desc['function'], desc['variable']
    shape = {'function': name, 'variable': 'x'}
    relation = pointer(candidate, desc['relation_source_ref'])
    symbols = [part for part in formulas if part[2].strip() == variable
               and re.search(r'实数\s*\$\s*$', text[:part[0]])
               and re.match(r'\s*\$\s*的?取值范围', text[part[1]:])]
    # The inequality is asked as such, or printed as a condition whose real variable's range is then asked.
    asked = [part for part in formulas if _same(part[2], relation, shape)
             and (re.search(r'(?:不等式|满足)\s*\$\s*$', text[:part[0]])
                  or re.match(r'\s*\$\s*(?:的解集|成立)', text[part[1]:])
                  or (len(symbols) == 1 and symbols[0][0] > part[1]))]
    if len(asked) != 1:
        return None
    solution_set = re.match(r'\s*\$\s*的解集', text[asked[0][1]:])
    if symbols if solution_set else (len(symbols) != 1 or symbols[0][0] < asked[0][1]):
        return None
    sign = desc.get('route') == 'sign'
    intros = [part for part in formulas if re.fullmatch(rf'\s*(?:y\s*=\s*)?{re.escape(name)}\s*\(\s*[a-z]\s*\)\s*', part[2])
              and function_intro(text[:part[0]])]
    if len(intros) != 1:
        return None
    shape['variable'] = re.search(r'\(\s*([a-z])\s*\)', intros[0][2])[1]
    printed = _domains(text, formulas, None)
    domains = [part for part in printed if desc['domain_ast'] is not None
               and _printed_domain(part[2], desc, desc['domain_ast'])]
    functions = [{'name': name, 'property': desc['property'], 'parity_source_ref': desc['parity_source_ref']}]
    properties = parity_spans(text, ranges, intros, functions, shape)
    if properties is None or any(part[1] > asked[0][0] for part in domains):
        return None
    if len(domains) != (0 if desc['domain_ast'] is None else 1) or len(printed) != len(domains):
        return None
    mono_ref = source['source_ref']
    zeros = []
    from ..parity_order_math import _origin_rows
    point_refs = desc.get('zero_source_refs', []) if sign else [
        r['source_ref'] for r in _origin_rows(desc['given_entries'], name)]
    for ref in point_refs:
        fact = pointer(candidate, ref)
        found = [part for part in formulas if part[1] < asked[0][0] and _same(part[2], fact, shape)]
        if len(found) != 1:
            return None
        zeros.append((found[0], 'condition', [ref]))
    rows = [*properties, *((part, 'given_domain', list(desc['domain_source_refs'])) for part in domains), *zeros,
            (intros[0], 'expression', [mono_ref if source.get('from_fact') else mono_ref + '/function']),
            (asked[0], 'goal', [desc['relation_source_ref'], *([target_ref, target_ref + '/symbol'] if solution_set else [])]),
            *((part, 'goal', [target_ref, target_ref + '/symbol']) for part in symbols)]
    basis = source['basis']
    statement_end = None
    if basis['kind'] == 'stated':
        words = [(m.start(), m.end()) for m in re.finditer(DIRECTION_WORDS[source['direction']], text)
                 if m.end() < asked[0][0]]
        opposite = [m for m in re.finditer(DIRECTION_WORDS['decreasing' if source['direction'] == 'increasing'
                                                           else 'increasing'], text) if m.end() < asked[0][0]]
        if len(words) != 1 or opposite:
            return None
        # Bind a positive, strict assertion, not a substring of 非递增/不是增函数.
        clause = re.split(r'[，,。；;！？!?]', text[:words[0][0]])[-1]
        if re.search(r'非|不|未必|可能|未能|无法', clause):
            return None
        statement_end = words[0][1]
        rows.append(((words[0][0], words[0][1], text[words[0][0]:words[0][1]]), 'condition', [mono_ref]))
    else:
        from ..monotonicity_parameter_math import _basis_relation_text
        from .monotonicity_parameter_surface import _indexed_names
        statement = _basis_relation_text(basis)
        statements = [part for part in formulas if part[1] < asked[0][0]
                      and (_same(_indexed_names(part[2]), _indexed_names(basis['statement']), shape)
                           or _same(_indexed_names(part[2]), _indexed_names(statement), shape))]
        if len(statements) != 1:
            return None
        statement_end = statements[0][1]
        rows.append((statements[0], 'condition', [mono_ref] if source.get('from_fact') else [mono_ref, mono_ref + '/basis']))
    interval = [part for part in formulas if part[1] <= statement_end and part not in domains
                and re.search(r'在\s*\$\s*$', text[:part[0]]) and re.match(r'\s*\$\s*上', text[part[1]:])
                and _interval_text(part[2])]
    if interval:
        if len(interval) != 1 or not _printed_domain(interval[0][2], desc, source['interval_ast']):
            return None
        rows.append((interval[0], 'condition', [mono_ref if source.get('from_fact') else mono_ref + '/domain']))
    elif sign or not _same_ast(desc, source['interval_ast'], desc['domain_ast']):
        return None
    inputs = _input_rows(candidate, target_ref, formulas, desc, rows)
    if inputs is None:
        return None
    rows.extend(inputs)
    covered = {(part[0], part[1]) for part, *_ in rows}
    if any((part[0], part[1]) not in covered for part in formulas):
        return None
    return [(part[0], part[1], kind, refs) for part, kind, refs in sorted(rows, key=lambda row: row[0][0])]


def _plain(text):
    text = re.sub(r'\\math(?:bf|bb)\s*\{?R\}?|\bR\b', 'ℝ', text)
    return re.sub(r'\+?\s*\\infty', '∞', text)


def _interval_text(text):
    from ..parity_order_math import base_parse
    try:
        return base_parse(_plain(text))[0] in ('interval', 'real', 'tuple')
    except (ValueError, TypeError, IndexError):
        return False


def _same_ast(desc, a, b):
    from ..parity_order_math import _same_domain
    try:
        return _same_domain([a, b], desc.get('parameter'))
    except (ValueError, TypeError, KeyError, IndexError):
        return False


def _printed_domain(text, desc, ast):
    """A printed interval equals a bound domain AST, with the domain parameter read by name."""
    from ..parity_order_math import _named, base_parse
    try:
        printed = _named(base_parse(_plain(text)), desc.get('parameter'))
    except (ValueError, TypeError, IndexError):
        return False
    return _same_ast(desc, printed, ast)


def region_of(text):
    from ..extremum_math import domain
    from ..parity_order_math import _interval, base_parse
    return _interval(domain(base_parse(text)))
