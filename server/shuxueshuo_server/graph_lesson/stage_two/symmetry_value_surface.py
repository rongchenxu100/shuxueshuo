"""Bind parity, an optional one-sided rule or identity, given value equations and the value target to source text."""
import re

from ...problem_understanding.review_contract import pointer
from ..parity_extension_math import region
from .evaluation_surface import _formula_parts
from .parity_extension_surface import (
    _domain,
    _range,
    _same,
    _sibling_goals,
    parity_spans,
)


def source_spans(candidate, target_ref, ranges, desc):
    text = candidate['original_text']
    formulas = [part for begin, end in ranges for m in re.finditer(r'\$([^$\n]+)\$', text[begin:end])
                for part in _formula_parts(m[1], begin + m.start(1))]
    goal = desc['source']

    def asked(part):
        body = part[2].rstrip()
        if body.endswith('='):
            return _same(body[:-1], goal['expression'], desc) and bool(re.match(r'\s*\$\s*[_＿]', text[part[1]:]))
        return (_same(body, goal['expression'], desc)
                and bool(re.match(r'\s*\$\s*的值(?:为|是)\s*[_＿]', text[part[1]:])))

    targets = [part for part in formulas if asked(part)]
    if len(targets) != 1:
        return None
    target = targets[0]
    rows = [(target, 'goal', [target_ref])]
    first = target[0]

    def unused(part):
        return part[1] < target[0] and all(part != used for used, *_ in rows)

    if desc['rule_ast'] is not None:
        relations = [part for part in formulas if part[1] < target[0] and _same(part[2], goal['relation'], desc)]
        if len(relations) != 1:
            return None
        relation = relations[0]
        known = [part for part in formulas if part[1] < relation[0]
                 and re.search(r'(?:当|且)\s*\$\s*$', text[:part[0]]) and re.match(r'\s*\$\s*时', text[part[1]:])
                 and _range(part[2], desc['variable']) == region(desc['rule_domain_ast'])]
        if len(known) != 1:
            return None
        rows += [(known[0], 'condition', [target_ref + '/relation_domain']),
                 (relation, 'expression', [target_ref + '/relation'])]
        first = known[0][0]
    for identity in desc['identities']:
        printed = (goal['relation'] if identity['source_ref'] == target_ref + '/relation'
                   else re.sub(r'^\s*∀[^:]*:', '', pointer(candidate, identity['source_ref'])))
        found = [part for part in formulas if unused(part) and _same(part[2], printed, desc)]
        bound = re.match(r'^\s*∀\s*([A-Za-z]\w*)', pointer(candidate, identity['source_ref']))
        if bound:
            scoped = []
            for part in found:
                preceding = [p for p in formulas if p[1] < part[0]]
                if preceding and _range(preceding[-1][2], bound[1]) == region(identity['domain_ast']):
                    scoped.append(part)
            if scoped:
                found = scoped
        if len(found) != 1:
            return None
        rows.append((found[0], 'condition', [identity['source_ref']]))
        first = min(first, found[0][0])
        if bound:
            # “对任意实数 $x$ 都有 …” names the quantified variable; “实数” must match the stated range.
            quantified = [part for part in formulas if unused(part) and part[1] < found[0][0]
                          and part[2].strip() == bound[1]
                          and re.search(r'(?:任意|一切|所有|任何)(?:的)?(实数)?\s*\$\s*$', text[:part[0]])]
            for part in quantified:
                said_real = re.search(r'实数\s*\$\s*$', text[:part[0]])
                if said_real and region(identity['domain_ast']) != region(['real']):
                    return None
                rows.append((part, 'condition', [identity['source_ref']]))
            # A local identity may use an explicit non-symmetric range. Bind that
            # range to the equality instead of silently treating it as global.
            preceding = [p for p in formulas if p[1] < found[0][0]]
            scope = preceding[-1] if preceding else None
            if scope is not None and _range(scope[2], bound[1]) == region(identity['domain_ast']):
                if (re.search(r'(?:当|且|任意|一切|所有|任何)(?:的)?\s*\$\s*$', text[:scope[0]])
                        and re.match(r'\s*\$\s*(?:时|都有|均有|有)', text[scope[1]:])):
                    rows.append((scope, 'condition', [identity['source_ref']]))
            elif region(identity['domain_ast']) != region(['real']):
                return None
    for row in desc['value_equations']:
        printed = pointer(candidate, row['source_ref'])
        found = [part for part in formulas if unused(part) and _same(part[2], printed, desc)]
        if len(found) != 1:
            return None
        rows.append((found[0], 'condition', [row['source_ref']]))
        first = min(first, found[0][0])
    abstract = desc['domain_ast'] is None

    def same_domain(body):
        if desc.get('parameter'):
            printed = pointer(candidate, desc['domain_source_refs'][0]).split('=', 1)[1]
            return _same(body, printed, desc)
        return _domain(body) == region(desc['domain_ast'])

    domains = [part for part in formulas if re.search(r'(?:定义在|定义域(?:都|均)?(?:为|是))\s*\$\s*$', text[:part[0]])
               and (abstract or same_domain(part[2]))]
    calls = {f"{F['name']}({desc['variable']})" for F in desc['functions']}
    intros = [part for part in formulas if part[1] <= first
              and any(_same(re.sub(r'^\s*y\s*=', '', part[2]), call, desc) for call in calls)
              and re.search(r'(?:函数|设|已知|[，,、和与])\s*\$\s*$', text[:part[0]])]
    properties = parity_spans(text, ranges, intros, desc['functions'], desc)
    if len(domains) != (0 if abstract else 1) or properties is None:
        return None
    rows += properties
    rows += [*((part, 'given_domain', list(desc['domain_source_refs'])) for part in domains),
             *((part, 'expression', [target_ref]) for part in intros)]
    covered = {(part[0], part[1]) for part, *_ in rows}
    siblings = _sibling_goals(candidate, target_ref)

    def sibling_owned(part):
        slot = re.match(r'\s*\$\s*[_＿]', text[part[1]:]) and part[1] < target[0]
        return siblings and (slot or part[0] > target[1])

    if any((part[0], part[1]) not in covered and not sibling_owned(part) for part in formulas):
        return None
    return [(part[0], part[1], kind, refs) for part, kind, refs in sorted(rows, key=lambda row: row[0][0])]
