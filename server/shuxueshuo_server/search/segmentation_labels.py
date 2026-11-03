"""Printed textbook headings, separate from worksheet numbering and formulas."""

import re

_TITLE = re.compile(
    r"^\s*(?P<opening>[【\[（(])?\s*"
    r"(?P<kind>例题|例|变式(?:训练|练习)?|练习题|练习)\s*"
    r"(?P<number>[1-9][0-9]{0,2}|[一二三四五六七八九十]{1,3})"
    r"(?=$|[\s】\]）).．、:：]|已知|若|设|求|如图|计算|证明)"
)
_SOLUTION = re.compile(r"^\s*(?:[【\[（(]\s*(?:解析|分析|解答|解|答案|反思|点评)\s*[】\]）)]"
                       r"|(?:解析|分析|解答|解|答案|反思|点评)\s*[:：])")
_HEADING_PREFIX = re.compile(r"^\s*[【\[（(]\s*(?:例|变式|练习|解析|分析|解答|答案|反思|点评)")
_NUMBERED_STEM = re.compile(r"^\s*\d{1,2}\s*[.．、:：)）]\s*(?:已知|若|设|求|计算|如图|下列|函数)")
_DIGITS = {char: index for index, char in enumerate("零一二三四五六七八九")}


def textbook_title(head):
    """Return a typed label; its number does not join the worksheet number chain."""
    match = _TITLE.match(head or "")
    if not match:
        return None
    tail = head[match.end():].lstrip()
    if match["opening"] and (not tail or tail[0] not in "】]）)"):
        return None  # An incomplete OCR heading must not silently lose a digit.
    digits = match["number"]
    if digits.isascii():
        number = int(digits)
    elif "十" in digits and digits.count("十") == 1:
        tens, units = digits.split("十")
        if len(tens) > 1 or len(units) > 1:
            return None
        number = 10 * (_DIGITS[tens] if tens else 1) + (_DIGITS[units] if units else 0)
    elif len(digits) == 1:
        number = _DIGITS[digits]
    else:
        return None
    kind = match["kind"]
    return {"kind": "example" if kind.startswith("例") else "variant" if kind.startswith("变式") else "exercise",
            "number": number, "label": f"{kind}{digits}"}


def solution_heading(head):
    return bool(_SOLUTION.match(head or ""))


def incomplete_heading(head):
    """Only a clipped editorial heading gets a wider second OCR crop."""
    return bool(_HEADING_PREFIX.match(head or "")) and not re.search(r"[】\]）)]", head)


def numbered_stem(head):
    return bool(_NUMBERED_STEM.match(head or ""))
