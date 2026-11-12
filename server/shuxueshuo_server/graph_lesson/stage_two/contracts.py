"""Stage-two boundaries: failed extraction artifacts are never recognition inputs."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from shuxueshuo_server.problem_understanding.review_contract import pointer

from ..stage_one import contracts as stage_one_contracts
from ..stage_one.extraction import scopes, validate_candidate
from ..stage_one.features import FEATURE_REGISTRY

ROOT = Path(__file__).resolve().parents[4]
RESULT_CONTRACT = "graph-stage-two-result/v1"
SCHEMA_PATH = ROOT / "internal/schemas/graph-stage-two-result-v1.schema.json"
FEATURE_VALUES_PATH = ROOT / "internal/schemas/graph-stage-two-input-feature-values-v1.schema.json"


def result_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def targets(candidate):
    """Preserve authored scope/goal order, including more than one goal per scope."""
    for path, scope, _ in scopes(candidate["root"]):
        for index, goal in enumerate(scope.get("goals", [])):
            yield {
                "target_ref": f"{path}/goals/{index}",
                "scope": path,
                "label": scope.get("label", ""),
                "goal": goal,
            }


def _visible_sources(candidate):
    """Only concrete local/inherited evidence entries belong to a target."""
    own, visible = {}, {}
    for path, scope, ancestors in scopes(candidate["root"]):
        own[path] = {
            f"{path}/{kind}/{index}"
            for kind in ("facts", "definitions")
            for index in range(len(scope.get(kind, [])))
        }
        inherited = set().union(*(own[ancestor] for ancestor in ancestors))
        for index in range(len(scope.get("goals", []))):
            target = f"{path}/goals/{index}"
            visible[target] = own[path] | inherited | {target}
            goal = scope['goals'][index]
            if goal['kind'] == 'find_function_formula' or (goal['kind'] in ('find_value', 'find_range') and 'relation' in goal):
                for field in ('function', 'variable', 'relation', 'relation_domain', 'declared_domain', 'requested_domain', 'function_type', 'expression', 'symbol'):
                    if field in goal:
                        visible[target].add(f'{target}/{field}')
                visible[target].update(f'{target}/additional_relations/{i}' for i in range(len(goal.get('additional_relations', []))))
                visible[target].update(f'{target}/relation_variables/{i}' for i in range(len(goal.get('relation_variables', []))))
            if goal['kind'] in ('find_translation_range', 'find_abstract_domain', 'find_abstract_domain_parameter', 'find_abstract_range'):
                for field in ('function_relation', 'periodic_function', 'period', 'periodic_domain', 'known_call', 'known_domain', 'known_range', 'target_call', 'input_domain', 'variable', 'parameter', 'quantifier', 'strength'):
                    if field in goal:
                        visible[target].add(f'{target}/{field}')
            if goal['kind'] == 'determine_function_parity':
                visible[target].update(f'{target}/{field}' for field in ('function', 'variable', 'expression', 'input_domain')
                                       if field in goal)
            if goal['kind'] == 'compare_functions':
                for fi, function in enumerate(goal['shared_functions']):
                    prefix = f'{target}/shared_functions/{fi}'
                    visible[target].add(prefix + '/definition')
                    if 'domain' in function:
                        visible[target].add(prefix + '/domain')
                for oi, option in enumerate(goal['options']):
                    for fi, function in enumerate(option['functions']):
                        prefix = f'{target}/options/{oi}/functions/{fi}'
                        visible[target].add(prefix + '/definition')
                        if 'domain' in function:
                            visible[target].add(prefix + '/domain')
    return visible


def _required_piecewise_features(root):
    """Use the validated AST to require only the applicable new input feature."""
    from ..piecewise_equation import relevant as equation_relevant
    from ..piecewise_inequality import relevant as inequality_relevant

    own, required = {}, {}
    for path, scope, ancestors in scopes(root):
        own[path] = [{'value': fact} for fact in scope['facts']]
        records = [row for ancestor in ancestors for row in own[ancestor]] + own[path]
        for index, goal in enumerate(scope['goals']):
            if 'pricing' in goal or goal['kind'] == 'match_range':
                continue
            if inequality_relevant(goal, records):
                required[f'{path}/goals/{index}'] = 'piecewise_inequality'
            elif equation_relevant(goal, records):
                required[f'{path}/goals/{index}'] = 'piecewise_equation'
    return required


# Acceptance inputs come from recorded batches checked against gold fixtures.
# Student uploads have no gold: they must say so explicitly and are admitted on
# extraction, source review and features alone, never by claiming evaluation.
ADMISSIONS = {
    "acceptance": ("source_reviewed", "features", "evaluation", "passed"),
    "student_upload": ("source_reviewed", "features"),
    "authored_topic": ("author_reviewed", "features"),
}


def validate_input(value, admission="acceptance"):
    diagnostics = []
    if admission not in ADMISSIONS:
        raise ValueError(f"unknown admission: {admission}")
    feature_values = json.loads(FEATURE_VALUES_PATH.read_text(encoding="utf-8"))

    def issue(code, path, message):
        diagnostics.append({"code": code, "path": path, "message": message})

    for error in Draft202012Validator(stage_one_contracts.result_schema()).iter_errors(value):
        issue("input.schema", "/" + "/".join(map(str, error.absolute_path)), error.message)
    if diagnostics:
        return {"ok": False, "diagnostics": diagnostics[:32]}
    candidate = value.get("candidate")
    checked = validate_candidate(candidate)
    if not checked["contract_valid"]:
        issue("input.candidate", "/candidate", "阶段①候选不完整或数学／作用域校验未通过。")
    statuses = value["statuses"]
    extraction = 'authored_candidate' if admission == 'authored_topic' else 'reviewed_candidate'
    if statuses.get("extraction") != extraction:
        issue("input.extraction", "/statuses/extraction", "阶段①尚未完成题意提取与原图复核。")
    if admission == "student_upload" and statuses.get("admission") != "student_upload":
        issue("input.admission", "/statuses/admission", "学生上传的阶段①结果必须标明 admission=student_upload。")
    if admission == 'authored_topic':
        from ...problem_understanding.identity import revision
        provenance = value.get('provenance')
        schema = {
            'type': 'object', 'required': ['kind', 'candidate_sha256', 'sources', 'reviewer'],
            'properties': {
                'kind': {'const': 'authored_topic'},
                'candidate_sha256': {'const': revision(candidate)},
                'reviewer': {'type': 'string', 'minLength': 1},
                'sources': {'type': 'array', 'minItems': 1, 'items': {
                    'type': 'object', 'required': ['reference', 'sha256', 'location'],
                    'properties': {'reference': {'type': 'string', 'minLength': 1},
                                   'sha256': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
                                   'location': {'type': 'string', 'minLength': 1}}}},
            },
        }
        if (statuses.get('admission') != admission or statuses.get('source_reviewed') is not False
                or any(key in statuses for key in ('evaluation', 'passed'))):
            issue('input.authored_claims', '/statuses', '专题录入须明确来源，不能声称经过拍题复核或金标验收。')
        for error in Draft202012Validator(schema).iter_errors(provenance):
            issue('input.authored_provenance', '/provenance', error.message)
        from ..stage_one.features import extract_features
        if checked['contract_valid'] and value['features'] != extract_features(candidate)['features']:
            issue('input.authored_features', '/features', '专题特征必须由当前规范题意重新计算。')
    for key in ADMISSIONS[admission]:
        if statuses.get(key) is not True:
            issue("input.not_accepted", f"/statuses/{key}", "阶段①完成与验收标记必须明确为 true。")
    if not checked["contract_valid"]:
        return {"ok": False, "diagnostics": diagnostics}
    expected = {item["target_ref"]: item for item in targets(candidate)}
    visible_sources = _visible_sources(candidate)
    if not expected:
        issue("input.no_targets", "/candidate/root", "候选没有可判型的目标。")
    registry = {spec.feature_id for spec in FEATURE_REGISTRY}
    piecewise_required = _required_piecewise_features(checked['compiled']['root'])
    grouped = {target: set() for target in expected}
    for index, row in enumerate(value["features"]):
        path = f"/features/{index}"
        if not isinstance(row, dict):
            issue("input.feature_shape", path, "特征必须是对象。")
            continue
        target, feature = row.get("target_ref"), row.get("feature_id")
        if not isinstance(target, str) or target not in expected:
            issue("input.feature_target", path + "/target_ref", "特征指向当前候选中不存在的目标。")
            continue
        if row.get("scope") != expected[target]["scope"]:
            issue("input.feature_scope", path + "/scope", "特征作用域与目标作用域不一致。")
        if not isinstance(feature, str) or feature not in registry:
            issue("input.feature_id", path + "/feature_id", "特征未登记在阶段①注册表中。")
            continue
        if feature in grouped[target]:
            issue("input.feature_duplicate", path, "同一目标的特征重复。")
        grouped[target].add(feature)
        status = row.get("status")
        if status not in ("known", "conditional", "unknown") or "value" not in row:
            issue("input.feature_shape", path, "特征缺少合法的 status/value。")
        elif status in ("known", "conditional"):
            validator = Draft202012Validator({**feature_values, "$ref": f"#/$defs/{feature}"})
            for error in validator.iter_errors(row["value"]):
                suffix = "/".join(map(str, error.absolute_path))
                issue("input.feature_value", path + "/value" + ("/" + suffix if suffix else ""), error.message)
        if status == "unknown" and not row.get("diagnostics"):
            issue("input.feature_reason", path, "未知特征必须保留原因。")
        if status == "conditional" and not row.get("conditions"):
            issue("input.feature_reason", path, "条件特征必须保留适用条件。")
        for name in ("conditions", "diagnostics"):
            entries = row.get(name, [])
            if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
                issue("input.feature_reason", path + "/" + name, "条件和诊断必须是对象列表。")
        if not isinstance(row.get("source_refs"), list):
            issue("input.feature_sources", path + "/source_refs", "特征缺少题意依据列表。")
        else:
            for source_index, ref in enumerate(row["source_refs"]):
                source_path = f"{path}/source_refs/{source_index}"
                try:
                    if not isinstance(ref, str):
                        raise TypeError("source ref must be a string")
                    pointer(candidate, ref)
                except (ValueError, KeyError, IndexError, TypeError):
                    issue("input.feature_source_ref", source_path, "出处必须是候选中可解析的 JSON 指针。")
                    continue
                if ref not in visible_sources[target]:
                    issue("input.feature_source_scope", source_path,
                          "出处仅可引用本作用域及祖先的事实、定义，或当前目标。")
    for target, found in grouped.items():
        # Additive type features are required only for their own goals. Older
        # reviewed results do not contain irrelevant features introduced later;
        # any rows they do contain still receive all shape/source checks above.
        kind = expected[target]['goal']['kind']
        required = registry - {'shifted_odd', 'symmetry_relation', 'parity_extension', 'parity_inequality', 'symmetry_evaluation', 'parity_parameter', 'function_parity', 'abstract_monotonicity', 'monotonicity_parameter', 'monotonicity_inequality', 'function_extremum', 'function_monotonicity', 'function_domain', 'function_comparison', 'abstract_function_domain', 'function_evaluation', 'function_range', 'abstract_function_range', 'translation_range',
                               'function_graph', 'piecewise_equation', 'piecewise_inequality'}
        if kind == 'determine_monotonicity_on_interval' or (
                kind == 'prove_monotonicity_on_interval' and 'relation' in expected[target]['goal']):
            required.add('abstract_monotonicity')
        elif kind in ('find_monotonic_intervals', 'prove_monotonicity_on_interval'):
            required.add('function_monotonicity')
        if kind in ('find_value', 'finite_sum', 'find_range'):
            from ..stage_three.context import build_context
            context = build_context(candidate, target)
            if context.get('parity_parameter_goal') is not None:
                required.add('parity_parameter')
            if context.get('shifted_odd_goal') is not None:
                required.add('shifted_odd')
            elif context.get('symmetry_relation_goal') is not None:
                required.add('symmetry_relation')
            if context.get('symmetry_value_goal') is not None:
                required.add('symmetry_evaluation')
            if context.get('parity_inequality_goal') is not None:
                required.add('parity_inequality')
        if kind == 'find_function_formula':
            from ..stage_three.context import build_context
            if build_context(candidate, target).get('parity_extension_goal') is not None:
                required.add('parity_extension')
        if kind == 'find_range' and 'required_monotonicity' in expected[target]['goal']:
            required.add('monotonicity_parameter')
        if target in piecewise_required:
            required.add(piecewise_required[target])
        if kind in ('select_function_graph', 'draw_function_graph', 'solve_graph_inequality'):
            required.add('function_graph')
        required.discard('function_formula')
        required.discard('piecewise_modeling')
        if 'pricing' in expected[target]['goal']:
            required.add('piecewise_modeling')
        required.discard('piecewise_range_parameter')
        if kind == 'match_range':
            required.add('piecewise_range_parameter')
        if kind == 'find_function_formula' or (kind in ('find_value', 'find_range') and 'relation' in expected[target]['goal']):
            required.add('function_formula')
        elif kind in ('find_range', 'select_range_domain', 'find_extrema_expression') and 'object' in expected[target]['goal']:
            required.add('function_range')
        elif kind in ('find_domain', 'match_domain'):
            required.add('function_domain')
        elif kind == 'compare_functions':
            required.add('function_comparison')
        elif kind == 'determine_function_parity':
            required.add('function_parity')
        elif kind in ('find_abstract_domain', 'find_abstract_domain_parameter'):
            required.add('abstract_function_domain')
        elif kind == 'find_translation_range':
            required.add('translation_range')
        elif kind == 'find_abstract_range':
            required.add('abstract_function_range')
        elif kind in ('find_value', 'check_constant', 'finite_sum'):
            required.add('function_evaluation')
        if missing := required - found:
            issue("input.features_incomplete", target, "缺少阶段①特征：" + ", ".join(sorted(missing)))
    return {"ok": not diagnostics, "diagnostics": diagnostics}


def validate_result(value):
    Draft202012Validator(result_schema()).validate(value)
    goals = value["goals"]
    if value["status"] == "input_error":
        if value["input_validation"]["ok"] or not value["input_diagnostics"]:
            raise ValueError("result.invalid_input_failure")
        return
    if not value["input_validation"]["ok"] or not goals:
        raise ValueError("result.invalid_accepted_input")
    failed = sum(goal["status"] == "selection_failed" for goal in goals)
    expected = "failed" if failed == len(goals) else "partial" if failed else "completed"
    if value["status"] != expected:
        raise ValueError("result.invalid_aggregate_status")
    if len({goal["target_ref"] for goal in goals}) != len(goals):
        raise ValueError("result.duplicate_target")
    for goal in goals:
        if goal["status"] == "resolved" and goal["primary"] not in goal["supported"]:
            raise ValueError("result.primary_not_supported")
        if goal["status"] == "unsupported" and goal["supported"]:
            raise ValueError("result.supported_is_not_unsupported")
        if goal["status"] == "selection_failed" and len(goal["supported"]) < 2:
            raise ValueError("result.failure_requires_multiple_candidates")
