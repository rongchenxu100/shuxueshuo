"""Bind each supplied translation fact to its actual function and text clause."""

import re

from ...problem_understanding.notation_parser import NotationError, parse
from ...problem_understanding.review_contract import pointer
from .evaluation_surface import _formula_parts
from .surface_math import normalize_surface


def translation_source_spans(candidate, target_ref, ranges, desc, matches):
    text = candidate['original_text']
    goal = pointer(candidate, target_ref)
    formulas = [part for begin, end in ranges for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
                for part in _formula_parts(m[1], begin+m.start(1))]
    relations = [part for part in formulas if matches(part[2], goal['function_relation'])]
    if len(relations) != 1:
        return None
    relation = relations[0]

    def call_name(part):
        try:
            ast = parse(normalize_surface(part[2]).text)
            return ast[1] if ast[0] == 'call' else None
        except (NotationError, ValueError):
            return None
    # The periodicity clause must name the periodic function, not f. Keep its
    # domain and period in that same preceding clause, never any equal number.
    heads = [part for part in formulas if part[1] < relation[0] and
             (matches(part[2], desc['periodic_name']) or
              matches(part[2], desc['periodic_name']+'('+desc['variable']+')'))]
    if not heads:
        return None
    head = heads[-1]
    clause = text[head[1]:relation[0]]
    if '周期' not in clause or '定义' not in clause:
        return None
    if any(call_name(part) not in (None, desc['periodic_name'])
           for part in formulas if head[1] < part[0] < relation[0]):
        return None
    domains = [part for part in formulas if head[1] < part[0] < relation[0]
               and matches(part[2], goal['periodic_domain'])]
    periods = [part for part in formulas if head[1] < part[0] < relation[0]
               and matches(part[2], goal['period']) and re.match(r'\$?\s*为周期', text[part[1]:])]
    if not periods:
        for m in re.finditer(r'以\s*([^，,。；;]+?)\s*为周期', clause):
            body = m[1].strip().strip('$')
            if matches(body, goal['period']):
                periods.append((head[1]+m.start(1), head[1]+m.end(1), body))
    if len(domains) != 1 or len(periods) != 1:
        return None
    # A local exact image is distinct from both the global domain and the
    # final requested input interval. Tie the pair through the word 值域.
    pairs = []
    for base in formulas:
        if base[0] < relation[1] or not matches(base[2], goal['known_domain']):
            continue
        owners = [call_name(part) for part in formulas if relation[1] < part[0] < base[0]
                  and call_name(part) is not None]
        if owners and owners[-1] != desc['function_name']:
            continue
        for image in formulas:
            if (0 < image[0]-base[1] < 65 and matches(image[2], goal['known_range'])
                    and re.search(r'值域(?:为|是)', text[base[1]:image[0]])):
                pairs.append((base, image))
    if len(pairs) != 1:
        return None
    base, image = pairs[0]
    targets = [part for part in formulas if part[0] > image[1] and matches(part[2], goal['input_domain'])]
    if len(targets) != 1:
        return None
    target = targets[0]
    f_calls = [part for part in formulas if image[1] < part[0] < target[0]
               and matches(part[2], desc['function_name']+'('+desc['variable']+')')]
    if not f_calls:
        return None
    goals = list(re.finditer('值域', text[target[1]:ranges[-1][1]]))
    if not goals:
        return None
    span = goals[-1]
    rows = [(relation, ['function_relation']), (head, ['periodic_function']),
            (domains[0], ['periodic_domain']), (periods[0], ['period']),
            (base, ['known_domain']), (image, ['known_range']), (target, ['input_domain'])]
    return [(a, b, 'expression', [target_ref+'/'+field for field in fields]) for (a, b, _), fields in rows] + [
        (target[1]+span.start(), target[1]+span.end(), 'goal', [target_ref])]
