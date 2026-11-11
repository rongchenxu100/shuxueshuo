"""Bind the parity request, the original rule and any given input set to the source."""
import re

from ...problem_understanding.notation_parser import NotationError
from .evaluation_surface import _formula_parts

REQUEST = r'奇偶性|(?:是|为)?(?:奇函数|偶函数)'


def _domains(text, ranges, variable):
    """Locate source input sets in membership, domain prose and interval prose."""
    result = []
    for begin, end in ranges:
        segment = text[begin:end]
        for match in re.finditer(r'\$([^$\n]+)\$', segment):
            for start, stop, body in _formula_parts(match[1], begin + match.start(1)):
                membership = re.match(rf'\s*{re.escape(variable)}\s*(?:\\in\b|∈)\s*(.+)$', body)
                if membership:
                    result.append((start, stop, membership[1]))
                elif re.search(r'(?:定义域\s*(?:为|是)?|在\s*(?:区间)?)\s*\$?\s*$', text[begin:start]):
                    result.append((start, stop, body))
        # OCR may retain plain Unicode notation instead of wrapping it in $.
        pattern = (rf'(?:定义域\s*(?:为|是)?|在\s*(?:区间)?|{re.escape(variable)}\s*∈)'
                   r'\s*([^$，。；\n]+)')
        # Branch-local membership inside the formula is not the whole input set.
        prose = re.sub(r'\$[^$\n]+\$', lambda match: ' ' * len(match[0]), segment)
        for match in re.finditer(pattern, prose):
            body = re.split(r'上|内|的|判断', match[1], maxsplit=1)[0].strip()
            if body and (body[0] in '([（｛{ℝR' or body.startswith('实数集')):
                start = begin + match.start(1)
                result.append((start, start + len(body), 'R' if body == '实数集' else body))
    return list(dict.fromkeys(result))


def audit_domain(candidate, target_ref):
    """A missing/mismatched source set is an admission failure, not merely lost D1."""
    from ...problem_understanding.review_contract import pointer
    from .fragments import _abstract_formula_matches, _scope_ranges

    goal = pointer(candidate, target_ref)
    ranges = _scope_ranges(candidate, target_ref)
    text = candidate['original_text']
    domains = _domains(text, ranges, goal['variable'])
    expected = goal.get('input_domain')
    if domains:
        if expected is None:
            raise NotationError('function_parity.source_domain_missing')
        if any(not _abstract_formula_matches('ℝ' if body.strip() in ('R', '实数集') else body, expected)
               for _, _, body in domains):
            raise NotationError('function_parity.source_domain_mismatch')
    elif expected is not None or any(re.search(r'定义域|(?:\\in\b|∈)', re.sub(r'\$[^$\n]+\$', '', text[a:b]))
                                    for a, b in ranges):
        raise NotationError('function_parity.source_domain_not_located')
    return domains


def source_spans(candidate, target_ref, ranges, goal, matches):
    text = candidate['original_text']
    formulas = [part for begin, end in ranges for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
                for part in _formula_parts(m[1], begin + m.start(1))]
    given = [row for row in formulas
             if matches(row[2], goal['expression'], call=True, alias_variables=(goal['variable'],))]
    requests = [(start + m.start(), start + m.end()) for start, end in ranges
                for m in re.finditer(REQUEST, text[start:end])]
    if len(given) != 1 or not requests:
        return None
    rows = [(*given[0][:2], 'goal', [target_ref, target_ref + '/expression', target_ref + '/variable']),
            *((*span, 'goal', [target_ref]) for span in requests)]
    try:
        domains = audit_domain(candidate, target_ref)
    except (NotationError, ValueError):
        return None
    rows.extend((start, stop, 'given_domain', [target_ref + '/input_domain']) for start, stop, _ in domains)
    return rows
