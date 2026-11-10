"""Locate each original function/condition and the requested extrema goal."""
import re
from itertools import pairwise

from ...problem_understanding.notation_parser import parse
from .evaluation_surface import _piecewise_source_matches, source_formulas


def _text(ast):
    """Serialize just the source grammar needed for local, exact span matching."""
    if ast[0] in ('name', 'number'):
        return str(ast[1])
    if ast[0] == 'real':
        return 'ℝ'
    if ast[0] in ('infinity', 'infty'):
        return '-∞' if ast[1] < 0 else '∞'
    if ast[0] == 'interval':
        return ('[' if ast[1] else '(')+_text(ast[3])+','+_text(ast[4])+(']' if ast[2] else ')')
    if ast[0] == 'call':
        return ast[1]+'('+','.join(_text(c) for c in ast[2:])+')'
    if ast[0] == 'neg':
        return '-('+_text(ast[1])+')'
    if ast[0] in ('+', '-', '*', '/', '^'):
        return '('+_text(ast[1])+')'+ast[0]+'('+_text(ast[2])+')'
    if ast[0] in ('=', '<', '<=', '>', '>=', '∈'):
        return _text(ast[1])+ast[0]+_text(ast[2])
    raise ValueError('unsupported extrema source span')


def _natural_fact(text, ast, formulas, matches):
    if ast[0] == 'quantifier' and ast[4][0] == 'quantifier':
        outer, inner = ast, ast[4]
        spans = []
        for q, glyph, words in ((outer, '∀', r'任意|每个'), (inner, '∃', r'存在')):
            member = _text(['∈', ['name', q[2]], q[3]])
            hits = []
            for a, b, body in formulas:
                cleaned = re.sub(r'\\forall|\\exists|[∀∃]', '', body).strip()
                marked = (glyph in body or ('\\forall' if glyph == '∀' else '\\exists') in body or
                          re.search('(?:'+words+r')[^。；;$]{0,12}\$?$', text[max(0, a-16):a]))
                if marked and matches(cleaned, member):
                    hits.append((a, b))
            if len(hits) != 1:
                return None
            spans.append(hits[0])
        relations = [(a, b) for a, b, body in formulas if matches(body, _text(inner[4]))]
        if len(relations) != 1 or not spans[0][1] <= spans[1][0] or not spans[1][1] <= relations[0][0]:
            return None
        return [*spans, relations[0]]
    if ast[0] == '=':
        ext, call = ast[1:]
        if call[0] == 'extremum':
            ext, call = call, ext
        if ext[0] != 'extremum' or call[0] != 'call':
            return None
        label = '最大值' if ext[1] == 'max' else '最小值'
        hits = []
        for a, b, body in formulas:
            if not matches(body, _text(call)):
                continue
            before, after = text[max(0, a-35):a], text[b:b+55]
            prior = re.search(label+r'(?:为|是|等于)\s*\$?$', before)
            following = re.match(r'\$?\s*(?:是|为)(?:函数)?(?:\s*\$[^$]+\$\s*)?(?:的)?'+label, after)
            if prior:
                hits.append((a-len(before)+prior.start(), b))
            elif following:
                hits.append((a, b+following.end()))
        return hits if len(hits) == 1 else None
    return None


def _recurrence_fact(text, ast, formulas, matches, function):
    """Bind explicit global domain, global identity, and separate local conditions."""
    if ast[0] == '=' and ast[1][:2] == ['call', 'Dom']:
        from .formula_surface import _real_spelling
        hits = []
        for first, second in pairwise(formulas):
            printed_set = _real_spelling(second[2]).strip()
            if (re.fullmatch(re.escape(function)+r'\([^()]+\)', first[2].strip())
                    and re.search(r'定义域(?:为|是)', text[first[1]:second[0]])
                    and (matches(printed_set, _text(ast[2]))
                         or ast[2] == ['real'] and printed_set == 'R')):
                # Plain R denotes the real set only in this explicit domain
                # position, never as a global replacement of a parameter R.
                hits.append((first[0], second[1]))
        return hits if len(hits) == 1 else None
    if ast[0] != 'quantifier' or ast[1] != '∀':
        return None
    member = _text(['∈', ['name', ast[2]], ast[3]])
    def body_matches(body):
        # The quantifier binds a real scalar, so x(x-c) is juxtaposed
        # multiplication here; it cannot introduce a function named x.
        body = re.sub(r'(?<![A-Za-z0-9_])'+re.escape(ast[2])+r'\s*(?=\()', ast[2]+'*', body)
        return matches(body, _text(ast[4]))
    bodies = [(a, b) for a, b, body in formulas if body_matches(body)]
    if len(bodies) != 1:
        return None
    body_start, body_end = bodies[0]
    members = [(a, b) for a, b, body in formulas
               if matches(re.sub(r'\\forall|∀', '', body).strip(), member) and b < body_start]
    if len(members) == 1:
        a, b = members[0]
        # A stated local formula uses “当...时”; the requested prefix must
        # explicitly quantify all its inputs. Never promote an existential.
        words = r'当|任意|每个' if ast[4][0] == '=' else r'任意|每个'
        if re.search(words+r'[^。；;$]{0,12}\$?$', text[max(0, a-20):a]) or re.search(r'\\forall|∀', text[a:b]):
            return [(a, b), (body_start, body_end)]
    # Ordinary “satisfies f(x+L)=Kf(x)” states an identity on the explicitly
    # declared real domain, not a local formula with an omitted restriction.
    if ast[3] == ['real'] and ast[4][0] == '=' and re.search(
            r'(?:满足|且有)\s*\$?$', text[max(0, body_start-12):body_start]):
        return bodies
    return None


def source_spans(candidate, target_ref, ranges, description, matches):
    text = candidate['original_text']
    original_matches = matches
    def matches(body, expected):
        # x_1 and x1 denote the same indexed source variable; this is naming,
        # not an algebraic rewrite or a change to quantifier order.
        index = lambda s: re.sub(r'([A-Za-z])_\{?(\d+)\}?', r'\1\2', s)
        body, expected = index(body), index(expected)
        builder = re.fullmatch(r'\s*([A-Za-z])\s*=\s*\\\{\s*([A-Za-z])\s*\\mid\s*(.*?)\s*\\\}\s*', body)
        if builder:
            from .surface_math import normalize_surface
            try:
                adapted = builder[1]+'={'+builder[2]+'∈ℝ | '+normalize_surface(builder[3]).text+'}'
                return parse(adapted) == parse(expected)
            except ValueError:
                return False
        return original_matches(body, expected)
    formulas = source_formulas(text, ranges)
    expanded = []
    for a, b, body in formulas:
        # A trailing parenthesized parameter condition is a separate given,
        # e.g. g(x)=kx+5-2k(k>0). Only split a complete terminal relation.
        suffix = re.search(r'[（(]([^()（）]+)[)）]\s*$', body)
        if suffix and re.search(r'[<>≤≥]|\\(?:ge|le|gt|lt)', suffix[1]):
            expanded.extend([(a, a+suffix.start(), body[:suffix.start()]),
                             (a+suffix.start(1), a+suffix.end(1), suffix[1])])
        else:
            expanded.append((a, b, body))
    formulas = expanded
    rows = []
    for source in description['given_definitions']:
        found = [f for f in formulas if matches(f[2], source['expression'])
                 or _piecewise_source_matches(f[2], source['expression'], matches)]
        spans = [found[0][:2]] if len(found) == 1 else _natural_fact(text, parse(source['expression']), formulas, matches)
        if not spans and description['task'] == 'recurrence':
            spans = _recurrence_fact(text, parse(source['expression']), formulas, matches, description['function'])
        if not spans and description['task'] == 'direct':
            from ...problem_understanding.notation_parser import definition
            ast = parse(source['expression'])
            fn = next(definition(r['expression']) for r in description['given_definitions']
                      if definition(r['expression'])[:2] == ['function_definition', description['function']])
            if ast[:2] == ['∈', ['name', fn[2]]]:
                hits = [f for f in formulas if matches(f[2], _text(ast[2]))
                        and re.search(r'(?:在|区间)\s*\$?$', text[max(0, f[0]-8):f[0]])]
                spans = [hits[0][:2]] if len(hits) == 1 else None
        if not spans:
            return None
        rows.extend((a, b, 'given_domain' if 'Dom(' in source['expression'] else 'relation', [source['source_ref']]) for a, b in spans)
    goal = description['source']
    if description['task'] == 'recurrence':
        found = [(a, b) for a, b, body in formulas if matches(body, description['parameter'])
                 and re.match(r'\$?\s*的最大值', text[b:])]
        if len(found) != 1:
            return None
    elif description['task'] == 'direct':
        label = '最大值' if description['quantity'] == 'maximum' else '最小值'
        found = [(start+m.start(), start+m.end()) for start, end in ranges for m in re.finditer(label, text[start:end])]
        if len(found) != 1:
            return None
        if 'input_domain' in goal:
            # The independent variable is source-bound, not assumed to be x.
            from ...problem_understanding.notation_parser import definition
            fn = next(definition(r['expression']) for r in description['given_definitions']
                      if definition(r['expression'])[:2] == ['function_definition', goal['object']])
            spans = [f for f in formulas if matches(f[2], fn[2]+'∈'+goal['input_domain'])]
            if not spans:
                spans = [f for f in formulas if matches(f[2], goal['input_domain'])
                         and re.search(r'(?:在|区间)\s*\$?$', text[max(0, f[0]-8):f[0]])]
            if len(spans) != 1:
                return None
            rows.append((*spans[0][:2], 'given_domain', [target_ref]))
    else:
        symbol = re.escape(description['parameter'])
        found = [(start+m.start(), start+m.end()) for start, end in ranges
                 for m in re.finditer(r'(?:求|则)(?:实数|参数)?\s*\$?'+symbol+r'\$?\s*(?:的)?(?:取值)?范围', text[start:end])]
        if len(found) != 1:
            return None
    rows.append((*found[0], 'goal', [target_ref]))
    return rows
