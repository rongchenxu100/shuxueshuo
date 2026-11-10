"""Locate the parametric expression and the monotonicity-parameter ask for FM-T4."""

import re

from .evaluation_surface import (
    _formula_parts,
    _piecewise_source_matches,
    range_goal_span,
)


def _indexed_names(text):
    # Plain extraction names x1 and displayed x_1 / x_{1} name the same input.
    return re.sub(r'\b([A-Za-z]+)_(?:\{(\d+)\}|(\d+))',
                  lambda match: match[1] + (match[2] or match[3]), text)


def source_spans(candidate, target_ref, ranges, description, matches):
    text = candidate['original_text']
    formulas = [part for begin, end in ranges
                for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
                for part in _formula_parts(m[1], begin + m.start(1))]
    if not formulas:
        return None
    requirement = description['requirement']
    expr = requirement['expression']
    located = [(a, b) for a, b, body in formulas if matches(body, expr)]
    if not located:
        # The source may name its output y while the internal definition uses f(x).
        located = [(a, b) for a, b, body in formulas
                   if re.match(r'^\s*y\s*=', body) and matches(body.split('=', 1)[1], expr)]
    if not located:
        # Allow f(x)=… definition forms that wrap the same body.
        fn = description.get('function')
        if fn:
            wrapped = f'{fn}({description["variable"]})={expr}'
            located = [(a, b) for a, b, body in formulas
                       if matches(body, wrapped) or matches(body, expr)]
    if not located:
        # A printed cases block is matched row by row against the given definition.
        for row in description.get('given_definitions', []):
            located = [(a, b) for a, b, body in formulas
                       if matches(body, row['expression'])
                       or _piecewise_source_matches(body, row['expression'], matches)]
            if located:
                break
    if not located:
        return None
    spans = [(*located[0], 'expression', description['source_refs'][1:] or [target_ref])]
    basis = requirement.get('basis', {'kind': 'stated'})
    if basis['kind'] != 'stated':
        statement = [(a, b) for a, b, body in formulas
                     if matches(_indexed_names(body.replace('[', '(').replace(']', ')')),
                                _indexed_names(description['basis_relation']))]
        if not statement:
            return None
        spans.append((*statement[0], 'condition', [target_ref]))
    variable = description['parameter']
    # Goal ask may not cite a comparison fact; locate the parameter-range prompt.
    goal = range_goal_span(text, formulas, variable, None, matches)
    if goal is None:
        hits = []
        for a, b, body in formulas:
            if variable not in body:
                continue
            window = text[max(0, a - 24):b + 24]
            if re.search(r'取值范围|取值集合|的范围|求实数|求参数', window):
                hits.append((a, b))
        if not hits:
            # Use a textual ask without a formula: 求实数 m 的取值范围
            ask = re.search(
                r'(?:求|则)[^。；]*?' + re.escape(variable) + r'[^。；]*?(?:取值范围|取值集合|的范围)',
                text)
            if not ask:
                return None
            goal = (ask.start(), ask.end())
        else:
            goal = hits[-1]
    spans.append((*goal, 'goal', [target_ref]))
    return spans
