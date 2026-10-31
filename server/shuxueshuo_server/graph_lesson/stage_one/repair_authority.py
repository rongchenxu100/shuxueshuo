"""Item-level repair authority: every change must be explained by one grant.

Facts, definitions and goals are matched as items, not as list positions.
Each current item ends up kept, moved, replaced or deleted, and each new item
is matched to a current one or inserted. Every outcome needs a grant whose
kind permits it at that place:

* ``wrong_scope`` only moves unchanged items within its container;
* ``missing_condition`` and a container-level ``wrong_goal`` only append to
  their scope's facts/definitions or goals;
* a goal-level ``missing_condition`` may add one absent typed input condition,
  without rewriting the target, existing conditions, or sibling goals;
* other review findings correct what they point to (a goal's field edits
  stay inside that field); only ``unsupported_addition`` may delete;
* compiler, schema and scope-policy diagnostics may edit, delete or insert at
  their own position.

An item grant explains at most one item, so equal items or several findings
can never be combined into extra authority.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

from shuxueshuo_server.problem_understanding.review_contract import pointer

ITEM_FIELDS = ("definitions", "facts", "goals")
UNCERTAINTIES = re.compile(r"^/root(?:/children/\d+)*/uncertainties(?:/|$)")
REVIEW_KINDS = frozenset(
    {
        "missing_condition",
        "wrong_expression",
        "wrong_scope",
        "wrong_goal",
        "unsupported_addition",
        "missing_figure",
        "unreadable",
        "ambiguous",
        "wrong_transcription",
    }
)
_ITEM_PATH = re.compile(r"^/root(?:/children/\d+)*/(?:definitions|facts|goals)/\d+$")
_SCOPE_STRUCTURE = re.compile(r"^/root(?:/children/\d+)*/(?:children(?:/\d+)?|label)$")
_APPEND_FIELDS = {"missing_condition": ("facts", "definitions"), "wrong_goal": ("goals",)}
_SCOPE_PREFIX = re.compile(r"^/root(?:/children/\d+)*")


class AmbiguousScopeMapping(ValueError):
    """Equal mathematical evidence would send a local grant to different scopes."""

    def __init__(self, paths):
        self.paths = sorted(paths)
        super().__init__("repair.ambiguous_scope_mapping")


def _key(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def edits(before, after, path=""):
    """(path, op) pairs in the original's coordinates; op is insert, delete or replace."""
    if type(before) is not type(after):
        return [(path, "replace")]
    if isinstance(before, dict):
        found = []
        for key in sorted(set(before) | set(after)):
            child = path + "/" + str(key).replace("~", "~0").replace("/", "~1")
            if key not in after and isinstance(before[key], list):
                # Omitting an optional collection after deleting its final item
                # has exactly the same edit authority as keeping an empty list.
                found.extend(edits(before[key], [], child))
            elif key not in before:
                found.append((child, "insert"))
            elif key not in after:
                found.append((child, "delete"))
            else:
                found.extend(edits(before[key], after[key], child))
        return found
    if isinstance(before, list):
        matcher = SequenceMatcher(
            None, [_key(x) for x in before], [_key(x) for x in after], autojunk=False
        )
        found = []
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == "equal":
                continue
            paired = min(i2 - i1, j2 - j1)
            for k in range(paired):
                found.extend(edits(before[i1 + k], after[j1 + k], f"{path}/{i1 + k}"))
            found.extend((f"{path}/{i}", "delete") for i in range(i1 + paired, i2))
            found.extend((f"{path}/{i2 + k}", "insert") for k in range(j2 - j1 - paired))
        return found
    return [] if before == after else [(path, "replace")]


def changed_paths(before, after, path=""):
    return [p for p, _ in edits(before, after, path)]


@dataclass(frozen=True)
class Grant:
    path: str
    code: str | None

    def covers(self, path):
        return path == self.path or path.startswith(self.path + "/")


@dataclass
class Item:
    list: str
    index: int
    value: object

    @property
    def path(self):
        return f"{self.list}/{self.index}"


def _items(scope, path="/root", place=None):
    """Items with their list paths; ``place`` maps a scope path to old coordinates."""
    if not isinstance(scope, dict):
        return []
    at = place(path) if place else path
    found = [
        Item(f"{at}/{field}", i, value)
        for field in ITEM_FIELDS
        if isinstance(scope.get(field), list)
        for i, value in enumerate(scope[field])
    ]
    for i, child in enumerate(scope.get("children") or []):
        found += _items(child, f"{path}/children/{i}", place)
    return found


def _children(scope):
    children = scope.get("children") if isinstance(scope, dict) else None
    return [c for c in children if isinstance(c, dict)] if isinstance(children, list) else []


def _contents(scope):
    return Counter((item.list.rsplit("/", 1)[1], _key(item.value)) for item in _items(scope))


def _own_contents(scope):
    if not isinstance(scope, dict):
        return Counter()
    return Counter(
        (field, _key(value))
        for field in ITEM_FIELDS
        if isinstance(scope.get(field), list)
        for value in scope[field]
    )


def _descendant_contents(scope, depth=0):
    """Mathematical evidence at each relative depth, independent of sibling order."""
    found = Counter()
    for child in _children(scope):
        found.update({(depth + 1, *key): count for key, count in _own_contents(child).items()})
        found.update(_descendant_contents(child, depth + 1))
    return found


def _scopes(scope, path):
    """This scope and all its sub-questions, parents before children."""
    found = [(path, scope)]
    for i, child in enumerate(_children(scope)):
        found += _scopes(child, f"{path}/children/{i}")
    return found


def _scope_places(old, new, authority, old_path="/root", new_path="/root", places=None):
    """Map every proposed scope path to the current scope it continues.

    Sub-questions keep their order unless this round authorizes a scope move:
    without one they are aligned in order, and only a sub-question some grant
    may delete can drop out, so removing it does not shift its siblings'
    grants. Inside an authorized scope move every nested sub-question is paired
    by its own and descendant content, so both an entire subtree and a single
    child moved under another parent keep their grants. Labels never decide
    identity, since a label may itself be corrected. A proposed scope without
    a counterpart gets a fresh path that only ancestor grants cover.
    """
    places = {} if places is None else places
    places[new_path] = old_path
    if authority.restructures(f"{old_path}/children"):
        before, after = _scopes(old, old_path)[1:], _scopes(new, new_path)[1:]
        matched = _content_pairs(before, after, authority, old_path, _contents(old) == _contents(new))
        for j, (path, _) in enumerate(after):
            if j in matched:
                places[path] = before[matched[j]][0]
            else:
                parent, index = path.rsplit("/children/", 1)
                places[path] = f"{places[parent]}/children/new{index}"
        return places
    before, after = _children(old), _children(new)
    pairs = _ordered_pairs(before, after, authority, old_path)
    for i, j in pairs:
        _scope_places(before[i], after[j], authority, f"{old_path}/children/{i}",
                      f"{new_path}/children/{j}", places)
    paired = {j for _, j in pairs}
    for j, child in enumerate(after):
        if j not in paired:
            for path, _ in _scopes(child, f"{new_path}/children/{j}"):
                parent, index = path.rsplit("/children/", 1)
                places[path] = f"{places[parent]}/children/new{index}"
    return places


def _content_pairs(before, after, authority, old_root, unchanged_items):
    """Match own evidence first, descendants second; never guess a local grant's owner.

    Own items anchor independently moved children. Descendant evidence keeps
    empty parent containers with their subtrees. The weights encode that
    priority over the whole assignment, rather than a fixed per-edge bonus.
    Equal evidence is harmless for pure moves, but not when it would transfer
    a correction/append grant to a different sub-question.
    """
    size = len(before) + len(after)
    own = [[_own_contents(scope) for _, scope in scopes] for scopes in (before, after)]
    below = [[_descendant_contents(scope) for _, scope in scopes] for scopes in (before, after)]
    descendant_weight = min(len(before), len(after)) + 1
    descendant_bound = min(sum(sum(values.values()) for values in side) for side in below)
    own_weight = (descendant_bound + 1) * descendant_weight
    cost = [[0] * size for _ in range(size)]
    for i in range(len(before)):
        for j in range(len(after)):
            shared = sum((own[0][i] & own[1][j]).values())
            descendants = sum((below[0][i] & below[1][j]).values())
            cost[i][j] = -(own_weight * shared + descendant_weight * descendants + 1)
    columns = _hungarian(cost)
    matched = {j: i for i, j in enumerate(columns[: len(before)]) if j < len(after)}
    if unchanged_items:
        # Pure mathematical moves use no local correction/append permission.
        # This also lets a repair first settle the hierarchy and ask for a
        # fresh source review before changing an indistinguishable local item.
        return matched
    best = sum(cost[i][j] for i, j in enumerate(columns))
    forbidden = 1 + size * max((abs(value) for row in cost for value in row), default=0)
    ambiguous = []
    local = [g for g in authority.grants if g.code != "wrong_scope" and not g.covers(old_root)]
    for i, (path, _) in enumerate(before):
        sensitive = any(
            (_SCOPE_PREFIX.match(g.path) and _SCOPE_PREFIX.match(g.path).group() == path)
            or (authority.append_lists(g) is None and g.covers(path))
            for g in local
        )
        if not sensitive:
            continue
        alternative = [row[:] for row in cost]
        # An unmatched scope can use any dummy column. Forbid all of those
        # together so the alternative actually changes its mathematical owner.
        blocked = [columns[i]] if columns[i] < len(after) else range(len(after), size)
        for j in blocked:
            alternative[i][j] = forbidden
        other = _hungarian(alternative)
        if sum(alternative[k][j] for k, j in enumerate(other)) == best:
            ambiguous.append(path)
    if ambiguous:
        raise AmbiguousScopeMapping(ambiguous)
    return matched


def _ordered_pairs(before, after, authority, path):
    """Order-preserving alignment; an old sub-question drops out only if deletable."""

    def drop(i):
        child = f"{path}/children/{i}"
        deletable = any(
            g.code not in REVIEW_KINDS or g.code == "unsupported_addition"
            for g in authority.editors(child)
        )
        return 0 if deletable else _INFEASIBLE

    def pair(i, j):
        return 10 - min(9, sum((_contents(before[i]) & _contents(after[j])).values()))

    n, m = len(before), len(after)
    best = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        best[i][m] = drop(i) + best[i + 1][m]
    for j in range(m - 1, -1, -1):
        best[n][j] = _CHURN + best[n][j + 1]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            best[i][j] = min(
                pair(i, j) + best[i + 1][j + 1],
                drop(i) + best[i + 1][j],
                _CHURN + best[i][j + 1],
            )
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if best[i][j] == pair(i, j) + best[i + 1][j + 1]:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif best[i][j] == drop(i) + best[i + 1][j]:
            i += 1
        else:
            j += 1
    return pairs


def _scope_edits(old, new, places):
    """Skeleton changes, comparing each scope with its counterpart.

    An absent ``children`` field and an empty list are the same; any change of
    which sub-questions a scope holds, or their order, is a change of its
    ``children``.
    """
    def own(scope, path):
        if not isinstance(scope, dict):
            return scope
        return _skeleton({k: v for k, v in scope.items() if k != "children"}, path)

    after = dict(_scopes(new, "/root"))
    counterpart = {o: n for n, o in places.items()}
    found = []
    for path, scope in _scopes(old, "/root"):
        if path not in counterpart:
            found.append((path, "delete"))
            continue
        twin = after[counterpart[path]]
        found += edits(own(scope, path), own(twin, path), path)
        held = [places[f"{counterpart[path]}/children/{j}"] for j in range(len(_children(twin)))]
        kept = [f"{path}/children/{i}" for i in range(len(_children(scope)))]
        if held != [p for p in kept if p in held] or any(
            p in counterpart and p not in held for p in kept
        ):
            found.append((f"{path}/children", "reorder"))
    return found


def _skeleton(value, path=""):
    """The candidate without its item lists, for checking every other field."""
    if isinstance(value, dict):
        return {
            key: _skeleton(item, f"{path}/{key}")
            for key, item in value.items()
            if not (key in ITEM_FIELDS and path.startswith("/root"))
        }
    if isinstance(value, list):
        return [_skeleton(item, f"{path}/{i}") for i, item in enumerate(value)]
    return value


class _Authority:
    def __init__(self, current, grants):
        self.current = current
        self.grants = grants
        self.used = set()

    def append_lists(self, grant):
        """Lists an append-only grant may extend, or None for an editing grant."""
        if grant.code not in _APPEND_FIELDS:
            return None
        try:
            container = pointer(self.current, grant.path)
        except (KeyError, ValueError, IndexError):
            container = None
        if isinstance(container, list):
            return {grant.path}
        if grant.code == "wrong_goal" and not (
            isinstance(container, dict) and "kind" not in container
        ):
            return None  # An existing goal is corrected in place.
        return {f"{grant.path}/{field}" for field in _APPEND_FIELDS[grant.code]}

    def editors(self, path):
        return [
            g
            for g in self.grants
            if g.code != "wrong_scope"
            and self.append_lists(g) is None
            and g.covers(path)
            and g not in self.used
        ]

    def can_move(self, old, new_list):
        """A scope move keeps the field: a fact never becomes a goal."""
        return old.list.rsplit("/", 1)[1] == new_list.rsplit("/", 1)[1] and any(
            g.code == "wrong_scope" and g.covers(old.path) and g.covers(new_list)
            for g in self.grants
        )

    def unexplained(self, old, value):
        changes = edits(old.value, value, old.path)
        if (len(changes) == 1 and isinstance(old.value, dict)
                and old.value.get('kind') in ('find_abstract_domain', 'find_abstract_range',
                                               'find_abstract_domain_parameter')):
            path, operation = changes[0]
            field = path.removeprefix(old.path + '/')
            if (operation == 'insert' and field in ('known_domain', 'known_range', 'input_domain')
                    and any(g.code == 'missing_condition' and g.path in (old.path, path)
                            and g not in self.used for g in self.grants)):
                return []
        return [path for path, _ in changes if not self.editors(path)]

    def can_delete(self, item):
        return any(
            g.code not in REVIEW_KINDS or g.code == "unsupported_addition"
            for g in self.editors(item.path)
        )

    def consume(self, item):
        """Item grants on or inside this item explain nothing else."""
        self.used.update(
            g
            for g in self.grants
            if (g.path == item.path or g.path.startswith(item.path + "/"))
        )

    def restructures(self, path):
        """A scope move may add, remove or relabel sub-question containers.

        Their facts, definitions and goals are still matched item by item, so
        restructuring never adds or drops mathematics.
        """
        return bool(_SCOPE_STRUCTURE.match(path)) and any(
            g.code == "wrong_scope" and g.covers(path) for g in self.grants
        )

    def insertable(self, list_path):
        """Whether any grant may insert into this list, ignoring positions."""
        return any(
            list_path in (self.append_lists(g) or ())
            or (
                g.code not in REVIEW_KINDS
                and (g.covers(list_path) or g.path.rsplit("/", 1)[0] == list_path)
            )
            for g in self.grants
        )

    def can_insert(self, list_path, position):
        if any(list_path in (self.append_lists(g) or ()) for g in self.grants):
            return True
        slot = f"{list_path}/{position}"
        for g in self.editors(slot):
            if g.code in REVIEW_KINDS:
                continue
            if _ITEM_PATH.match(g.path):
                if g.path != slot:
                    continue
                self.used.add(g)
            return True
        return False


def repair_violations(current, proposed, diagnostics):
    """Paths of changes that no same-round repair grant explains."""
    grants = [
        Grant(d.get("path", ""), d.get("code"))
        for d in diagnostics
        if d.get("action") == "repair"
    ]
    if any(g.path == "" for g in grants):
        return []  # Malformed top-level extraction can require re-extraction.
    authority = _Authority(current, grants)
    places = _scope_places(current.get("root"), proposed.get("root"), authority)
    outer = [{k: v for k, v in c.items() if k != "root"} for c in (current, proposed)]
    skeleton_edits = edits(*outer)
    if "root" in current or "root" in proposed:
        skeleton_edits += _scope_edits(current.get("root"), proposed.get("root"), places)
        if not ("root" in current and "root" in proposed):
            skeleton_edits.append(("/root", "replace"))
    violations = [
        path
        for path, _ in skeleton_edits
        if not UNCERTAINTIES.match(path)
        and not authority.editors(path)
        and not authority.restructures(path)
    ]
    old = _items(current.get("root"))
    new = _items(proposed.get("root"), place=places.__getitem__)
    assigned = _assign(old, new, authority)
    match = {j: old[i] for j, i in assigned.items()}
    for j, item in enumerate(new):
        if j not in match:
            continue
        before = match[j]
        if before.list != item.list and not authority.can_move(before, item.list):
            violations += [before.path, item.list]
        if _key(before.value) != _key(item.value):
            violations += authority.unexplained(before, item.value)
            authority.consume(before)
    for i, item in enumerate(old):
        if i in assigned.values():
            continue
        if authority.can_delete(item):
            authority.consume(item)
        else:
            violations.append(item.path)
    # An insertion sits after the preceding matched item of its list.
    position = {}
    for j, item in enumerate(new):
        if j in match:
            if match[j].list == item.list:
                position[item.list] = match[j].index + 1
        elif not authority.can_insert(item.list, position.get(item.list, 0)):
            violations.append(f"{item.list}/{position.get(item.list, 0)}")
    return list(dict.fromkeys(violations))


_INFEASIBLE = 10**6  # One unexplained change; outweighs every preference.
_FORBIDDEN = 10**9
# Deleting or inserting costs more than keeping, moving or correcting an item,
# so an item is never treated as removed and re-added when it can be matched.
_CHURN = 1000


def _assign(old, new, authority):
    """Globally cheapest outcome for every item: new index -> matched old index.

    Rows are old items plus one "inserted" row per new item; columns are new
    items plus one "deleted" column per old item. A greedy choice could spend
    the only grant that a later item needs (e.g. correcting the item that was
    authorized for deletion), so all items are assigned together.
    """
    n, m = len(old), len(new)
    size = n + m
    cost = [[_FORBIDDEN] * size for _ in range(size)]
    for i, before in enumerate(old):
        granted = bool(authority.editors(before.path))
        for j, after in enumerate(new):
            distance = min(abs(before.index - after.index), 9)
            same_list = before.list == after.list
            if _key(before.value) == _key(after.value):
                moved = 0 if same_list else 100 if authority.can_move(before, after.list) else _INFEASIBLE
                cost[i][j] = moved + 10 * granted + distance
            elif same_list or authority.can_move(before, after.list):
                explained = not authority.unexplained(before, after.value)
                cost[i][j] = (200 if explained else _INFEASIBLE) + 100 * (not same_list) + distance
        cost[i][m + i] = _CHURN if authority.can_delete(before) else _INFEASIBLE
    for j, after in enumerate(new):
        cost[n + j][j] = _CHURN if authority.insertable(after.list) else _INFEASIBLE
        for i in range(n):
            cost[n + j][m + i] = 0
    rows = _hungarian(cost)
    return {j: i for i, j in enumerate(rows[:n]) if j < m}


def _hungarian(cost):
    """Minimum-cost perfect assignment of a square matrix; returns row -> column."""
    size = len(cost)
    u, v = [0] * (size + 1), [0] * (size + 1)
    owner, way = [0] * (size + 1), [0] * (size + 1)
    for row in range(1, size + 1):
        owner[0], column = row, 0
        best, used = [float("inf")] * (size + 1), [False] * (size + 1)
        while True:
            used[column] = True
            current, delta, nxt = owner[column], float("inf"), 0
            for j in range(1, size + 1):
                if used[j]:
                    continue
                reduced = cost[current - 1][j - 1] - u[current] - v[j]
                if reduced < best[j]:
                    best[j], way[j] = reduced, column
                if best[j] < delta:
                    delta, nxt = best[j], j
            for j in range(size + 1):
                if used[j]:
                    u[owner[j]] += delta
                    v[j] -= delta
                else:
                    best[j] -= delta
            column = nxt
            if owner[column] == 0:
                break
        while column:
            previous = way[column]
            owner[column] = owner[previous]
            column = previous
    result = [0] * size
    for j in range(1, size + 1):
        if owner[j]:
            result[owner[j] - 1] = j - 1
    return result
