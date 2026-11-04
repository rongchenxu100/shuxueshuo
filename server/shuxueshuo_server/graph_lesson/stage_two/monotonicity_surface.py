"""Bind the actual direction request, expression and restriction to the source."""
import re

from .evaluation_surface import _formula_parts


def source_spans(candidate, target_ref, ranges, description, matches):
    text, goal = candidate['original_text'], description['source']
    formulas = [part for begin, end in ranges for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
                for part in _formula_parts(m[1], begin+m.start(1))]
    given = [r for r in formulas if matches(r[2], goal['expression'], call=True, alias_variables=(goal['variable'],))]
    if len(given) != 1:
        return None
    requests = {'increasing': r'(?:单调(?:递)?增|递增)(?:区间|性)?',
                'decreasing': r'(?:单调(?:递)?减|递减)(?:区间|性)?', 'both': r'单调区间|单调性'}
    located = {direction: [(start+m.start(), start+m.end()) for start, end in ranges
                          for m in re.finditer(pattern, text[start:end])]
               for direction, pattern in requests.items()}
    directions = [direction for direction in ('increasing', 'decreasing') if located[direction]]
    # An explicit pair of requests asks for both families. Check all directions
    # together so neither family can silently disappear from the extracted goal.
    requested = 'both' if len(directions) == 2 or not directions else directions[0]
    spans = [span for direction in directions or ['both'] for span in located[direction]]
    if requested != goal['direction'] or any(len(located[d]) != 1 for d in directions or ['both']):
        return None
    rows = [(*given[0][:2], 'goal', [target_ref, target_ref+'/expression', target_ref+'/variable']),
            *((*span, 'goal', [target_ref, target_ref+'/direction']) for span in spans)]
    # Bind the domain, even if its expression would happen to give the same answer.
    domain_mentions = [r for r in formulas if re.search(r'\\in|∈', r[2])]
    if 'input_domain' in goal:
        found = [r for r in formulas if matches(r[2], goal['variable']+'∈'+goal['input_domain'])]
        if len(found) != 1:
            return None
        rows.append((*found[0][:2], 'given_domain', [target_ref+'/input_domain']))
        declared = bool(re.search(r'定义域(?:为|是)', text))
        if declared != (goal.get('domain_role', 'restriction') == 'declared'):
            return None
    elif domain_mentions or re.search(r'定义域(?:为|是)|在区间', text):
        return None
    if goal['kind'] == 'prove_monotonicity_on_interval' and not re.search('证明|求证', text):
        return None
    return rows
