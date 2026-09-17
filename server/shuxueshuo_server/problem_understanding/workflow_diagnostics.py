"""Explicit routing of compiler findings, separate from benchmark equivalence."""

import re

from .review_contract import pointer

REPAIRABLE = frozenset(
    {
        "notation.expected",
        "notation.unexpected_end",
        "notation.unbalanced_group",
        "notation.interval_arity",
        "notation.extremum_arity",
        "notation.quantifier_variable",
        "notation.radical_requires_number_or_group",
        "notation.geometry_shorthand",
        "binding.unknown_or_invisible",
        "binding.type_conflict",
        "binding.reserved_name",
        "binding.call_arity",
        "binding.endpoint_pair",
        "binding.quantifier_domain",
        "type.goal_target",
        "type.point_arguments",
        "type.call_arguments",
        "type.membership",
        "type.logic",
        "type.negation",
        "type.line_relation",
        "type.coordinates",
        "type.scalar_domain",
        "type.function_argument",
        "type.function_body",
        "type.relation",
        "type.arithmetic",
        "type.dimension",
        "type.fact_must_be_relation",
        "type.point_collection",
        "type.interval_endpoint",
    }
)


def json_pointer(path):
    if path.startswith("/"):
        return path
    if not path.startswith("r"):
        return "/root"
    path = re.sub(r"\.c(\d+)", r"/children/\1", path[1:])
    path = re.sub(r"\[(\d+)\]", r"/\1", path).replace(".", "/")
    return "/root" + path


def nearest_path(candidate, path):
    while path:
        try:
            pointer(candidate, path)
            return path
        except (KeyError, ValueError, IndexError):
            path = path.rsplit("/", 1)[0]
    return ""


def uncertainty_diagnostics(candidate):
    findings = []

    def visit(scope, path):
        if not isinstance(scope, dict):
            return
        for i, item in enumerate(scope.get("uncertainties", [])):
            if not isinstance(item, dict):
                continue
            kind = item.get("kind")
            if kind:
                findings.append(
                    {
                        "stage": "source",
                        "code": kind,
                        "path": f"{path}/uncertainties/{i}",
                        "source": item,
                        "message": item.get("text", ""),
                        "action": "code_gap"
                        if kind == "unstructured"
                        else "needs_confirmation",
                    }
                )
        for i, child in enumerate(scope.get("children", [])):
            visit(child, f"{path}/children/{i}")

    if isinstance(candidate, dict):
        visit(candidate.get("root"), "/root")
    return findings


def diagnose(parsed, candidate):
    result = []
    if "json" in parsed["reports"]:
        return [
            {
                "stage": "json",
                "code": "json.invalid",
                "path": "",
                "action": "repair",
                "message": "返回完整、合法 JSON。",
            }
        ]
    for issue in parsed["reports"].get("ir", {}).get("issues", []):
        code = issue.get("reason_code", issue["code"])
        # Unknown tokens/functions may be legitimate unsupported mathematics.
        # Only known catalog operators with invalid arity/type are auto-repaired.
        action = (
            "repair" if code in REPAIRABLE or code == "schema.invalid" else "code_gap"
        )
        result.append(
            {
                "stage": "schema" if code == "schema.invalid" else "compile",
                "code": code,
                "path": json_pointer(issue["path"]),
                "source": issue.get("source"),
                "message": issue["message"],
                "action": action,
            }
        )
    for code in parsed["reports"].get("match", {}).get("issues", []):
        result.append(
            {
                "stage": "match",
                "code": code,
                "path": "/family_id",
                "message": "按实际题意与注册表修正匹配声明；不能补写题设。",
                "action": "repair",
            }
        )
    return result


def review_diagnostics(review, candidate=None):
    return [
        {
            "stage": "review",
            "code": f["kind"],
            "path": f["path"],
            "source": pointer(candidate, f["path"]) if candidate is not None else None,
            "source_excerpt": f["source_excerpt"],
            "message": f["message"],
            "action": "needs_confirmation"
            if review["status"] == "uncertain"
            or f["kind"] in {"missing_figure", "unreadable", "ambiguous"}
            else "repair",
        }
        for f in review["findings"]
    ]


def permissions(candidate, diagnostics):
    if not isinstance(candidate, dict) or not isinstance(candidate.get("root"), dict):
        return [{"path": "", "mode": "reextract"}]
    allowed = []
    for issue in diagnostics:
        if issue["action"] != "repair":
            continue
        path = nearest_path(candidate, issue["path"])
        mode = "replace"
        value = pointer(candidate, path)
        if (
            issue["stage"] == "compile"
            and isinstance(value, dict)
            and value.get("kind", "").startswith("find_")
        ):
            field = next(
                (k for k in ("expression", "object", "symbol") if k in value), None
            )
            if field:
                path += "/" + field
        if issue["stage"] == "match":
            allowed.extend(
                {"path": "/" + key, "mode": "source_edit"}
                for key in ("family_id", "match_status", "match_reason")
            )
            continue
        if issue["stage"] == "review":
            if issue["code"] == "missing_condition":
                mode = "append"
            elif issue["code"] == "wrong_scope":
                mode = "subtree"
            else:
                mode = "source_edit"
                if (
                    issue["code"] == "wrong_goal"
                    and isinstance(value, dict)
                    and "kind" not in value
                ):
                    path += "/goals"
                # Missing goals refer to their existing container. They may be
                # appended, but replacing/deleting existing goals requires an
                # item-level finding. The same rule applies to math arrays.
                if isinstance(value, list) or path.endswith("/goals"):
                    mode = "append"
        allowed.append({"path": path, "mode": mode, "reason": issue["code"]})
        if (
            issue["stage"] == "compile"
            and issue["code"] == "binding.unknown_or_invisible"
        ):
            owner = re.match(r"/root(?:/children/\d+)*", path)
            if owner:
                allowed.append(
                    {
                        "path": owner[0] + "/definitions",
                        "mode": "append",
                        "reason": "binding.missing_local_definition",
                    }
                )
    # A repair must not rewrite a code-gap item, including through an ancestor
    # grant. Independent repairable paths may still make bounded progress.
    protected = [
        nearest_path(candidate, issue["path"])
        for issue in diagnostics
        if issue["action"] == "code_gap"
    ]
    allowed = [
        grant
        for grant in allowed
        if not any(
            grant["path"] == path
            or grant["path"].startswith(path + "/")
            or path.startswith(grant["path"] + "/")
            for path in protected
        )
    ]
    if allowed:
        # Evidence discovered while repairing may require a stop. This grants
        # only a diagnostic append, never permission to change mathematics.
        allowed.append(
            {
                "path": "/root/uncertainties",
                "mode": "append",
                "reason": "source_stop_diagnostic",
            }
        )
    return allowed


def repair_permissions(candidate, diagnostics):
    """Enrich internal diagnostics with stable snapshot content and grants."""
    allowed = permissions(candidate, diagnostics)
    for item in diagnostics:
        path = nearest_path(candidate, item["path"])
        item.setdefault(
            "source", pointer(candidate, path) if candidate is not None else None
        )
        item["repair_scope"] = [
            grant
            for grant in allowed
            if grant["path"] == path
            or grant["path"].startswith(path + "/")
            or path.startswith(grant["path"] + "/")
        ]
    return allowed
