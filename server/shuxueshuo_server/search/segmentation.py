"""Split a photographed worksheet page into question regions from OCR text lines.

Pure Python so it can run (and be tested) without Paddle. Input is the OCR
worker reply: page size plus text lines (quadrilateral, recognised head text)
and layout boxes, all normalised to 0..1.

Rules, in order:
1. Deskew: estimate the page angle from long lines and rotate everything level.
2. Question starts: the leftmost piece of a row whose head is a question number
   (``10.``、``11、``、``14．``, or a bare ``15`` followed by text on the same row).
   Textbook titles (``【例11】``、``【变式1】``) keep their own labels and numbering.
   ``（1）`` sub-questions never start a question; ``三、解答题`` headers end one.
3. Columns: cluster start x positions; keep only the numbering chain that reads
   1→2→3 in column order (gaps of up to two, restarts after a section header),
   which drops stray handwritten digits.
4. Regions: a question owns the lines below its start up to the next start or
   header or worked-solution heading in its column; the last question in a
   column stops at a large gap.
   Figures from the layout model join the question they sit under.

Boxes err large: stage one re-reads the crop, so an extra half line from a
neighbour is harmless while a missing condition is not.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from itertools import pairwise
from statistics import median

from .segmentation_labels import numbered_stem, solution_heading, textbook_title
from .segmentation_numbering import gap_number_hint

NUMBER = re.compile(r"^\s*(\d{1,2})\s*([.．、。,，:：)）])?\s*(.?)")
SECTION = re.compile(r"^\s*(?:[一二三四五六七八九十]{1,3}\s*[、.．]|第\s*[一二三四五六七八九十百0-9]+\s*[章节])")
FORMULA_FOLLOW = re.compile(r"[\dA-Za-z+\-−<>=^/*≤≥≠|()（）{}\[\]]")
FIGURE_LABELS = {"image", "figure", "chart", "seal"}
MAX_STEP = 3
SECTION_RESTART = 2
# The layout model sometimes labels the whole photographed sheet as one image.
MAX_FIGURE_AREA = 0.4
DIGIT_HEAD = re.compile(r"^\s*\d")


@dataclass
class Item:
    x0: float
    y0: float
    x1: float
    y1: float
    head: str = ""
    figure: bool = False

    @property
    def h(self):
        return self.y1 - self.y0

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2


@dataclass
class Start:
    item: Item
    number: int
    column: int = -1
    kind: str = "number"
    label: str = ""


@dataclass
class _Section:
    cy: float
    column: int
    y1: float = 0.0


@dataclass
class Segmentation:
    regions: list[dict]
    mode: str
    diagnostics: dict = field(default_factory=dict)


def _rows_overlap(a, b):
    return min(a.y1, b.y1) - max(a.y0, b.y0) > 0.5 * min(a.h, b.h)


def head_candidates(boxes, median_h=None, *, text_regions=()):
    """Indices of boxes that start their row, i.e. nothing sits just to their left.

    The OCR worker recognises only these heads; continuations never start a question.
    ``boxes`` are (x0, y0, x1, y1) in any consistent unit.
    """
    items = [Item(*b) for b in boxes]
    if not items:
        return []
    mh = median_h or median(i.h for i in items)
    # Only broad text regions can identify a separate sheet/column. Per-line
    # text and formula boxes must not turn continuations into new row heads.
    bodies = [Item(*b) for b in text_regions if b[2] - b[0] >= 4 * mh and b[3] - b[1] >= 3 * mh]
    paragraphs = [Item(*b) for b in text_regions if b[2] - b[0] >= 8 * mh and b[3] - b[1] >= mh]

    def separate_body(item, other):
        for body in bodies:
            inside = (body.x0 <= (item.x0 + item.x1) / 2 <= body.x1
                      and body.y0 <= item.cy <= body.y1 and body.x0 <= item.x0)
            # Layout may find only one paragraph on a curved photographed
            # page. Its column edges also identify aligned, similarly wide
            # sibling rows. A neighbouring sheet must not hide their heads.
            aligned = (abs(item.x0 - body.x0) <= 0.5 * mh and item.x1 - item.x0 >= 4 * mh
                       and abs(item.x1 - body.x1) <= 2 * mh)
            if other.x1 < min(body.x0, item.x0) and (inside or aligned):
                return True
        # Curved book pages may have only shallow paragraph boxes. Several
        # independent paragraphs can establish a margin even when a short
        # title above them is obscured by a fragment of the facing page.
        anchors = [body for body in paragraphs if abs(item.x0 - body.x0) <= 2 * mh]
        return (item.x1 - item.x0 >= 4 * mh and len(anchors) >= 3
                and max(body.y0 for body in anchors) - min(body.y1 for body in anchors) >= 3 * mh
                and other.x0 < min(body.x0 for body in anchors) - 2 * mh
                and other.x1 < item.x0 and other.x1 - other.x0 < 4 * mh)

    keep = []
    for i, item in enumerate(items):
        reach = 2 * max(item.h, mh)
        blocked = any(
            j != i and _rows_overlap(item, other) and other.x1 <= item.x0 + 0.3 * item.h
            and item.x0 - other.x1 < reach
            and not separate_body(item, other)
            for j, other in enumerate(items))
        if not blocked:
            keep.append(i)
    return keep


def _angle(lines, width, height):
    """Median top-edge angle of long lines, in radians; small angles only."""
    angles = []
    for line in lines:
        poly = line.get("poly")
        if not poly or len(poly) != 4:
            continue
        (ax, ay), (bx, by) = (poly[0][0] * width, poly[0][1] * height), (poly[1][0] * width, poly[1][1] * height)
        dx, dy = bx - ax, by - ay
        side = math.hypot(poly[3][0] * width - ax, poly[3][1] * height - ay)
        if dx > 4 * max(side, 1):
            angles.append(math.atan2(dy, dx))
    if len(angles) < 3:
        return 0.0
    angle = median(angles)
    return angle if abs(angle) <= math.radians(15) else 0.0


class _Frame:
    """Rotate page coordinates level around the page centre, and back."""

    def __init__(self, angle, width, height):
        self.cos, self.sin = math.cos(-angle), math.sin(-angle)
        self.cx, self.cy = width / 2, height / 2

    def level(self, x, y):
        dx, dy = x - self.cx, y - self.cy
        return self.cx + dx * self.cos - dy * self.sin, self.cy + dx * self.sin + dy * self.cos

    def page(self, x, y):
        dx, dy = x - self.cx, y - self.cy
        return self.cx + dx * self.cos + dy * self.sin, self.cy - dx * self.sin + dy * self.cos

    def item(self, points, **extra):
        level = [self.level(x, y) for x, y in points]
        xs, ys = [p[0] for p in level], [p[1] for p in level]
        return Item(min(xs), min(ys), max(xs), max(ys), **extra)


def _corners(box):
    x0, y0, x1, y1 = box
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def page_head_candidates(raw_lines, layout, width, height):
    """Shared deskew/layout filtering before OCR and after head recognition."""
    frame = _Frame(_angle(raw_lines, width, height), width, height)
    lines = [frame.item([(x * width, y * height) for x, y in
                         (line.get("poly") or _corners(line["box"]))]) for line in raw_lines]
    bodies = [frame.item([(x * width, y * height) for x, y in _corners(item["box"])])
              for item in layout if item.get("label") == "text"]
    return head_candidates([(line.x0, line.y0, line.x1, line.y1) for line in lines],
                           text_regions=[(body.x0, body.y0, body.x1, body.y1) for body in bodies])


def question_number(head, *, has_right_neighbour):
    """The question number this line head starts with, or None."""
    match = NUMBER.match(head or "")
    if not match:
        return None
    number, punct, follow = int(match.group(1)), match.group(2), match.group(3)
    if not 1 <= number <= 99:
        return None
    if punct in {".", "．"} and follow.isdigit():
        return None  # decimal such as 0.11
    if punct in {")", "）", ",", "，"} and follow and FORMULA_FOLLOW.match(follow):
        return None  # A formula fragment such as 1)2 or 1,2 is not a question.
    if punct is None:
        if follow and FORMULA_FOLLOW.match(follow):
            return None  # 2x+1, 4<4a ...
        if not follow and not has_right_neighbour:
            return None  # a lone digit is more likely handwriting
    return number


def _chain(starts, sections):
    """Longest numbering chain in reading order; restarts allowed after a section header."""
    if not starts:
        return []

    def header_between(a, b):
        return any(s.column == b.column and a.item.cy < s.cy < b.item.cy if a.column == b.column
                   else s.column == b.column and s.cy < b.item.cy
                   for s in sections)

    best = [1] * len(starts)
    prev = [-1] * len(starts)
    for j, b in enumerate(starts):
        for i in range(j):
            a = starts[i]
            step = b.number - a.number
            ok = (a.kind != "number" or b.kind != "number" or 1 <= step <= MAX_STEP
                  or (b.number <= SECTION_RESTART and header_between(a, b)))
            if ok and best[i] + 1 > best[j]:
                best[j], prev[j] = best[i] + 1, i
    j = max(range(len(starts)), key=lambda k: (best[k], -k))
    chain = []
    while j != -1:
        chain.append(starts[j])
        j = prev[j]
    return chain[::-1]


def _cluster_columns(xs, width):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    columns, current = [], [order[0]]
    for a, b in pairwise(order):
        if xs[b] - xs[a] > 0.2 * width:
            columns.append(current)
            current = []
        current.append(b)
    columns.append(current)
    labels = [0] * len(xs)
    for c, members in enumerate(columns):
        for i in members:
            labels[i] = c
    return labels, len(columns)


def segment(ocr) -> Segmentation:
    width, height = ocr["width"], ocr["height"]
    raw_lines = ocr.get("lines", [])
    frame = _Frame(_angle(raw_lines, width, height), width, height)
    lines = []
    for line in raw_lines:
        points = line.get("poly") or _corners(line["box"])
        lines.append(frame.item([(x * width, y * height) for x, y in points], head=line.get("head") or ""))
    figures = [frame.item([(x * width, y * height) for x, y in _corners(item["box"])], figure=True)
               for item in ocr.get("layout", []) if item.get("label") in FIGURE_LABELS
               and (item["box"][2] - item["box"][0]) * (item["box"][3] - item["box"][1]) < MAX_FIGURE_AREA]
    if not lines:
        return Segmentation([], "empty", {"reason": "no_text"})
    mh = median(line.h for line in lines)
    pad = 0.5 * mh
    # Detection at DETECT_SIDE ends line boxes about one character short on the right.
    tail = 1.5 * mh

    leftmost = set(page_head_candidates(raw_lines, ocr.get("layout", []), width, height))
    candidates, sections, solutions = [], [], []
    for i, line in enumerate(lines):
        if i not in leftmost:
            continue
        if SECTION.match(line.head):
            sections.append(line)
            continue
        if solution_heading(line.head):
            solutions.append(line)
            continue
        title = textbook_title(line.head)
        if title:
            candidates.append(Start(line, **title))
            continue
        right = any(other is not line and _rows_overlap(line, other) and 0 <= other.x0 - line.x1 < 2 * mh
                    for other in lines)
        number = question_number(line.head, has_right_neighbour=right)
        if number is not None and line.h >= 0.5 * mh:
            candidates.append(Start(line, number))

    diagnostics = {"angle_degrees": round(math.degrees(math.atan2(-frame.sin, frame.cos)), 2),
                   "median_line_height": round(mh, 1), "candidates": [s.number for s in candidates]}
    if not candidates:
        if solutions:
            return Segmentation([], "uncertain", {**diagnostics, "reason": "solution_without_question"})
        return _whole_content(lines, figures, frame, width, height, pad, tail, diagnostics)
    candidates = [start for start in candidates if not _isolated_number(start, lines, mh)]
    if not candidates:
        return Segmentation([], "uncertain", {**diagnostics, "reason": "isolated_number"})

    labels, _ = _cluster_columns([s.item.x0 for s in candidates], width)
    for start, label in zip(candidates, labels):
        start.column = label
    column_x = {}
    for start in candidates:
        column_x.setdefault(start.column, []).append(start.item.x0)
    headers = [_Section(s.cy, min(column_x, key=lambda c: abs(min(column_x[c]) - s.x0)), s.y1) for s in sections]
    ordered = sorted(candidates, key=lambda s: (s.column, s.item.cy))
    # Printed solution steps can themselves be numbered. They are not new
    # questions; another title, section or anchored question stem ends the block.
    ordered = [s for s in ordered if s.kind != "number" or not _inside_solution(s, candidates, sections, solutions, mh)]
    if not ordered:
        return Segmentation([], "uncertain", {**diagnostics, "reason": "solution_without_question"})
    chain = _chain(ordered, headers)
    diagnostics["chain"] = [s.number for s in chain]
    if not chain:
        return _whole_content(lines, figures, frame, width, height, pad, tail, diagnostics)
    chain, repaired = _repair_gaps(chain, [lines[i] for i in sorted(leftmost)], mh, solutions=solutions)
    if repaired:
        diagnostics["repaired"] = repaired
    used = sorted({s.column for s in chain})

    lefts = {c: min(s.item.x0 for s in chain if s.column == c) for c in used}
    regions = []
    for position, column in enumerate(used):
        left = lefts[column] - pad
        right_limit = lefts[used[position + 1]] - pad if position + 1 < len(used) else width
        in_column = [it for it in lines + figures if left - mh <= (it.x0 + it.x1) / 2 < right_limit]
        # Text starting right of the printed body is margin work or a neighbouring sheet, not the question.
        body_right = _body_right(in_column, lefts[column], mh)
        in_column = [it for it in in_column if it.figure or it.x0 < body_right]
        starts = sorted((s for s in chain if s.column == column), key=lambda s: s.item.cy)
        stops = sorted([s.item.y0 for s in starts[1:]] + [h.cy - 0.5 * mh for h in headers if h.column == column])
        boxes, bottoms = [], []
        for k, start in enumerate(starts):
            top_line = start.item
            next_stop = next((y for y in stops if y > top_line.cy), None)
            solution = next(iter(sorted((line for line in solutions
                                         if line.cy > top_line.cy and abs(line.x0 - top_line.x0) < 3 * mh
                                         and (next_stop is None or line.cy < next_stop)), key=lambda line: line.cy)), None)
            if solution:
                next_stop = solution.cy
            members = [it for it in in_column
                       if it.cy >= top_line.y0 - 0.3 * mh and (next_stop is None or it.cy < next_stop)
                       and it is not solution and it not in sections
                       and (it.figure or it.x1 > top_line.x0 - 0.25 * mh)
                       and not (it.figure and it.y0 < top_line.y0 - mh)]
            if next_stop is None:
                members = _until_gap(members, top_line, 4 * mh)
            members = [it for it in members if it.x1 <= right_limit + mh or it is top_line]
            x0 = min([it.x0 for it in members] + [top_line.x0]) - pad
            # Printed text never sits above its number line; marks there are handwriting.
            y0 = min([top_line.y0] + [it.y0 for it in members if it.figure
                                    or (start.kind != "number" and _rows_overlap(it, top_line))]) - pad
            right = max([it.x1 for it in members] + ([body_right] if body_right < math.inf else []))
            x1 = min(right + tail, right_limit)
            y1 = max(it.y1 for it in members) + pad
            if solution:
                # OCR boxes can overlap on a curved page. Keep the actual
                # last option's bottom, without padding into the solution.
                y1 = min(y1, max(solution.y0, max(it.y1 for it in members)))
            boxes.append([x0, y0, x1, y1])
            bottoms.append(y1 - pad)
        column_headers = [h for h in headers if h.column == column]
        _clear_headers(boxes, starts, [h.cy for h in column_headers], mh)
        taps = [list(box) for box in boxes]
        _separate(taps, starts)
        crops = _bound_crops(boxes, bottoms, starts, column_headers, mh)
        for start, box, crop in zip(starts, taps, crops):
            regions.append({"number": start.number, "column": position,
                            "box": _page_box(frame, tuple(box), width, height),
                            "crop": _page_box(frame, tuple(crop), width, height)})
            if start.label:
                regions[-1]["label"] = start.label
    regions.sort(key=lambda r: (r["column"], r["box"][1]))
    for i, region in enumerate(regions):
        region["index"] = i + 1
    diagnostics["columns"] = len(used)
    return Segmentation(regions, "numbered", diagnostics)


def _inside_solution(start, starts, sections, solutions, mh):
    def preceding(line):
        return line.cy < start.item.cy and abs(line.x0 - start.item.x0) < 3 * mh

    boundary = max((line.cy for line in solutions if preceding(line)), default=-math.inf)
    reset = max((line.cy for line in sections if preceding(line)), default=-math.inf)
    title = max((s.item.cy for s in starts if s.kind != "number" and preceding(s.item)), default=-math.inf)
    # A numbered exercise book can resume with the next ordinary question
    # after a worked solution. Require a question stem and an earlier anchor;
    # plain numbered solution steps cannot reset the block themselves.
    if title <= reset and numbered_stem(start.item.head) and any(
        s.kind == "number" and preceding(s.item) and s.item.cy < boundary
        and 1 <= start.number - s.number <= MAX_STEP for s in starts
    ):
        return False
    reset = max(reset, title)
    return boundary > reset


def _isolated_number(start, lines, mh):
    """A lone short digit fragment needs a same-row question body, not just another digit."""
    item = start.item
    if start.kind != "number" or item.x1 - item.x0 >= 4 * mh or re.search(r"[\u3400-\u9fff]", item.head):
        return False
    return not any(line is not item and _rows_overlap(item, line)
                   and 0 <= line.x0 - item.x1 < 3 * mh and line.x1 - line.x0 >= 4 * mh
                   for line in lines)


def _repair_gaps(chain, row_leaders, mh, *, solutions=()):
    """Fill numbering gaps with margin lines whose number OCR misread (circled or ticked digits).

    Between consecutive chain members ``a`` and ``b`` of one column with missing
    numbers, eligible row-leading lines on that column's left margin can fill
    the gap. Weak number hints must match the complete missing sequence.
    """
    used = {id(s.item) for s in chain}
    result, repaired = [], []
    for a, b in zip(chain, chain[1:] + [None]):
        result.append(a)
        if (b is None or b.column != a.column or b.number - a.number < 2
                or a.kind != "number" or b.kind != "number"):
            continue
        margin = median(s.item.x0 for s in chain if s.column == a.column)
        between = sorted((line for line in row_leaders
                          if id(line) not in used and a.item.cy < line.cy < b.item.cy
                          and abs(line.x0 - margin) < 1.5 * mh and line.h >= 0.6 * mh
                          and not any(a.item.cy < solution.cy < line.cy and abs(solution.x0 - margin) < 3 * mh
                                      for solution in solutions)
                          and _repairable_head(line.head)), key=lambda line: line.cy)
        # Isolated numbers, letter-confused digits and damaged source labels
        # are weak hints. Require an unambiguous, complete sequence bounded
        # by strong numbers in the same column.
        hints = [gap_number_hint(line.head) for line in between]
        if any(hint is not None for hint in hints) and (
            len(between) != b.number - a.number - 1
            or any(hint not in {None, a.number + offset} for offset, hint in enumerate(hints, start=1))
        ):
            between = []
        for offset, line in enumerate(between[: b.number - a.number - 1], start=1):
            result.append(Start(line, a.number + offset, a.column))
            repaired.append({"number": a.number + offset, "head": line.head})
    return result, repaired


def _repairable_head(head):
    """Repair a damaged number only between already established question starts.

    Bare numbers, letter-confused digits and decimal-like source labels
    require a fully confirmed gap. Other decimal/formula heads must never
    enter through this gap-repair back door.
    """
    if gap_number_hint(head) is not None:
        return True
    return bool(DIGIT_HEAD.match(head)) and question_number(head, has_right_neighbour=False) is not None


def _clear_headers(boxes, starts, header_cys, mh):
    """Keep one column's boxes off a section header lying between two questions."""
    for k, (start, box) in enumerate(zip(starts, boxes)):
        top = start.item
        previous_cy = starts[k - 1].item.cy if k else -math.inf
        next_cy = starts[k + 1].item.cy if k + 1 < len(starts) else math.inf
        above = [cy for cy in header_cys if previous_cy < cy < top.cy]
        below = [cy for cy in header_cys if top.cy < cy < next_cy]
        if above:
            box[1] = max(box[1], min(max(above) + 0.5 * mh, top.y0 - 0.25 * mh))
        if below:
            box[3] = min(box[3], max(min(below) - 0.5 * mh, top.y1))


def _separate(boxes, starts):
    """Tap areas: no overlap, so a tap picks one question.

    Handwriting and photo blur inflate line boxes, so padded neighbours
    overlap; the split sits between the previous question's text and the next
    number line.
    """
    for k in range(len(boxes) - 1):
        box, below, line = boxes[k], boxes[k + 1], starts[k + 1].item
        if box[3] > below[1]:
            split = max(below[1], min(box[3], (line.y0 + line.cy) / 2))
            box[3] = split
            below[1] = split


def _bound_crops(boxes, bottoms, starts, headers, mh):
    """Crops sent to stage one: the whole question, overlapping neighbours only at the edges.

    Line boxes in photos overlap, so a crop holding its own last line touches
    the next line. Only the edge is allowed: a readable part of a neighbour
    or header is reported by the model as truncated content. A crop stops a
    quarter into the next number line box and starts a quarter line above the
    bottom of whatever precedes it (previous question or header), at most a
    quarter into its own number line box.
    """
    crops = [list(box) for box in boxes]
    for crop, start in zip(crops, starts[1:]):
        line = start.item
        crop[3] = min(crop[3], max(line.y0 + 0.25 * line.h, crop[1]))
    for k, (crop, start) in enumerate(zip(crops, starts)):
        top = start.item
        previous_cy = starts[k - 1].item.cy if k else -math.inf
        above = [h.y1 for h in headers if previous_cy < h.cy < top.cy]
        if above:
            above_bottom = max(above)
        elif k:
            above_bottom = bottoms[k - 1]
        else:
            continue
        crop[1] = min(max(crop[1], above_bottom - 0.25 * mh), top.y0 + 0.25 * top.h, crop[3])
    return crops


def _body_right(items, left, mh):
    """Right edge of the printed text: 90th percentile end of lines starting at the column margin."""
    ends = sorted(it.x1 for it in items if not it.figure and abs(it.x0 - left) < 3 * mh)
    return ends[min(len(ends) - 1, int(0.9 * len(ends)))] if ends else math.inf


def _until_gap(members, top, gap):
    """Members from the top line downwards, stopping at the first vertical gap wider than ``gap``."""
    members = sorted(members, key=lambda it: it.y0)
    kept, bottom = [], top.y1
    for it in members:
        if it.y0 - bottom > gap:
            break
        kept.append(it)
        bottom = max(bottom, it.y1)
    return kept or [top]


def _whole_content(lines, figures, frame, width, height, pad, tail, diagnostics):
    items = lines + figures
    box = (min(i.x0 for i in items) - pad, min(i.y0 for i in items) - pad,
           max(i.x1 for i in items) + tail, max(i.y1 for i in items) + pad)
    page_box = _page_box(frame, box, width, height)
    region = {"index": 1, "number": None, "column": 0, "box": page_box, "crop": page_box}
    return Segmentation([region], "whole_content", {**diagnostics, "reason": "no_numbering"})


def _page_box(frame, box, width, height):
    """Map a level-space box back to the page, take its bounding box, clamp and normalise."""
    points = [frame.page(x, y) for x, y in _corners(box)]
    x0 = max(0.0, min(p[0] for p in points)) / width
    y0 = max(0.0, min(p[1] for p in points)) / height
    x1 = min(float(width), max(p[0] for p in points)) / width
    y1 = min(float(height), max(p[1] for p in points)) / height
    return [round(x0, 5), round(y0, 5), round(x1, 5), round(y1, 5)]
