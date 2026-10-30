"""Bind a function-image target to its original formula and input restrictions."""

import re

from ...problem_understanding.notation_parser import NotationError, parse
from ...problem_understanding.review_contract import pointer
from .evaluation_surface import _formula_parts
from .surface_math import normalize_surface


def _input_matches(body, expected, matches):
    if matches(body, expected):
        return True
    try:
        stated = parse(normalize_surface(body).text)
        wanted = parse(expected)
    except (NotationError, ValueError):
        return False
    if wanted[0] != '∈':
        return False
    variable, interval = wanted[1:]
    if interval[0] == 'tuple' and len(interval) == 3:
        interval = ['interval', False, False, *interval[1:]]
    if interval[0] != 'interval':
        return False
    left_closed, right_closed, left, right = interval[1:]
    required = [['<=' if left_closed else '<', left, variable],
                ['<=' if right_closed else '<', variable, right]]
    required = [row for row in required if not any(v[0] in ('infinity',) or v == ['neg', ['infinity']] for v in row[1:])]
    # Compare only the exact endpoint inequalities, without solving a new
    # condition or borrowing a range from another occurrence.
    def canonical(row):
        if row[0] in ('>', '>='):
            return [{'>' : '<', '>=': '<='}[row[0]], row[2], row[1]]
        return row
    actual = stated[1:] if stated[0] == 'and' else [stated]
    return sorted(map(repr, map(canonical, actual))) == sorted(map(repr, required))


def _range_parts(body, start):
    result = []
    for begin, end, formula in _formula_parts(body, start):
        result.append((begin, end, formula))
        # Printed y=P(x)(a<x<b) uses the final parentheses for the input
        # restriction. Split that annotation, never an arithmetic factor.
        if not formula.rstrip().endswith((')', '）')):
            continue
        for mark in re.finditer(r'(?:\\left\s*)?[（(]', formula):
            inside = re.sub(r'\\right\s*$', '', formula[mark.end():].rstrip()[:-1])
            try:
                condition = parse(normalize_surface(inside).text)
            except (NotationError, ValueError):
                continue
            if condition[0] in ('and', '<', '<=', '>', '>=', '∈'):
                result.extend([(begin, begin+mark.start(), formula[:mark.start()]),
                               (begin+mark.end(), end-1, inside)])
                break
    return result


def range_source_spans(candidate, target_ref, ranges, description, matches):
    text = candidate['original_text']
    formulas = [part for begin, end in ranges
                for match in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
                for part in _range_parts(match[1], begin + match.start(1))]
    source = pointer(candidate, description['source_ref'])
    name, variable = description['function_name'], description['variable']
    # y=... may use a local function alias, as in the shared extraction rules.
    # Compare the entire original RHS; never rename an explicitly named function.
    definition_forms = [source]
    named = re.compile(r'^\s*' + re.escape(name) + r'\s*(?:\\left\s*)?\(')
    if not description.get('relation_input_ast') and (name == 'y' or not any(named.match(body) for _, _, body in formulas)):
        definition_forms.append('y=' + source.split('=', 1)[1])
    located = [(start, end) for start, end, body in formulas
               if any(matches(body, form) for form in definition_forms)]
    if not located:
        return None
    definition_span = located[0]
    spans = [(*definition_span, 'expression', [description['source_ref']])]
    refs = [description.get('declared_domain_source_ref'), description.get('input_domain_source_ref')]
    refs.extend(row['source_ref'] for row in description.get('restriction_facts', []))
    for ref in filter(None, refs):
        source = pointer(candidate, ref)
        expected = f'{variable}∈{source}' if ref.endswith('/input_domain') else source
        located = [(start, end) for start, end, body in formulas if _input_matches(body, expected, matches)]
        if ref == description.get('declared_domain_source_ref'):
            domain_text = source.split('=', 1)[1].strip()
            for index, (start, end, body) in enumerate(formulas[:-1]):
                next_start, next_end, next_body = formulas[index + 1]
                if ((named.match(body) or (start, end) == definition_span)
                        and re.search(r'定义域(?:是|为|恰为)?', text[end:next_start])
                        and matches(next_body, domain_text)):
                    located.append((start, next_end))
        if not located:
            return None
        spans.append((*located[0], 'expression', [ref]))
    goals = [(begin + match.start(), begin + match.end()) for begin, end in ranges
             for match in re.finditer(r'值域', text[begin:end])]
    if not goals:
        return None
    spans.append((*goals[-1], 'goal', [target_ref]))
    return spans
