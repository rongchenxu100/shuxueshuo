"""Bind requested answer conversions to explicit clauses in the original text."""

import re

QUANTITY_WORDS = {'minimum': '最小值', 'maximum': '最大值', 'infimum': '下确界', 'supremum': '上确界'}


def request_spans(text, ranges, formulas, request, target_ref, matches):
    """Bind answer semantics to the actual question, independently of methods."""
    ref = target_ref + '/answer_request'
    kind = request['kind']
    if kind in ('identity', 'extremum'):
        word = '值域' if kind == 'identity' else QUANTITY_WORDS[request['quantity']]
        hits = []
        for a, b in ranges:
            for match in re.finditer(word, text[a:b]):
                start, end = a+match.start(), a+match.end()
                prefix = re.split(r'[，,；;。\n]', text[a:start])[-1]
                suffix = re.split(r'[，,；;。\n]', text[end:b])[0]
                # A named extremum in the givens is not the requested answer;
                # a question about a comparison or arithmetic is not identity.
                if re.search(r'是否|是不是|的[和差积商]|之[和差积商]', prefix+suffix) or re.match(r'\s*[与和]', suffix):
                    continue
                requested = re.search(r'求|计算|确定', prefix) and not re.match(r'\s*(?:为|是)\s*\$', suffix)
                blank = re.fullmatch(r'\s*(?:为|是|=)?\s*(?:[_＿]{2,}|[（(]\s*[）)]|[?？])\s*', suffix)
                if requested or blank:
                    hits.append((start, end, 'goal', [ref]))
        return hits if len(hits) == 1 else None
    if kind == 'compare_set':
        words = r'值域是否(?:为|等于|是)?' if request['relation'] == 'equal' else r'值域是否(?:不等于|不是)'
        hits = [(a, b, 'goal', [ref]) for a, b, formula in formulas
                if matches(formula, request['expected'])
                and re.search(words + r'\s*\$?\s*$', text[max(0, a-24):a])]
        return hits if len(hits) == 1 else None
    if kind != 'expression':
        return None
    bindings, hits = request['bindings'], []
    for index, row in enumerate(bindings):
        word = QUANTITY_WORDS[row['quantity']]
        located = [(a, b, 'expression', [f'{ref}/bindings/{index}']) for a, b, formula in formulas
                   if matches(formula, row['symbol'])
                   and re.search(word + r'\s*(?:为|是|等于)?\s*\$?\s*$', text[max(0, a-24):a])]
        if len(located) != 1:
            hits = []
            break
        hits.extend(located)
    targets = [(a, b, 'goal', [ref+'/expression']) for a, b, formula in formulas
               if matches(re.sub(r'\s*=\s*$', '', formula), request['expression'])
               and not any(a == row[0] and b == row[1] for row in hits)]
    if len(hits) == len(bindings) and len(targets) == 1:
        return [*hits, *targets]
    # Explicitly supported worded arithmetic; local binding names need not
    # appear in the question, but operation and operand order must agree.
    if len(bindings) == 2:
        first, second = bindings
        for operator, noun in (('+', '和'), ('-', '差'), ('*', '积'), ('/', '商')):
            if not matches(request['expression'], first['symbol'] + operator + second['symbol']):
                continue
            pattern = QUANTITY_WORDS[first['quantity']] + r'\s*(?:与|和)\s*' + QUANTITY_WORDS[second['quantity']] + r'\s*(?:的|之)' + noun
            located = [(a+m.start(), a+m.end(), 'goal', [ref]) for a, b in ranges for m in re.finditer(pattern, text[a:b])]
            if len(located) == 1:
                return located
    return None


def task_spans(text, ranges, formulas, task, target_ref, matches):
    found = []

    def formula_after(words, expected, ref):
        for start, end, body in formulas:
            for begin, stop in ranges:
                if not begin <= start < end <= stop:
                    continue
                prefix = text[max(begin, start-24):start].rstrip('$ ')
                if re.search(words + r'\s*(?:为|是|等于)?\s*$', prefix) and matches(body, expected):
                    found.append((start, end, 'expression', [ref]))
                    return True
        return False

    if task['kind'] == 'select_range_domain':
        if not formula_after('定义域', task['domain_template'], target_ref+'/domain_template'):
            return None
        if not formula_after('值域', task['expected_range'], target_ref+'/expected_range'):
            return None
        words = r'不可能|不能|不可以' if task['select_relation'] == 'differs' else r'(?<!不)可能|(?<!不)可以'
        locations = [(begin+m.start(), begin+m.end()) for begin, end in ranges
                     for m in re.finditer(words, text[begin:end])]
        if len(locations) != 1:
            return None
        found.append((*locations[0], 'goal', [target_ref]))
        return found
    for index, row in enumerate(task['extrema']):
        role = '最大值' if row['kind'] == 'maximum' else '最小值'
        if not formula_after(role, row['symbol'], f'{target_ref}/extrema/{index}'):
            return None
    located = [(start, end) for start, end, body in formulas
               if matches(re.sub(r'\s*=\s*$', '', body), task['expression'])]
    if len(located) != 1:
        return None
    found.append((*located[0], 'goal', [target_ref]))
    return found
