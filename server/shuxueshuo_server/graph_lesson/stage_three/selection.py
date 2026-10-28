"""Contract-driven method selection, independent of execution availability."""

import json
from copy import deepcopy

from jsonschema import Draft202012Validator

from ..stage_two.recognition import DATA, load_nodes
from .fragments import build_fragments
from .premises import check_premise


def load_contract(primary):
    nodes = load_nodes()
    if nodes.get(primary, {}).get("status") == "planned":
        return None
    direct = DATA / "selection" / f"{primary}.json"
    if direct.exists():
        contract = json.loads(direct.read_text())
        schema = json.loads((DATA.parents[2] / "internal/schemas/graph-direct-method-selection-v1.schema.json").read_text())
        Draft202012Validator(schema).validate(contract)
        methods = nodes[primary].get('methods', [])
        if contract.get('admission') == 'function_domain_routes':
            route_methods = [row['method'] for row in contract.get('routes', [])]
            if (contract['type'] != primary or nodes[primary].get('rules')
                    or not route_methods or any(method not in methods for method in route_methods)):
                raise ValueError('selection.direct_contract_node_mismatch')
        elif (contract['type'] != primary or contract.get('method') not in methods
                or nodes[primary].get('rules')):
            raise ValueError('selection.direct_contract_node_mismatch')
        return contract
    for rule in nodes.get(primary, {}).get("rules", []):
        path = DATA / "selection" / f"{rule}.json"
        if path.exists():
            contract = json.loads(path.read_text())
            schema = json.loads((DATA.parents[2] / "internal/schemas/graph-method-selection-v1.schema.json").read_text())
            Draft202012Validator(schema).validate(contract)
            if contract.get("schema_version") != "graph-method-selection/v1":
                raise ValueError("selection.unsupported_contract")
            expected = [(b["id"], b["target"]) for b in nodes[rule]["branches"]]
            actual = [(b["branch"], b["target"]) for b in contract["branches"]]
            if expected != actual or contract.get("rule") != rule:
                raise ValueError("selection.contract_node_mismatch")
            return contract
    return None


def _trigger(checks, indexed):
    states = []
    for check in checks:
        feature = indexed.get(check["feature"], {})
        if feature.get("status") != "known":
            states.append("unknown")
            continue
        actual = feature["value"]
        for key in check.get("path", []):
            actual = actual.get(key) if isinstance(actual, dict) else None
        choices = check.get("in", [check.get("equals")])
        holds = any(type(actual) is type(expected) and actual == expected for expected in choices)
        states.append("triggered" if holds else "not_triggered")
    return "not_triggered" if "not_triggered" in states else "unknown" if "unknown" in states else "triggered"


def _matches(condition, branches, indexed, case_split):
    if "all" in condition:
        return all(_matches(item, branches, indexed, case_split) for item in condition["all"])
    if "applicable" in condition:
        return branches[condition["applicable"]]["applicability"] == "applicable"
    if "feature" in condition:
        row = indexed.get(condition["feature"], {})
        expected = condition.get("in", [condition.get("equals")])
        return row.get("status") == "known" and any(
            type(row["value"]) is type(value) and row["value"] == value for value in expected
        )
    if "case_split" in condition:
        return case_split["status"] == condition["case_split"]
    if "applicable_count" in condition:
        return sum(b["applicability"] == "applicable" for b in branches.values()) == condition["applicable_count"]
    if condition == {"fallback": True}:
        return True
    raise ValueError("selection.unknown_recommendation_condition")


def _recommend(contract, branches, indexed):
    case_split = check_premise("interval_case_split", indexed)
    for rule in contract["recommendation"]["rules"]:
        if not _matches(rule["when"], branches, indexed, case_split):
            continue
        applicable = [b for b in contract["recommendation"]["priority"]
                      if branches[b]["applicability"] == "applicable"]
        preferred = rule.get("preferred", applicable[0] if applicable else None)
        if preferred not in applicable:
            continue
        for key in applicable:
            branches[key]["recommendation"] = (
                "preferred" if key == preferred else
                "superseded" if key in rule.get("superseded", []) else "optional"
            )
        return rule["id"], case_split
    return None, case_split


def evaluate_goal(candidate, target_ref, features, primary):
    """Evaluate one admitted stage-two target. Batch 1a executes no routes."""
    if isinstance(primary, dict):
        primary = primary.get("type_id")
    contract = load_contract(primary)
    if contract is None:
        return {"status": "unsupported_type", "selection": None, "d3": None, "d4": None,
                "diagnostics": [{"code": "selection.contract_missing", "type_id": primary}]}
    if contract['schema_version'] == 'graph-direct-method-selection/v1':
        # Schema expansion alone must not silently reuse this admission check.
        # New direct categories need an explicit runtime implementation as well.
        admission = contract.get('admission')
        if admission not in ('function_domain', 'function_domain_routes', 'function_equality',
                             'abstract_function_domain'):
            raise ValueError('selection.unsupported_direct_admission')
        from .context import build_context
        from .equality_runtime import admitted as admitted_equality
        from .function_domain import admitted, admitted_parameter
        from .method_admission import _abstract_function_domain as admitted_abstract
        context = build_context(candidate, target_ref)
        # Re-read the candidate. A supplied type/feature/method override never
        # grants admission to a different mathematical category.
        checks = {
            'function_domain': admitted,
            'function_domain_parameter': admitted_parameter,
            'function_equality': admitted_equality,
            'abstract_function_domain': admitted_abstract,
        }
        if admission == 'function_equality':
            routes = [{'method': contract['method'], 'route_id': contract['route_id'],
                       'admission': admission, 'label': '同一函数判定法'}]
        elif admission == 'function_domain':
            routes = [{'method': contract['method'], 'route_id': contract['route_id'],
                       'admission': 'function_domain', 'label': '列条件求交集法'}]
        elif admission == 'abstract_function_domain':
            routes = [{'method': contract['method'], 'route_id': contract['route_id'],
                       'admission': admission, 'label': '输入范围对应法'}]
        else:
            routes = contract['routes']
        chosen = None
        for route in routes:
            guard = checks.get(route['admission'])
            if guard is None:
                raise ValueError('selection.unsupported_direct_admission')
            if guard(context):
                if chosen is not None:
                    raise ValueError('selection.ambiguous_direct_route')
                chosen = route
        if chosen is None:
            selection = {'kind': 'direct_method', 'rule': None, 'branches': [],
                         'recommendation_rule': None, 'recommendation_checks': []}
            return {'status': 'no_applicable_method', 'selection': selection,
                    'd3': None, 'd4': None, 'diagnostics': []}
        label = chosen.get('label') or (
            '定义域求参法' if chosen['admission'] == 'function_domain_parameter' else
            '输入范围对应法' if chosen['admission'] == 'abstract_function_domain' else
            '列条件求交集法'
        )
        branch = {'branch': 'direct', 'target': chosen['method'], 'route_id': chosen['route_id'],
                  'trigger': 'triggered', 'applicability': 'applicable',
                  'recommendation': 'preferred',
                  'route_plan': 'capability_gap',
                  'checks': [{'check_id': 'original_function_domain', 'status': 'holds'}],
                  'missing_capabilities': [f"execution:{chosen['method']}"]}
        selection = {'kind': 'direct_method', 'rule': None, 'branches': [branch],
                     'recommendation_rule': 'direct_admission', 'recommendation_checks': []}
        question = (
            '逐项比较定义域，再比较对应关系，完成各项判断后按原题要求作答。'
            if chosen['admission'] == 'function_equality' else
            '已知定义域恰为给定集合，列出有意义条件并化为参数范围。'
            if chosen['admission'] == 'function_domain_parameter' else
            ('让每个完整输入落在题设给定范围内，要求存在共同合法的自变量，再求参数范围。'
             if context['goal']['kind'] == 'find_abstract_domain_parameter' else
             '先求 f 的输入范围，再列出目标函数的输入条件，最后求出目标函数的定义域。')
            if chosen['admission'] == 'abstract_function_domain'
            else '按原式列出有意义的条件，分别求解，再取交集。'
        )
        d3 = {'id': 'D3', 'title': '选择解题方法', 'question': question,
              'query': {'op': 'methods', 'from': primary}, 'interaction': {'type': 'read'},
              'expected_answer': {}, 'verdicts': {}, 'submit_label': f'用{label}解题'}
        d4 = {'id': 'D4', 'title': '解题路线', 'options': [{
            'route_id': branch['route_id'], 'branch': 'direct', 'method': branch['target'],
            'recommendation': 'preferred', 'route_plan': branch['route_plan'], 'message': '开始解题'}]}
        if admission == 'function_equality':
            workspaces = [{key: row[key] for key in ('option_id', 'label', 'text')}
                          for row in context['comparison_goal']['options']]
            d4['options'][0]['option_workspaces'] = workspaces
        return {'status': 'no_verified_route', 'selection': selection,
                'd3': d3, 'd4': d4, 'diagnostics': []}
    selected = [row for row in features if row.get("target_ref") == target_ref]
    indexed = {row["feature_id"]: row for row in selected}
    if len(indexed) != len(selected):
        raise ValueError("selection.duplicate_feature")
    branches = {}
    for entry in contract["branches"]:
        trigger = _trigger(entry["trigger"], indexed)
        checks = [check_premise(name, indexed) for name in entry["premises"]] if trigger == "triggered" else []
        statuses = [check["status"] for check in checks]
        applicability = (None if trigger == "not_triggered" else "unknown" if trigger == "unknown"
                         else "not_applicable" if "fails" in statuses else "unknown" if "unknown" in statuses
                         else "applicable")
        branches[entry["branch"]] = {
            "branch": entry["branch"], "target": entry["target"], "route_id": entry["route_id"],
            "trigger": trigger, "applicability": applicability, "recommendation": None,
            "route_plan": "not_planned", "checks": checks, "missing_capabilities": [],
        }
    rule, case_split = _recommend(contract, branches, indexed)
    for branch in branches.values():
        if branch["recommendation"] in ("preferred", "optional"):
            branch["route_plan"] = "capability_gap"
            branch["missing_capabilities"] = [f"execution:{branch['target']}"]
    selection = {"rule": contract["rule"], "branches": list(branches.values()),
                 "recommendation_rule": rule, "recommendation_checks": [case_split]}
    status = "no_verified_route" if rule else "no_applicable_method"
    d3, d4 = (build_fragments(contract, selection, indexed, primary,
                              candidate=candidate, target_ref=target_ref) if rule else (None, None))
    return {"status": status, "selection": deepcopy(selection), "d3": d3, "d4": d4, "diagnostics": []}
