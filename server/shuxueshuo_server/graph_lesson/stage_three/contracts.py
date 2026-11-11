"""Stage-three admission and serialized boundaries, without solver side effects."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from shuxueshuo_server.problem_understanding.candidate_common import strict_json
from shuxueshuo_server.problem_understanding.identity import revision

from ..stage_two import contracts as stage_two_contracts

ROOT = Path(__file__).resolve().parents[4]
RESULT_CONTRACT = "graph-stage-three-result/v1"
INPUT_MANIFEST_CONTRACT = "graph-stage-three-input-manifest/v1"
SCHEMA_PATH = ROOT / "internal/schemas/graph-stage-three-result-v1.schema.json"


def result_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _issue(code, path, message):
    return {"code": code, "path": path, "message": message}


def _read(path, diagnostics, field):
    try:
        return strict_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        diagnostics.append(_issue("input.read", field, f"无法读取 {path}：{type(exc).__name__}"))
        return None


def _is_input_manifest(value):
    if not isinstance(value, dict):
        return False
    contract = value.get("contract")
    if isinstance(contract, str) and contract.startswith("graph-stage-three-input-manifest/"):
        return True
    # Compatibility with the already retained 1a reports. A stage-one result
    # has its own contract and can never be mistaken for this legacy manifest.
    return contract is None and "admission" in value and all(
        isinstance(value.get(key), dict) and "snapshot" in value[key]
        for key in ("stage_one", "stage_two")
    )


def _manifest_source(manifest, source, stage_two, admission, diagnostics):
    """Resolve a portable snapshot only after binding the manifest to this input."""
    try:
        if manifest.get("contract", INPUT_MANIFEST_CONTRACT) != INPUT_MANIFEST_CONTRACT:
            raise ValueError("不支持的阶段③输入清单版本。")
        for key in ("stage_two", "stage_one"):
            item = manifest[key]
            if not isinstance(item, dict) or not {"reference", "sha256", "run_id", "snapshot"} <= item.keys():
                raise ValueError("阶段③输入清单缺少完整的快照元数据。")
        if manifest["admission"] != admission:
            raise ValueError("清单准入策略与阶段②结果不一致。")
        if manifest["stage_two"]["sha256"] != revision(stage_two):
            raise ValueError("清单未绑定当前阶段②结果的规范哈希。")
        if manifest["stage_one"]["sha256"] != stage_two["stage_one"]["sha256"]:
            raise ValueError("清单与阶段②引用的阶段①哈希不一致。")
        paths = {}
        for key in ("stage_two", "stage_one"):
            name = manifest[key]["snapshot"]
            if not isinstance(name, str) or not name or Path(name).is_absolute():
                raise ValueError("快照必须使用当前输出目录内的相对路径。")
            path = (source.parent / name).resolve()
            if not path.is_relative_to(source.parent.resolve()) or path == source.parent.resolve():
                raise ValueError("快照路径超出当前输出目录。")
            paths[key] = path
        if paths["stage_two"] != source.resolve() or paths["stage_one"] == paths["stage_two"]:
            raise ValueError("清单快照路径与当前输入不匹配。")
        return paths["stage_one"]
    except (KeyError, TypeError, ValueError, OSError, RuntimeError) as exc:
        diagnostics.append(_issue("input.manifest", "/input.json", str(exc)))
        return None


def _target_diagnostics(stage_two, candidate):
    expected = list(stage_two_contracts.targets(candidate))
    actual = stage_two["goals"]
    diagnostics = []
    if [row["target_ref"] for row in actual] != [row["target_ref"] for row in expected]:
        diagnostics.append(_issue("input.target_coverage", "/goals", "阶段②目标必须完整且按候选题意顺序排列。"))
    by_ref = {row["target_ref"]: row for row in expected}
    for index, goal in enumerate(actual):
        path = f"/goals/{index}"
        target = by_ref.get(goal["target_ref"])
        if target is None:
            diagnostics.append(_issue("input.target_ref", path + "/target_ref", "目标在阶段①候选中不存在。"))
            continue
        for field in ("scope", "label", "goal"):
            if field not in goal or goal[field] != target[field]:
                diagnostics.append(_issue("input.target_metadata", path + "/" + field, "目标元数据与阶段①原始目标不一致。"))
        reports = goal["types"]
        if any(not isinstance(row, dict) or not isinstance(row.get("type_id"), str)
               or row.get("status") not in ("supported", "unknown", "conflict") for row in reports):
            diagnostics.append(_issue("input.type_reports", path + "/types", "题型报告格式不完整。"))
            continue
        ids = [row["type_id"] for row in reports]
        supported = {row["type_id"] for row in reports if row["status"] == "supported"}
        if len(ids) != len(set(ids)) or supported != set(goal["supported"]):
            diagnostics.append(_issue("input.supported_types", path + "/supported", "支持集合与题型报告不一致。"))
        if goal["status"] == "resolved" and goal["primary"] not in supported:
            diagnostics.append(_issue("input.primary", path + "/primary", "主要归属必须有支持的题型报告。"))
    return diagnostics


def load_input(source, reference_base=None):
    """Load portable stage-two input, rechecking both upstream contracts.

    A present but corrupt local input is an error; it never falls back to an
    unrelated historical reference. Relative provenance needs an explicit base.
    """
    source = Path(source)
    diagnostics = []
    result = {"ok": False, "diagnostics": diagnostics, "stage_two": None, "stage_one": None,
              "source": str(source), "stage_one_source": None, "admission": None}
    value = _read(source, diagnostics, "/stage_two")
    result["stage_two"] = value
    if diagnostics:
        return result
    try:
        stage_two_contracts.validate_result(value)
    except (ValidationError, ValueError, KeyError, TypeError, IndexError, RecursionError) as exc:
        suffix = "/" + "/".join(map(str, exc.absolute_path)) if isinstance(exc, ValidationError) else "/stage_two"
        diagnostics.append(_issue("input.stage_two", suffix, str(exc).splitlines()[0]))
        return result
    if value["status"] not in ("completed", "partial"):
        diagnostics.append(_issue("input.status", "/status", "仅 completed 或 partial 的阶段②结果可以进入阶段③。"))
        return result
    options = value.get("options", {})
    admission = options.get("admission", "acceptance") if isinstance(options, dict) else None
    result["admission"] = admission
    if not isinstance(admission, str) or admission not in stage_two_contracts.ADMISSIONS:
        diagnostics.append(_issue("input.admission", "/options/admission", "阶段②准入策略非法。"))
        return result
    provenance = value["stage_one"]
    if not isinstance(provenance.get("sha256"), str) or not provenance["sha256"]:
        diagnostics.append(_issue("input.stage_one_hash", "/stage_one/sha256", "缺少阶段①规范哈希。"))
        return result
    input_path = source.parent / "input.json"
    if not input_path.exists():
        reference = provenance.get("reference")
        if not isinstance(reference, str) or not reference:
            diagnostics.append(_issue("input.stage_one_reference", "/stage_one/reference", "阶段①副本和有效来源引用均缺失。"))
            return result
        input_path = Path(reference)
        if not input_path.is_absolute():
            if reference_base is None:
                diagnostics.append(_issue("input.reference_base", "/stage_one/reference", "相对来源引用需要调用方显式提供基准目录。"))
                return result
            input_path = Path(reference_base) / input_path
    result["stage_one_source"] = str(input_path)
    stage_one = _read(input_path, diagnostics, "/stage_one")
    if not diagnostics and _is_input_manifest(stage_one):
        input_path = _manifest_source(stage_one, source, value, admission, diagnostics)
        if input_path is None:
            return result
        result["stage_one_source"] = str(input_path)
        stage_one = _read(input_path, diagnostics, "/stage_one")
    result["stage_one"] = stage_one
    if diagnostics:
        return result
    if revision(stage_one) != provenance["sha256"]:
        diagnostics.append(_issue("input.stage_one_hash", "/stage_one/sha256", "阶段①副本的规范哈希与阶段②记录不一致。"))
        return result
    checked = stage_two_contracts.validate_input(stage_one, admission=admission)
    if not checked["ok"]:
        diagnostics.extend({**row, "path": "/stage_one" + row["path"]} for row in checked["diagnostics"])
        return result
    diagnostics.extend(_target_diagnostics(value, stage_one["candidate"]))
    result["ok"] = not diagnostics
    return result


def aggregate_status(goals):
    admitted = [goal for goal in goals if goal["stage_two_status"] == "resolved"]
    failed = [goal for goal in admitted if goal["status"] in ("execution_error", "conflict")
              or any(route["status"] in ("math_failed", "execution_error") for route in goal["routes"])]
    return "failed" if admitted and len(failed) == len(admitted) else "partial" if failed else "completed"


def validate_result(value):
    """Reject contradictory completion claims, including zero-network accounting."""
    Draft202012Validator(result_schema()).validate(value)
    goals = value["goals"]
    if value["input_validation"]["diagnostics"] != value["input_diagnostics"]:
        raise ValueError("result.inconsistent_input_diagnostics")
    if value["status"] == "input_error":
        if value["input_validation"]["ok"] or not value["input_diagnostics"]:
            raise ValueError("result.invalid_input_failure")
        return
    if not value["input_validation"]["ok"] or value["input_diagnostics"] or not goals:
        raise ValueError("result.invalid_accepted_input")
    if len({goal["target_ref"] for goal in goals}) != len(goals):
        raise ValueError("result.duplicate_target")
    for goal in goals:
        selection = goal.get('selection')
        if selection is not None and not selection['branches'] and (
            goal['status'] != 'no_applicable_method' or selection.get('recommendation_rule') is not None
        ):
            raise ValueError('result.empty_selection_without_admission_failure')
        if goal["stage_two_status"] != "resolved":
            if goal["status"] != "skipped":
                raise ValueError("result.unresolved_goal_not_skipped")
        else:
            if not goal["primary"]:
                raise ValueError("result.resolved_goal_without_primary")
            if goal["status"] == "skipped":
                raise ValueError("result.resolved_goal_skipped")
        if goal["status"] in ("skipped", "unsupported_type", "no_applicable_method") and (
            goal["d3"] is not None or goal["d4"] is not None or goal["routes"]
        ):
            raise ValueError("result.ineligible_goal_artifacts")
        if goal["status"] in ("execution_error", "capability_gap") and not goal["diagnostics"]:
            raise ValueError("result.missing_execution_diagnostics")
        if goal["status"] in ("execution_error", "capability_gap") and goal["routes"]:
            # D3/D4 may preserve the already committed selection prefix;
            # interrupted route summaries stay in execution_evidence instead.
            raise ValueError("result.ineligible_goal_artifacts")
        if len({route["route_id"] for route in goal["routes"]}) != len(goal["routes"]):
            raise ValueError("result.duplicate_route")
        if goal["status"] == "solved":
            if not any(route["status"] == "verified" for route in goal["routes"]):
                raise ValueError("result.solved_without_verified_route")
        elif goal["answer"] is not None or goal["feasible_set"] is not None:
            raise ValueError("result.unverified_answer")
    expected = aggregate_status(goals)
    if value["status"] != expected:
        raise ValueError("result.invalid_aggregate_status")
