"""Data-driven, three-state recognition and student knowledge references."""

import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / "site/data/knowledge-next"


def load_nodes():
    return {p.stem: json.loads(p.read_text()) for p in sorted((DATA / "nodes").glob("*.json"))}


def load_contracts():
    nodes = load_nodes()
    contracts = [json.loads(p.read_text()) for p in sorted((DATA / "recognition").glob("type-*.json"))]
    return [contract for contract in contracts if nodes.get(contract["type_id"], {}).get("status") != "planned"]


def _index(features):
    targets = {f.get("target_ref") for f in features if f.get("target_ref")}
    if len(targets) > 1:
        raise ValueError("recognition.multiple_targets")
    indexed = {f["feature_id"]: f for f in features}
    if len(indexed) != len(features):
        raise ValueError("recognition.duplicate_feature")
    return indexed


def _predicate(value, check):
    expected = check.get("expected")
    op = check["op"]
    if op == "known":
        return True
    if op == "eq":
        return type(value) is type(expected) and value == expected
    if op == "in":
        return any(type(value) is type(item) and value == item for item in expected)
    if op == "lte":
        return type(value) in (int, float) and value <= expected
    if op == "quadratic":
        return isinstance(value, dict) and value.get("degree") == 2 and value.get("degree_kind") in ("exact", "upper_bound")
    if op == "parameter_coefficients":
        return isinstance(value, dict) and any(item.get("contains_parameters") is True for item in value.get("items", []))
    raise ValueError(f"recognition.unknown_operator:{op}")


def _check(check, indexed, verification=None):
    feature_id = check["feature_id"]
    if feature_id == "verification.amgm":
        value = (verification or {}).get("status")
        known = value == "supported"
    else:
        feature = indexed.get(feature_id, {})
        known, value = feature.get("status") == "known", feature.get("value")
    actual = value
    for part in check.get("path", "").split(".") if check.get("path") else ():
        actual = actual.get(part) if isinstance(actual, dict) else None
    if not known:
        status = "unknown"
    else:
        holds = _predicate(actual, check)
        if check.get("role") == "exclude":
            holds = not holds
        status = "supported" if holds else "conflict"
    return {"status": status, "feature_id": feature_id, "actual": deepcopy(actual),
            "expected": deepcopy(check.get("expected", {"predicate": check["op"]})),
            "op": check["op"], "role": check.get("role", "required")}


def _all_status(statuses):
    return "conflict" if "conflict" in statuses else "unknown" if "unknown" in statuses else "supported"


def evaluate_types(features, verification=None, contracts=None):
    """Evaluate one target; unknown input never becomes a negative assertion."""
    indexed, nodes = _index(features), load_nodes()
    reports, identifiers = [], set()
    for contract in load_contracts() if contracts is None else contracts:
        type_id = contract["type_id"]
        if nodes.get(type_id, {}).get("status") == "planned":
            continue
        branches = []
        for branch in contract["branches"]:
            checks = []
            for check in branch["checks"]:
                check_id = f"{type_id}/{branch['branch_id']}/{check['id']}"
                if check_id in identifiers:
                    raise ValueError("recognition.duplicate_check_id")
                identifiers.add(check_id)
                result = {"check_id": check_id, **_check(check, indexed, verification)}
                cue = check.get("student_cue")
                if type(cue) is int and type_id in nodes:
                    result["student_cue"] = {"type_id": type_id, "index": cue,
                                             "text": nodes[type_id]["features"][cue]["cue"]}
                checks.append(result)
            branches.append({"branch_id": branch["branch_id"],
                             "status": _all_status([c["status"] for c in checks]), "checks": checks})
        statuses = [b["status"] for b in branches]
        status = "supported" if "supported" in statuses else "conflict" if statuses and all(s == "conflict" for s in statuses) else "unknown"
        reports.append({"type_id": type_id, "label": nodes.get(type_id, {}).get("label", type_id),
                        "status": status, "branches": branches})
    return reports


def _condition(condition, indexed):
    for key in ("all", "any"):
        if key not in condition:
            continue
        results = [_condition(child, indexed) for child in condition[key]]
        if key == "all":
            return all(ok for ok, _ in results), [f for _, fields in results for f in fields]
        for ok, fields in results:
            if ok:
                return True, fields
        return False, []
    result = _check(condition, indexed)
    return result["status"] == "supported", [condition["feature_id"]]


def derive_knowledge(features, primary=None):
    indexed, nodes = _index(features), load_nodes()
    rules = json.loads((DATA / "recognition/feature-knowledge.json").read_text())["rules"]
    items = []
    for rule in rules:
        holds, fields = _condition(rule["conditions"], indexed)
        if not holds:
            continue
        fields = list(dict.fromkeys(fields))
        items.append({"ref": rule["ref"], "rule_id": rule["rule_id"], "feature_ids": fields,
                      "values": {f: deepcopy(indexed[f]["value"]) for f in fields},
                      "fragment_kinds": rule["fragment_kinds"],
                      **({"matched_any": rule["matched_any"]} if "matched_any" in rule else {})})
    links, diagnostics = [], []
    if primary:
        declared = set(nodes.get(primary, {}).get("knowledge", []))
        lit = {item["ref"].split("#")[0] for item in items}
        for node in sorted(lit & declared):
            links.append({"from": node, "to": primary, "relation": "involves",
                          "knowledge_refs": [i["ref"] for i in items if i["ref"].split("#")[0] == node]})
        if not links or len(links) < min(2, len(lit)):
            diagnostics.append({"code": "knowledge.sparse_type_intersection", "type_id": primary,
                                "lit_nodes": sorted(lit), "linked_nodes": [x["from"] for x in links]})
    return {"items": items, "links": links, "diagnostics": diagnostics}


def build_d2(type_reports, primary):
    """Supported choices and proved-conflicting confuse entries, never unknowns."""
    reports = {r["type_id"]: r for r in type_reports}
    supported = [r["type_id"] for r in type_reports if r["status"] == "supported"]
    if primary is None:
        return {"options": []}
    if primary not in supported:
        raise ValueError("d2.primary_not_supported")
    nodes, origins = load_nodes(), {}
    for type_id in supported:
        for confuse in nodes.get(type_id, {}).get("confuse", []):
            target = confuse["ref"]
            if reports.get(target, {}).get("status") == "conflict":
                origins.setdefault(target, []).append({"type_id": type_id, "text": confuse["text"]})
    options = []
    for type_id in [*supported, *origins]:
        report = reports[type_id]
        role = "primary" if type_id == primary else "alternative" if type_id in supported else "conflict"
        evidence = [check for branch in report["branches"]
                    if role == "conflict" or branch["status"] == "supported"
                    for check in branch["checks"]
                    if check["status"] == ("conflict" if role == "conflict" else "supported")]
        feedback = "这是已确认的主要题型。" if role == "primary" else "这是得到支持的替代思路，不是数学错误。"
        if role == "conflict":
            feedback = "；".join(x["text"] for x in origins[type_id])
        options.append({"type_id": type_id, "label": nodes.get(type_id, {}).get("label", type_id),
                        "status": report["status"], "role": role, "feedback": feedback,
                        "check_ids": [c["check_id"] for c in evidence],
                        "checks": evidence, "confuse_sources": origins.get(type_id, [])})
    return {"options": options}
