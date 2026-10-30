"""Bind a function-image target to its original formula and input restrictions."""

import re

from ...problem_understanding.review_contract import pointer
from .evaluation_surface import _formula_parts


def range_source_spans(candidate, target_ref, ranges, description, matches):
    text = candidate['original_text']
    formulas = [part for begin, end in ranges
                for match in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
                for part in _formula_parts(match[1], begin + match.start(1))]
    source = pointer(candidate, description['source_ref'])
    name, variable = description['function_name'], description['variable']
    # Preserve the printed dependent variable in y=... rather than inventing f.
    definition_forms = [source]
    if name == 'y':
        definition_forms.append(source.replace(f'y({variable})', 'y', 1))
    located = [(start, end) for start, end, body in formulas
               if any(matches(body, form) for form in definition_forms)]
    if not located:
        return None
    spans = [(*located[0], 'expression', [description['source_ref']])]
    refs = [description.get('declared_domain_source_ref'), description.get('input_domain_source_ref')]
    refs.extend(row['source_ref'] for row in description.get('restriction_facts', []))
    for ref in filter(None, refs):
        source = pointer(candidate, ref)
        expected = f'{variable}∈{source}' if ref.endswith('/input_domain') else source
        located = [(start, end) for start, end, body in formulas if matches(body, expected)]
        if ref == description.get('declared_domain_source_ref'):
            domain_text = source.split('=', 1)[1].strip()
            for index, (start, end, body) in enumerate(formulas[:-1]):
                next_start, next_end, next_body = formulas[index + 1]
                if (re.match(r'^\s*' + re.escape(name) + r'\s*\(', body)
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
