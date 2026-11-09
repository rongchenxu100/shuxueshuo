"""Locate the comparison and range ask for FM-T3 monotonicity inequalities."""

import re

from ...problem_understanding.notation_parser import parse
from ..monotonicity_inequality_math import declared_domain_ast
from .evaluation_surface import (
    _formula_parts,
    _piecewise_source_matches,
    range_goal_span,
)


def source_spans(candidate, target_ref, ranges, description, matches):
    text = candidate['original_text']
    formulas = [part for begin, end in ranges
                for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
                for part in _formula_parts(m[1], begin + m.start(1))]
    spans = []
    relation = None
    for row in description.get('given_definitions') or []:
        ref = row['source_ref']
        located = [(a, b) for a, b, body in formulas
                   if matches(body, row['expression'])
                   or _piecewise_source_matches(body, row['expression'], matches)]
        ast = parse(row['expression'])
        declared_domain = declared_domain_ast(ast, description['function'])
        if declared_domain is not None:
            halves = row['expression'].split('=', 1)
            domain_text = halves[1 if ast[1][:2] == ['call', 'Dom'] else 0]
            for offset, (start, end, body) in enumerate(formulas[:-1]):
                next_start, next_end, next_body = formulas[offset+1]
                named = re.match(r'^\s*' + re.escape(description['function']) + r'\s*\(', body)
                if (named and re.search(r'定义域(?:是|为|恰为)?|定义在', text[end:next_start])
                        and matches(next_body, domain_text)):
                    located.append((start, next_end))
        if not located:
            return None
        kind = 'expression'
        spans.append((*located[0], kind, [ref]))
        if declared_domain is None and ('/facts/' in ref or '/conditions/' in ref):
            relation = row
    if relation is None:
        return None
    variable = description['variable']
    goal = range_goal_span(text, formulas, variable, relation['expression'], matches)
    if goal is None:
        return None
    spans.append((*goal, 'goal', [target_ref]))
    return spans
