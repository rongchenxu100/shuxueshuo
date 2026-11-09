"""Bounded original-source matching for forward function requests."""

import re
from fractions import Fraction

from ...problem_understanding.notation_parser import NotationError, definition, parse
from ...problem_understanding.review_contract import pointer
from .surface_math import normalize_surface


def _number(tree):
    if tree[0] == 'number':
        return Fraction(tree[1])
    if tree[0] == 'neg':
        return -_number(tree[1])
    a, b = _number(tree[1]), _number(tree[2])
    if tree[0] == '^' and (b.denominator != 1 or b not in (0, 1, 2) or (a == 0 and b == 0)):
        raise ValueError('unproved numeric power')
    return {'+': lambda: a+b, '-': lambda: a-b, '*': lambda: a*b,
            '/': lambda: a/b, '^': lambda: a ** int(b)}[tree[0]]()


def _term_text(expression, index=None, number=None):
    def render(tree):
        if tree == ['name', index]:
            return str(number)
        if tree[0] == 'number' or tree[0] == 'name':
            return tree[1]
        if tree[0] == 'call':
            return tree[1] + '(' + ','.join(render(child) for child in tree[2:]) + ')'
        children = [render(child) for child in tree[1:]]
        text = ('-(' + children[0] + ')' if tree[0] == 'neg'
                else '(' + children[0] + ')' + tree[0] + '(' + children[1] + ')')
        try:
            return str(_number(parse(text)))
        except (KeyError, ValueError, TypeError, IndexError, ZeroDivisionError):
            return text
    return render(parse(expression))


def sum_source_matches(body, terms, matches):
    """Ellipses may omit only a contiguous block of the exact requested sequence."""
    body = re.sub(r'\\(?:left|right|,|;|!)', '', body)
    body = re.sub(r'\\(?:cdots|ldots|dots)|⋯|…|\.{3}', '…', body)
    parts, start, depth = [], 0, 0
    for offset, char in enumerate(body):
        depth += char in '({['
        depth -= char in ')}]'
        if depth < 0:
            return False
        if char == '+' and depth == 0:
            parts.append(body[start:offset].strip())
            start = offset+1
    parts.append(body[start:].strip())
    if depth or not parts or parts[0] == '…' or parts[-1] == '…':
        return False
    expanded = []
    for part in parts:
        indexed = re.fullmatch(r'\\sum_\{([A-Za-z][A-Za-z0-9_]*)\s*=\s*(-?\d+)\}'
                               r'\^\{(-?\d+)\}\s*(.+)', part)
        if indexed:
            index, lower, upper, term = indexed.groups()
            lower, upper = int(lower), int(upper)
            if max(abs(lower), abs(upper)) > 10000 or len(expanded)+max(0, upper-lower+1) > 4096:
                return False
            try:
                # Instantiate both sides through the same arithmetic-only
                # adapter. It never cancels symbolic denominators, and an
                # undefined numeric input remains an intact original tree.
                expression = normalize_surface(term).text
                expanded.extend(_term_text(expression, index, value)
                                for value in range(lower, upper+1))
            except (NotationError, ValueError, TypeError, IndexError, ZeroDivisionError):
                return False
        else:
            expanded.append(part)
    parts = expanded
    expected = []
    for term in terms:
        if 'index' in term:
            count = max(0, term['upper'] - term['lower'] + 1)
            if len(expected) + count > 4096:
                return False
            expected.extend(_term_text(term['expression'], term['index'], value)
                            for value in range(term['lower'], term['upper']+1))
        else:
            expected.append(_term_text(term['expression']))
    positions = {0}
    for part in parts:
        if part == '…':
            positions = {next_pos for pos in positions for next_pos in range(pos+1, len(expected))}
        else:
            positions = {pos+1 for pos in positions if pos < len(expected) and matches(part, expected[pos])}
        if not positions:
            return False
    return len(expected) in positions


def _formula_parts(body, start):
    r"""Split a display list only at explicit, ungrouped punctuation.

    Keep exact original offsets and leave arithmetic/call/set subexpressions
    intact. In particular, TeX spacing commands (``\,``/``\;``) are not list
    separators, and a function call inside another expression cannot become
    a standalone task merely by sharing its text.
    """
    if r'\begin{cases}' in body:
        return [(start, start + len(body), body)]
    depth, previous, boundaries = 0, 0, []
    for offset, char in enumerate(body):
        if char in '({[（':
            depth += 1
        elif char in ')}]）':
            depth -= 1
            if depth < 0:
                return [(start, start + len(body), body)]
        elif depth == 0 and char in ',，;；、' and (offset == 0 or body[offset-1] != '\\'):
            boundaries.append((previous, offset))
            previous = offset + 1
    if depth:
        return [(start, start + len(body), body)]
    boundaries.append((previous, len(body)))
    return [(start + begin, start + end, body[begin:end])
            for begin, end in boundaries if body[begin:end].strip()]


def _source_notation(ast):
    if ast[0] in ('name', 'number'):
        return ast[1]
    if ast[0] == 'call':
        return ast[1] + '(' + ','.join(_source_notation(child) for child in ast[2:]) + ')'
    if ast[0] == 'neg':
        return '-(' + _source_notation(ast[1]) + ')'
    op = {'and': '∧', 'or': '∨'}.get(ast[0], ast[0])
    return op.join('(' + _source_notation(child) + ')' for child in ast[1:])


def _piecewise_source_matches(body, source, matches):
    """Match each original cases row, including strictness; never infer a missing row."""
    try:
        expected = definition(source)
        if expected[0] != 'function_definition' or expected[3][:2] != ['call', 'piecewise']:
            return False
        displayed = re.fullmatch(r'\s*(.+?)=\s*\\begin\{cases\}(.*?)\\end\{cases\}\s*', body, re.DOTALL)
        if not displayed or not matches(displayed[1], f'{expected[1]}({expected[2]})'):
            return False
        rows = re.split(r'\\\\', displayed[2])
        args = expected[3][2:]
        if len(rows) * 2 != len(args):
            return False
        for index, row in enumerate(rows):
            # A printed cases row may use punctuation instead of a TeX column.
            # Reuse the grouped splitter so commas in calls/sets and spacing
            # commands cannot become expression/condition boundaries.
            cells = row.split('&') if '&' in row else [part[2] for part in _formula_parts(row, 0)]
            if len(cells) != 2 or not all(
                matches(cell.strip().strip(',，;；'), _source_notation(args[2*index + column]))
                for column, cell in enumerate(cells)
            ):
                return False
        return True
    except (NotationError, ValueError, IndexError, TypeError):
        return False


def range_goal_span(text, formulas, variable, relation, matches):
    """Bind a variable range ask, or 'this inequality's solution set'."""
    for a, b, body in formulas:
        if matches(body, variable) and re.match(
                r'\s*(?:值?的(?:取值(?:范围|集合)|范围|解集(?:合)?)|取值(?:范围|集合)是)', text[b+1:]):
            return a, b
        if relation and matches(body, relation):
            ask = re.match(r'\s*的解集(?:合)?', text[b+1:])
            if ask:
                return b+1, b+1+ask.end()
    return None


def evaluation_source_spans(candidate, target_ref, ranges, description, matches):
    text, goal = candidate['original_text'], pointer(candidate, target_ref)
    formulas = [part for begin, end in ranges
                for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
                for part in _formula_parts(m[1], begin+m.start(1))]
    spans = []
    for function in description['functions']:
        source = pointer(candidate, function['source_ref'])
        located = [(start, end) for start, end, body in formulas
                   if matches(body, source) or _piecewise_source_matches(body, source, matches)]
        if not located:
            return None
        spans.append((*located[0], 'expression', [function['source_ref']]))
        if function.get('explicit_domain'):
            source_ref = function['input_domain_source_ref']
            domain_fact = pointer(candidate, source_ref)
            fact = parse(domain_fact)
            domain_text = domain_fact.split('=', 1)[1].strip()
            if fact[1][:2] != ['call', 'Dom']:
                domain_text = domain_fact.split('=', 1)[0].strip()
            domain_spans = [(start, end) for start, end, body in formulas if matches(body, domain_fact)]
            for offset, (start, end, body) in enumerate(formulas[:-1]):
                next_start, next_end, next_body = formulas[offset+1]
                # The immediately preceding call/definition identifies whose
                # complete domain the following range states.
                named = re.match(r'^\s*' + re.escape(function['function_name']) + r'\s*\(', body)
                if (named and re.search(r'定义域(?:是|为|恰为)?', text[end:next_start])
                        and matches(next_body, domain_text)):
                    domain_spans.append((start, next_end))
            if not domain_spans:
                return None
            spans.append((*domain_spans[0], 'expression', [source_ref]))
    if 'input_domain' in goal:
        variable = description.get('variable')
        if not variable:
            return None
        domain_spans = [(start, end) for start, end, body in formulas
                        if matches(body, f"{variable}∈{goal['input_domain']}")]
        if not domain_spans:
            return None
        spans.append((*domain_spans[0], 'expression', [f'{target_ref}/input_domain']))
    located = []
    for start, end, body in formulas:
        # A printed answer blank is a request, not a supplied equality/value.
        blank = re.fullmatch(r'(.*?)=\s*(?:_{2,}|\\underline\{(?:\s|\\quad|\\qquad)+\})\s*', body)
        if not blank and re.match(r'\s*_{2,}', text[end+1:]):
            blank = re.fullmatch(r'(.*?)=\s*', body)
        if blank:
            body = blank[1].rstrip()
            end = start + len(body)
        if goal['kind'] == 'finite_sum':
            equal = sum_source_matches(body, goal['terms'], matches)
        else:
            # TeX permits a single numeric atom without braces (\sqrt2).
            # Match its grouped spelling while retaining the original span.
            grouped = re.sub(r'\\sqrt\s*(\d)(?!\d)', lambda m: r'\sqrt{' + m[1] + '}', body)
            equal = matches(grouped, goal['expression'])
        if equal:
            located.append((start, end))
    if not located:
        return None
    # A repeated occurrence is not ambiguous about its identical task, but a
    # check_constant target must retain its explicit question rather than mere evidence.
    if goal['kind'] == 'check_constant' and not any(
            re.search(r'是否|判断|定值|常数', text[max(0, start-10):end+15]) for start, end in located):
        return None
    spans.append((*located[-1], 'goal', [target_ref]))
    return spans
