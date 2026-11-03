"""Locate the complete original cases and input equation, retaining source offsets."""

import re

from .evaluation_surface import _formula_parts, _piecewise_source_matches, pointer


def source_spans(candidate, target_ref, ranges, description, matches):
    text = candidate['original_text']
    formulas = [part for begin, end in ranges
                for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
                for part in _formula_parts(m[1], begin+m.start(1))]
    spans = []
    for row in description['sources']:
        located = [(a, b) for a, b, body in formulas
                   if matches(body, row['expression']) or _piecewise_source_matches(body, row['expression'], matches)]
        if not located:
            return None
        spans.append((*located[0], 'expression', [row['source_ref']]))
    if description['goal_ast']['kind'] == 'match_range':
        expected = pointer(candidate, target_ref)['range']
        located = [(a, b) for a, b, body in formulas
                   if matches(body, expected) and re.search(r'值域(?:为|是)?\s*\$?$', text[max(0, a-12):a])]
        if not located:
            return None
        spans.append((*located[0], 'expression', [target_ref+'/range']))
    goals = [(a, b) for a, b, body in formulas if matches(body, description['variable'])
             and re.search(r'的(?:值|取值|范围)|满足', text[b+1:b+16])]
    if not goals:
        return None
    spans.append((*goals[0], 'goal', [target_ref]))
    return spans
