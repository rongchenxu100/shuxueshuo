"""Output ranges on aligned number lines, with the union hidden until confirmed."""

from copy import deepcopy
from hashlib import sha256

import sympy as sp

from ..piecewise_range import endpoint_witnesses
from . import interaction_graphs as drawing
from .domain_visuals import exact_math
from .evaluation_presentation import _lines
from .math_values import latex
from .range_presentation import _card, _image_choices
from .trajectory import decode_value


def union_view(values):
    rows, answer = values['branch_results'], values['feasible_set']
    images = [row['image'] for row in rows]
    interaction, expected = _image_choices(answer, sp.Intersection(*images))
    proof = [r'R=' + r'\cup'.join(latex(image) for image in images) + '=' + latex(answer)]
    # Legal input witnesses explain why a closed output boundary survives even
    # when another piece has an open input endpoint at the same output height.
    for check in endpoint_witnesses(values['description'], answer)['points']:
        if check['included']:
            witness = check['evidence']['legal_preimages'][0]
            point = check['point']['latex']
            proof.append(rf'\text{{第{witness["branch"]}段}}:\quad '
                         rf'{values["description"]["function_name"]}({witness["input"]["latex"]})={point}\Rightarrow {point}\in R')
    return _card('合并各段值域',
                 '这里的数轴表示函数值 y。只要任意一段能取到，就属于函数的值域。把各段值域合起来，结果是什么？',
                 '各段能取到的函数值',
                 _lines([rf'R_{{{row["branch"]["index"]}}}={latex(row["image"])}' for row in rows]),
                 '整个函数的值域', rf'R={latex(answer)}',
                 '$$'+_lines(proof)+'$$', interaction, expected)


def presentation(values):
    view = union_view(values)
    left, right = view['derivation']['items']
    return {'formula_title': view['title'], 'formula_explanation': view['explanation'],
            'derivation_caption': view['title'], 'derivation_left_label': left['label'],
            'derivation_left_math': left['math'], 'derivation_left_note': '',
            'derivation_right_label': right['label'], 'derivation_right_math': right['math']}


def _output_lines(rows, answer):
    """The existing exact number-line component supports labels and shared bounds."""
    sets = [*(row['image'] for row in rows), answer]
    pieces = [drawing._pieces(value) for value in sets]
    ends = sorted({point for intervals, points in pieces
                   for point in [*points, *(v for interval in intervals for v in (interval.start, interval.end) if v.is_finite)]})
    low, high = (drawing._float(ends[0]), drawing._float(ends[-1])) if ends else (-1.0, 1.0)
    pad = max((high-low)*0.25, 0.75)
    ticks = [{'at': drawing._float(p), 'label': drawing.short_label(p), 'exact': exact_math(p)} for p in ends]
    labels = [*(rf'\text{{第{row["branch"]["index"]}段值域}}:\quad R_{{{row["branch"]["index"]}}}={latex(row["image"])}' for row in rows),
              rf'\text{{整个函数的值域}}:\quad R={latex(answer)}']
    return [{'variable': 'y', 'label': label, 'bounds': [low-pad, high+pad],
             'intervals': [{'left': drawing._float(p.start) if p.start.is_finite else None,
                            'right': drawing._float(p.end) if p.end.is_finite else None,
                            'left_closed': not p.left_open, 'right_closed': not p.right_open,
                            'exact': exact_math(p)} for p in intervals],
             'points': [{'at': drawing._float(p), 'label': drawing.short_label(p), 'exact': exact_math(p)} for p in points],
             'ticks': deepcopy(ticks), 'exact_set': exact_math(value)}
            for label, value, (intervals, points) in zip(labels, sets, pieces, strict=True)]


def compile_union(seeds, interaction_id):
    (seed,) = seeds
    values = decode_value(seed['values'])
    view = union_view(values)
    board = deepcopy(view['derivation'])
    board['items'][1]['math'] = None
    interaction = deepcopy(view['interaction'])
    interaction['options'].sort(key=lambda row: sha256(f'{interaction_id}:{row["value"]}'.encode()).digest())
    lines = _output_lines(values['branch_results'], values['feasible_set'])
    return {'parts': [{'id': interaction_id+'#1', 'title': view['title'], 'question': view['question'],
                       'interaction': interaction, 'expected_answer': view['expected_answer'],
                       'feedback': view['feedback'], 'submit_label': '确认值域',
                       'stem_board': board, 'completion_board': view['derivation'],
                       'condition_number_lines': lines[:-1], 'completion_number_line': lines[-1]}],
            'diagnostics': []}
