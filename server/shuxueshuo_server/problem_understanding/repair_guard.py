"""Conservative, atomic comparison against the request's original snapshot."""

import re
from collections import Counter

from .notation_compile import NotationValidator
from .notation_parser import NotationError, definition
from .notation_semantics import Canonical, bounded_expand, compare

MISSING = object()


def snapshot_diff(before, after, path=""):
    """Raw before/after evidence only; positional differences grant no authority."""
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        return [
            change
            for key in sorted(set(before) | set(after))
            for change in snapshot_diff(
                before.get(key, MISSING),
                after.get(key, MISSING),
                path + "/" + key.replace("~", "~0").replace("/", "~1"),
            )
        ]
    if isinstance(before, list) and isinstance(after, list):
        return [
            change
            for i in range(max(len(before), len(after)))
            for change in snapshot_diff(
                before[i] if i < len(before) else MISSING,
                after[i] if i < len(after) else MISSING,
                path + f"/{i}",
            )
        ]
    return [
        {
            "path": path,
            "before_present": before is not MISSING,
            "after_present": after is not MISSING,
            "before": None if before is MISSING else before,
            "after": None if after is MISSING else after,
        }
    ]


def equivalent(a, b):
    if a == b:
        return True
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    try:
        left, right = definition(a), definition(b)
        if left == right:
            return True

        def names(ast):
            if not isinstance(ast, list) or not ast:
                return set()
            return ({ast[1]} if ast[0] == "name" else set()).union(
                *(names(x) for x in ast[1:] if isinstance(x, list))
            )

        if names(left) != names(right):
            return False  # Never prove an unrelated rename through alias search.

        def wrap(text):
            return {
                "root": {"facts": [text]},
                "match_status": "unmatched",
                "family_id": None,
                "match_reason": "guard",
            }

        return compare(wrap(a), wrap(b))["ok"]
    except (NotationError, ValueError, TypeError, RecursionError):
        return False


def protected(value):
    """Syntax repair does not authorize removing logical/target requirements."""
    if isinstance(value, str):
        return Counter(
            {mark: value.count(mark) for mark in ("∀", "∃", "∧", "∨", "min", "max")}
        )
    if isinstance(value, dict):
        result = (
            Counter({"goal:" + value["kind"]: 1})
            if value.get("kind", "").startswith("find_")
            else Counter()
        )
        for item in value.values():
            result.update(protected(item))
        return result
    if isinstance(value, list):
        return sum((protected(x) for x in value), Counter())
    return Counter()


def erases_relation(before, after):
    if not isinstance(before, str) or not isinstance(after, str):
        return False
    if not any(mark in before for mark in ("=", "<", ">", "∈", "≤", "≥", "≠")):
        return False
    try:
        ast = definition(after)
        if ast[0] in ("=", "<=", ">=") and ast[1] == ast[2]:
            return True

        # A provably vacuous numeric/algebraic replacement is a deletion in
        # disguise. Unknown geometry is not guessed equivalent to truth.
        def wrap(facts):
            return {
                "root": {"facts": facts},
                "match_status": "unmatched",
                "family_id": None,
                "match_reason": "guard",
            }

        report = NotationValidator().validate(wrap([after]))
        if report.ok and len(report.semantic["facts"]) == 1:
            relation = report.semantic["facts"][0]
            if relation[0] in ("=", "<=", ">="):
                algebra = Canonical()
                difference = bounded_expand(
                    algebra.expr(relation[1]) - algebra.expr(relation[2])
                )
                return difference == 0
        return False
    except (NotationError, ValueError, TypeError, RecursionError):
        return False


def inventory(value):
    """A scope move must retain its mathematical items, goals and uncertainties."""
    result = []
    if not isinstance(value, dict):
        return result
    for field in ("definitions", "facts", "goals", "uncertainties"):
        result.extend(value.get(field, []))
    for child in value.get("children", []):
        result.extend(inventory(child))
    return result


def retains(old, new):
    remaining = list(new)
    for value in old:
        hit = next(
            (i for i, other in enumerate(remaining) if equivalent(value, other)), None
        )
        if hit is None:
            return False
        remaining.pop(hit)
    return True


def guard_changes(base, proposed, allowed):
    violations, changes = [], []
    rules = {p["path"]: p for p in allowed}
    usable_base = isinstance(base, dict) and isinstance(base.get("root"), dict)
    if any(
        (p["path"] == "" and p["mode"] != "reextract")
        or (p["mode"] == "reextract" and (usable_base or p["path"] != ""))
        for p in allowed
    ):
        return {
            "ok": False,
            "changes": [],
            "violations": [{"path": "", "code": "repair.outside_authority",
                            "message": "整份候选不能被授权重写；仅在没有可用基准候选时允许重新抽取。"}],
            "actual_diff": snapshot_diff(base, proposed),
        }
    if any(p["mode"] == "reextract" for p in allowed):
        return {
            "ok": True,
            "changes": [{"path": "", "mode": "reextract"}],
            "violations": [],
            "actual_diff": snapshot_diff(base, proposed),
        }

    def fail(path, reason):
        violations.append(
            {"path": path, "code": "repair.outside_authority", "message": reason}
        )

    def walk(a, b, path):
        # Original wording must be preserved verbatim outside its own grant;
        # algebraic equivalence cannot authorize rewriting the source text.
        unchanged = a == b if path == "/original_text" else equivalent(a, b)
        if unchanged:
            return
        rule = rules.get(path)
        if rule:
            mode = rule["mode"]
            changes.append(
                {
                    "path": path,
                    "mode": mode,
                    "before": None if a is MISSING else a,
                    "after": None if b is MISSING else b,
                }
            )
            if mode == "append":
                if (
                    a is MISSING
                    and path.rsplit("/", 1)[-1]
                    in {"definitions", "facts", "goals", "uncertainties"}
                    and isinstance(b, list)
                ):
                    return
                if isinstance(a, list) and isinstance(b, list) and retains(a, b):
                    return
                if isinstance(a, dict) and isinstance(b, dict):
                    # Only add mathematical facts/definitions at this scope.
                    for key in set(a) | set(b):
                        if key in {"facts", "definitions"}:
                            if not isinstance(b.get(key, []), list) or not retains(
                                a.get(key, []), b.get(key, [])
                            ):
                                fail(
                                    path + "/" + key,
                                    "遗漏修复只授权补充，不能删除或替换已有条件。",
                                )
                        else:
                            walk(
                                a.get(key, MISSING),
                                b.get(key, MISSING),
                                path + "/" + key,
                            )
                    return
                fail(path, "append 必须指向已有分问或数组。")
                return
            if mode == "subtree":
                if (
                    isinstance(a, dict)
                    and isinstance(b, dict)
                    and retains(inventory(a), inventory(b))
                    and retains(inventory(b), inventory(a))
                ):
                    return
                fail(path, "结构调整只能移动已有内容，不能增删数学内容或目标。")
                return
            if mode == "source_edit":
                deletion_authorized = rule.get("reason") == "unsupported_addition"
                if (b is MISSING or b in ("", [], {})) and not deletion_authorized:
                    fail(path, "未授权删除。")
                elif re.fullmatch(r"/root(?:/children/\d+)*", path) or (
                    isinstance(a, dict) and any(
                        k in a for k in ("root", "children", "facts", "definitions", "goals")
                    )
                ):
                    fail(path, "来源纠错需要精确定位，不能重写整个分问树。")
                return
            if b is MISSING or b in ("", [], {}):
                fail(path, "语法修复不能删除内容。")
            elif protected(a) - protected(b):
                fail(path, "语法修复移除了目标、量词、逻辑分支或最值限定。")
            elif erases_relation(a, b):
                fail(path, "语法修复不能把条件替换为恒真式。")
            elif isinstance(a, dict):
                # Missing/invalid fields can change, unrelated existing fields cannot.
                for key in set(a) - set(b):
                    fail(path + "/" + key, "语法修复不能删除已有字段。")
            return
        if isinstance(a, dict) and isinstance(b, dict):
            # Safe field placement changes share a single mathematical collection.
            if all(
                isinstance(x.get(k, []), list)
                for x in (a, b)
                for k in ("facts", "definitions")
            ):
                old_math = a.get("definitions", []) + a.get("facts", [])
                new_math = b.get("definitions", []) + b.get("facts", [])
                math_same = retains(old_math, new_math) and retains(new_math, old_math)
            else:
                math_same = False
            for key in sorted(set(a) | set(b)):
                if math_same and key in {"definitions", "facts"}:
                    continue
                left, right = a.get(key, MISSING), b.get(key, MISSING)
                if key in {
                    "definitions",
                    "facts",
                    "goals",
                    "children",
                    "uncertainties",
                }:
                    left = [] if left is MISSING else left
                    right = [] if right is MISSING else right
                walk(
                    left, right, path + "/" + key.replace("~", "~0").replace("/", "~1")
                )
            return
        if isinstance(a, list) and isinstance(b, list):
            # Match unchanged content first: deletions never shift an authorized
            # index onto an unrelated surviving item in the new array.
            old_left, new_left = list(range(len(a))), list(range(len(b)))
            moved_anchor = False
            for i in list(old_left):
                hit = next((j for j in new_left if equivalent(a[i], b[j])), None)
                if hit is not None:
                    moved_anchor |= i != hit
                    old_left.remove(i)
                    new_left.remove(hit)
            if path.endswith("/children"):
                # Scope position is semantic; do not match reordered children.
                for i in range(max(len(a), len(b))):
                    walk(
                        a[i] if i < len(a) else MISSING,
                        b[i] if i < len(b) else MISSING,
                        path + f"/{i}",
                    )
                return
            if len(old_left) > 1 and (moved_anchor or old_left != new_left):
                fail(path, "多个改动项无法对应到基准位置；保留原数组位置后重试。")
                return
            for pos, i in enumerate(old_left):
                walk(
                    a[i],
                    b[new_left[pos]] if pos < len(new_left) else MISSING,
                    path + f"/{i}",
                )
            for j in new_left[len(old_left) :]:
                fail(path, "未授权新增数组项。")
            return
        fail(path, "范围外内容发生了未证明等价的改变。")

    walk(base, proposed, "")

    # Missing uncertainty fields cannot be hidden by source/structure grants.
    def uncertainties(tree):
        if not isinstance(tree, dict):
            return []
        return list(tree.get("uncertainties", [])) + [
            u for c in tree.get("children", []) for u in uncertainties(c)
        ]

    if not retains(
        uncertainties(base.get("root", {})), uncertainties(proposed.get("root", {}))
    ):
        fail("/root", "本轮不能删除已有缺图或待确认声明。")
    return {
        "ok": not violations,
        "changes": changes,
        "violations": violations,
        "actual_diff": snapshot_diff(base, proposed),
    }
