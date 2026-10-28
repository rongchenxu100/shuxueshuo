"""Read printed answer choices without adding them to mathematical premises.

Stage one transcribes the image. This module recognizes an explicit option list
in that reviewed transcription; it never infers an answer or changes ``root``.
Ambiguous ownership and incomplete lists remain unavailable.
"""

import re
from copy import deepcopy

from shuxueshuo_server.problem_understanding.notation_parser import NotationError, parse

from ..stage_two.fragments import _scope_ranges
from ..stage_two.surface_math import normalize_surface

_TARGET = re.compile(r"/root(?:/children/\d+)*/goals/\d+\Z")
_LABEL = re.compile(
    r"(?<![\w\\])(?:([A-HＡ-Ｈ])[.．、:：)）]|[（(]([A-HＡ-Ｈ])[）)])\s*"
)
_LABELS = "ABCDEFGH"
_POINT_NAMES = r"[A-ZＡ-Ｚ](?:[ \t]*、[ \t]*[A-ZＡ-Ｚ])+"
_COUNTED_POINTS = re.compile(
    rf"(?<![\w\\])(?P<names>{_POINT_NAMES})[ \t]*(?P<count>[两二三四五六七八九2-9])[ \t]*(?:个[ \t]*)?点"
)
_NAMED_POINTS = re.compile(rf"点[ \t]*(?P<names>{_POINT_NAMES})(?![A-Za-zＡ-Ｚａ-ｚ0-9_]|[ \t]*、)")
_POINT_COUNTS = {name: count for count, name in enumerate("二三四五六七八九", 2)} | {"两": 2}
_EXTRA_COMMANDS = {
    "leqslant": "≤", "geqslant": "≥", "neq": "≠", "ne": "≠",
    "lor": "∨", "vee": "∨", "land": "∧", "wedge": "∧",
    "cup": "∪", "cap": "∩", "emptyset": "∅", "varnothing": "∅",
    "notin": "∉",
}


def _math_group(text, start):
    """Return one bounded TeX argument, with no evaluation or macro expansion."""
    while start < len(text) and text[start].isspace():
        start += 1
    if start >= len(text):
        raise ValueError("missing TeX argument")
    if text[start] != "{":
        if text[start].isdigit() or text[start].isalpha():
            return text[start], start + 1
        raise ValueError("unsupported TeX argument")
    depth = 1
    for stop in range(start + 1, len(text)):
        depth += (text[stop] == "{") - (text[stop] == "}")
        if depth == 0:
            return text[start + 1:stop], stop + 1
        if depth > 16:
            raise ValueError("TeX depth limit")
    raise ValueError("unbalanced TeX argument")


def _tex_math(text, depth=0):
    if depth > 16:
        raise ValueError("TeX depth limit")
    result, index = [], 0
    while index < len(text):
        command = re.match(r"\\(dfrac|tfrac|frac|sqrt)(?![A-Za-z])", text[index:])
        if command:
            name = command.group(1)
            first, stop = _math_group(text, index + command.end())
            first = _tex_math(first, depth + 1)
            if name == "sqrt":
                result.append(f"sqrt({first})")
            else:
                second, stop = _math_group(text, stop)
                result.append(f"(({first})/({_tex_math(second, depth + 1)}))")
            index = stop
            continue
        if text[index:index + 2] == "^{":
            power, stop = _math_group(text, index + 1)
            result.append(f"^({_tex_math(power, depth + 1)})")
            index = stop
            continue
        result.append(text[index])
        index += 1
    return "".join(result)


def option_expression(text, *, real_parameter=None):
    """Return parser-ready mathematics, or None for prose/unsupported notation.

    This is notation conversion only. Even a parsed option is not assumed to be
    true, equivalent to a goal answer, or admissible for the matching capability.
    A range goal supplies its real parameter for the textbook shorthand
    ``{k | condition}``; other binders and explicit domains are not inferred.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 2048:
        return None
    if text.count("$") % 2 or "[无法辨认]" in text:
        return None
    try:
        value = _tex_math(text).replace("$", "")
        value = re.sub(r"\\mathbf(?:\{\s*R\s*\}|\s+R\b)", "ℝ", value)
        value = re.sub(
            r"\\([A-Za-z]+)",
            lambda match: _EXTRA_COMMANDS.get(match.group(1), match.group()),
            value,
        )
        value = normalize_surface(value).text
        value = re.sub(r"或者|或", "∨", value)
        value = re.sub(r"并且|且", "∧", value)
        value = value.strip().rstrip("。；;").strip()
        if isinstance(real_parameter, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", real_parameter):
            shorthand = re.fullmatch(
                r"\{\s*" + re.escape(real_parameter) + r"\s*([|:])(.+)\}", value, re.DOTALL,
            )
            if shorthand:
                separator, condition = shorthand.groups()
                value = f"{{{real_parameter}∈ℝ{separator}{condition}}}"
        parse(value)
    except (NotationError, ValueError, RecursionError):
        return None
    return value


def _scope(candidate, target_ref):
    if not isinstance(target_ref, str) or not _TARGET.fullmatch(target_ref):
        raise ValueError("invalid target")
    scope = candidate["root"]
    parts = target_ref.split("/")[2:]
    for index in range(0, len(parts) - 2, 2):
        scope = scope["children"][int(parts[index + 1])]
    goals = scope.get("goals", [])
    if len(goals) != 1 or int(parts[-1]) != 0:
        raise ValueError("ambiguous choice goal")
    return scope


def _own_ranges(candidate, target_ref, ranges):
    scope_ref = target_ref.rsplit("/goals/", 1)[0]
    if "/children/" not in scope_ref:
        return ranges
    # _scope_ranges omits empty text ranges. Query the parent introduction as
    # well, so an empty child cannot accidentally inherit its parent's choices.
    parent_ref = scope_ref.rsplit("/children/", 1)[0]
    parent_candidate = deepcopy(candidate)
    parent = parent_candidate["root"]
    for index in parent_ref.removeprefix("/root").split("/children/")[1:]:
        parent = parent["children"][int(index)]
    parent["goals"] = [{}]
    ancestor_ranges = _scope_ranges(parent_candidate, parent_ref + "/goals/0")
    return [region for region in ranges if region not in ancestor_ranges]


def _point_name_spans(text):
    """Exclude explicit point enumerations, never search for a convenient A-D suffix."""
    spans = []
    for pattern in (_COUNTED_POINTS, _NAMED_POINTS):
        for match in pattern.finditer(text):
            names = [name.strip() for name in match["names"].split("、")]
            names = [chr(ord(name) - 0xFEE0) if "Ａ" <= name <= "Ｚ" else name for name in names]
            if len(set(names)) != len(names):
                continue
            if pattern is _COUNTED_POINTS:
                count = int(match["count"]) if match["count"].isdigit() else _POINT_COUNTS[match["count"]]
                if count != len(names):
                    continue
            spans.append(match.span("names"))
    return spans


def _option_markers(text):
    point_names = _point_name_spans(text)
    return [match for match in _LABEL.finditer(text)
            if text[:match.start()].count("$") % 2 == 0
            and not any(start <= match.start() < end for start, end in point_names)]


def _selection_mode(text, visible_ranges):
    """Use the nearest explicit format heading; options are not headings.

    Ancestor introductions can declare a section's format, while a child may
    explicitly override it. A conflicting heading is conservatively treated as
    multiple-selection, which the matching layer will not silently downgrade.
    """
    for start, end in reversed(visible_ranges):
        body = text[start:end]
        markers = _option_markers(body)
        prefix = body[:markers[0].start()] if markers else body
        if re.search(r"多项选择|多选|不定项", prefix):
            return "multiple"
        if re.search(r"单项选择|单选", prefix):
            return "single"
    return "unspecified"


def choice_source(candidate, target_ref):
    """Identify a complete printed choice list belonging to exactly one goal.

    Legacy transcription provides no expected option count, so fewer than four
    choices cannot distinguish a short list from a cropped/truncated one. Such
    lists are deliberately unavailable instead of guessing their completeness.
    """
    base = {"target_ref": target_ref, "source": "transcription"}
    if isinstance(candidate, dict) and "public_content" in candidate:
        return _public_choice_source(candidate, target_ref)
    text = candidate.get("original_text", "") if isinstance(candidate, dict) else ""
    if not isinstance(text, str) or not text or len(text) > 32768:
        return {**base, "status": "unavailable", "reason": "choice.missing_text"}
    try:
        scope = _scope(candidate, target_ref)
        visible_ranges = _scope_ranges(candidate, target_ref)
        ranges = _own_ranges(candidate, target_ref, visible_ranges)
        if not ranges:
            raise ValueError("missing scope text")
        # The earlier ranges are ancestor introductions, not this goal's own
        # question. Never borrow their option blocks for a child.
        start, end = ranges[-1]
    except (KeyError, IndexError, TypeError, ValueError):
        return {**base, "status": "unavailable", "reason": "choice.ambiguous_scope"}
    body = text[start:end]
    markers = _option_markers(body)
    if not markers:
        return {**base, "status": "not_choice"}
    labels = [chr(ord(label) - 0xFEE0) if "Ａ" <= label <= "Ｈ" else label
              for match in markers for label in [match.group(1) or match.group(2)]]
    if len(labels) < 4 or labels != list(_LABELS[:len(labels)]):
        return {**base, "status": "unavailable", "reason": "choice.incomplete_options"}
    goal = scope["goals"][0]
    real_parameter = (goal.get("symbol") if goal.get("kind") == "find_range"
                      else goal.get("parameter") if goal.get("kind") == "find_abstract_domain_parameter" else None)
    options = []
    for index, marker in enumerate(markers):
        stop = markers[index + 1].start() if index + 1 < len(markers) else len(body)
        option = body[marker.end():stop].strip()
        if not option or len(option) > 2048 or "[无法辨认]" in option:
            return {**base, "status": "unavailable", "reason": "choice.incomplete_options"}
        options.append({"label": labels[index], "text": option,
                        "expression": option_expression(option, real_parameter=real_parameter)})
    return {**base, "status": "recognized", "selection_mode": _selection_mode(text, visible_ranges),
            "options": options}


def _public_choice_source(candidate, target_ref):
    """Use the reviewed, scoped option contract; never borrow a sibling's options."""
    base = {"target_ref": target_ref, "source": "public_content"}
    try:
        scope = _scope(candidate, target_ref)
        public = candidate["public_content"]
        scopes = [row for row in public["scopes"]
                  if row["scope_ref"] == target_ref.rsplit("/goals/", 1)[0]]
        if public["completeness"] != "complete" or len(scopes) != 1:
            raise ValueError("incomplete public content")
        choices = [row for row in scopes[0]["choices"] if row["target_ref"] == target_ref]
        if len(choices) != 1:
            raise ValueError("ambiguous choice target")
        choice = choices[0]
        mode, options = choice["selection_mode"], choice["options"]
        if choice["status"] == "none" and mode == "none" and options == []:
            return {**base, "status": "not_choice"}
        if (choice["status"] != "complete" or mode not in ("single", "multiple", "unspecified")
                or not isinstance(options, list) or not 2 <= len(options) <= 32):
            raise ValueError("incomplete choices")
        labels = [row["label"] for row in options]
        if (any(not isinstance(label, str) or not label.strip() for label in labels)
                or len(set(labels)) != len(labels)
                or any(not isinstance(row["text"], str) or not row["text"].strip()
                       or len(row["text"]) > 4096 for row in options)):
            raise ValueError("invalid choices")
        goal = scope["goals"][0]
        parameter = (goal.get("symbol") if goal["kind"] == "find_range"
                     else goal.get("parameter") if goal["kind"] == "find_abstract_domain_parameter" else None)
        return {**base, "status": "recognized", "selection_mode": mode,
                "options": [{"label": row["label"], "text": row["text"],
                             "expression": option_expression(row["text"], real_parameter=parameter)}
                            for row in options]}
    except (KeyError, IndexError, TypeError, ValueError):
        return {**base, "status": "unavailable", "reason": "choice.incomplete_public_options"}
