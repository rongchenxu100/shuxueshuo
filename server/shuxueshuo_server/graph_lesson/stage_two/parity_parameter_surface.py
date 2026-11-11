"""Locate the given property as well as the formula and parameter request."""
import re

from ...problem_understanding.notation_parser import parse
from .evaluation_surface import _formula_parts, _piecewise_source_matches
from .parity_surface import _domains
from .surface_math import normalize_surface


def _domain_roles(text, ranges, variable):
    domains, defined = [], []
    for a, b, body in _domains(text, ranges, variable):
        role = defined if re.match(r'\$?\s*(?:上|内)?\s*(?:均|都)?(?:有意义|有定义)', text[b:]) else domains
        role.append((a, b, body))
    return domains, defined


def _requests(text, ranges, description):
    parameter = re.escape(description['parameter'])
    if description.get('analysis_mode') == 'joint':
        a, b = map(re.escape, description['parameters'])
        separator = r'\s*\$?\s*[,，、和与]\s*\$?\s*'
        pair = '(?:'+a+separator+b+'|'+b+separator+a+')'
        parameter = r'(?:\(|（)?\s*(?<![A-Za-z0-9_\u0370-\u03ff])'+pair+r'(?![A-Za-z0-9_\u0370-\u03ff])\s*(?:\)|）)?'
    return [(begin+m.start(), begin+m.end()) for begin, end in ranges
            for m in re.finditer(r'(?:求|则)[^。；\n]*?\$?\s*'+parameter+r'\s*\$?\s*的(?:值|取值范围|范围|条件|关系)', text[begin:end])]


def _source_set(body):
    text = 'ℝ' if body.strip() in ('R', '实数集') else body
    return parse(normalize_surface(text.replace(r'\setminus', '∖')).text)


def source_spans(candidate, target_ref, ranges, description, matches):
    text = candidate['original_text']
    formulas = [part for begin, end in ranges for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
                for part in _formula_parts(m[1], begin + m.start(1))]
    function = next(r for r in description['given_entries'] if r['source_ref'] == description['function_source_ref'])
    located = [(a, b) for a, b, body in formulas if matches(body, function['expression'])
               or _piecewise_source_matches(body, function['expression'], matches)]
    if not located and description.get('analysis_mode') == 'domain' and description['expression_ast'] is None:
        located = [(a, b) for a, b, _ in _domain_roles(text, ranges, description['variable'])[0]]
    if not located:
        return None
    properties = _properties(text, ranges, description['function'])
    if not audit_requirements(candidate, target_ref, description):
        return None
    domains, meaningful = _domain_roles(text, ranges, description['variable'])
    asks = _requests(text, ranges, description)
    if not asks:
        return None
    spans = [(*located[0], 'expression', [function['source_ref']]),
             *[(a, b, 'condition', description['source_refs'][1:]) for a, b, _ in properties],
             *[(a, b, 'given_domain', description['source_refs'][1:]) for a, b, _ in domains],
             *[(a, b, 'condition', description['source_refs'][1:]) for a, b, _ in meaningful],
             (*asks[-1], 'goal', [target_ref])]
    for row in description['constraints']:
        spans.extend((a, b, 'condition', [row['source_ref']]) for a, b, body in formulas if matches(body, row['expression']))
    return spans


def _properties(text, ranges, function):
    properties = []
    pattern = (r'既(?:是|为)?奇函数\s*(?:又|也)(?:是|为)?偶函数|既奇又偶|'
               r'奇函数(?:但|且|而)(?:不|非)(?:是|为)?偶函数|奇而非偶|'
               r'偶函数(?:但|且|而)(?:不|非)(?:是|为)?奇函数|偶而非奇|奇函数|偶函数')
    for begin, end in ranges:
        for match in re.finditer(pattern, text[begin:end]):
            wording = match[0]
            prop = ('both' if wording.startswith('既') else
                    'odd_only' if wording.startswith('奇') and re.search(r'不|非', wording) else
                    'even_only' if wording.startswith('偶') and re.search(r'不|非', wording) else
                    'odd' if wording == '奇函数' else 'even')
            properties.append((begin+match.start(), begin+match.end(), prop))
        for match in re.finditer(r'parity\(\s*'+re.escape(function)+r'\s*,\s*(odd_only|even_only|odd|even|both)\s*\)', text[begin:end]):
            properties.append((begin+match.start(), begin+match.end(), match[1]))
    return properties


def audit_requirements(candidate, target_ref, description):
    from .fragments import _abstract_formula_matches, _scope_ranges
    text, ranges = candidate['original_text'], _scope_ranges(candidate, target_ref)
    if description.get('analysis_mode') == 'joint' and not _requests(text, ranges, description):
        return False
    properties = _properties(text, ranges, description['function'])
    actual = {p for _, _, p in properties}
    required = {f['property'] for f in description['parity_facts']}
    if actual != required and not (actual == {'odd', 'even'} and required == {'both'}):
        return False
    domains, meaningful = _domain_roles(text, ranges, description['variable'])
    declared = [r for r in description['given_entries'] if r['ast'][0] == '='
                and any(side == ['call', 'Dom', ['ref', description['function_ref'], 'function']]
                        for side in r['ast'][1:])]
    expected_domains = []
    for row in declared:
        ast = parse(row['expression'])
        # Match source notation, without simplifying away any endpoint/hole.
        for call, value in (ast[1:], ast[1:][::-1]):
            if call[:2] == ['call', 'Dom']:
                expected_domains.append(value)
    if domains:
        for _, _, body in domains:
            try:
                actual_domain = _source_set(body)
                if actual_domain not in expected_domains:
                    return False
            except ValueError:
                return False
    if domains and not declared:
        return False
    scope_text = ' '.join(text[a:b] for a, b in ranges)
    degrees = {value for label, value in [('非零常函数', 0), ('一次函数', 1), ('二次函数', 2), ('三次函数', 3), ('四次函数', 4)]
               if label in scope_text}
    degrees.update(int(m[1]) for m in re.finditer(
        r'degree\(\s*' + re.escape(description['function']) + r'\s*\)\s*=\s*([01234])', scope_text))
    if degrees != {r['degree'] for r in description['degrees']}:
        return False
    # Preserve each written mathematical condition. This is source matching,
    # not permission to infer a missing parameter bound from the desired answer.
    source = [part for begin, end in ranges for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
              for part in _formula_parts(m[1], begin + m.start(1))]
    if any(not domains and not any(_abstract_formula_matches(body, row['expression']) for _, _, body in source)
           for row in declared):
        return False
    local_refs = {r['source_ref'] for r in description.get('local_rules', [])}
    if any(not any(_abstract_formula_matches(body, row['expression']) for _, _, body in source)
           for row in description['given_entries'] if row['source_ref'] in local_refs):
        return False
    defined_rows = [r for r in description['given_entries'] if r['ast'][0] == 'function_defined_on']
    defined_domains = [parse(r['expression'])[3] for r in defined_rows]
    if any(_source_set(body) not in defined_domains for _, _, body in meaningful):
        return False
    for row, domain in zip(defined_rows, defined_domains, strict=True):
        if not (any(_abstract_formula_matches(body, row['expression']) for _, _, body in source)
                or any(_source_set(body) == domain for _, _, body in meaningful)):
            return False
    if any(not any(_abstract_formula_matches(body, row['expression']) for _, _, body in source)
           for row in description['constraints']):
        return False
    entries = [r['expression'] for r in description['given_entries']]
    for _, _, body in source:
        if (re.search(r'[=<>≤≥∈∉]|\\(?:leq?|geq?|ne|in|notin)\b', body)
                and not any(_abstract_formula_matches(body, expression)
                            or _piecewise_source_matches(body, expression, _abstract_formula_matches)
                            for expression in entries)):
            return False
    return True
