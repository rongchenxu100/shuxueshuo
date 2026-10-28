"""Conservative, versioned identities for reviewed public problem content."""

import json
import re
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.stage_one import contracts
from shuxueshuo_server.graph_lesson.stage_one.extraction import (
    scopes,
    validate_candidate,
)
from shuxueshuo_server.problem_understanding.identity import revision

IDENTITY_VERSION = 1
EXTRACTION_CONTRACT = "search-problem-extraction/v1"
PUBLIC_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "internal/schemas/search-public-content-v1.schema.json"
_COMMANDS = {
    "le": "≤", "leq": "≤", "leqslant": "≤", "ge": "≥", "geq": "≥", "geqslant": "≥",
    "lt": "<", "gt": ">", "ne": "≠", "neq": "≠", "forall": "∀", "exists": "∃",
    "in": "∈", "notin": "∉", "infty": "∞", "cdot": "*", "times": "*",
    "cup": "∪", "cap": "∩", "emptyset": "∅", "varnothing": "∅",
    "land": "∧", "wedge": "∧", "lor": "∨", "vee": "∨",
    "left": "", "right": "", "quad": " ", "qquad": " ",
}
_SURFACE_COMMANDS = {**_COMMANDS, "cdot": "·", "times": "×"}


class IdentityUnavailable(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def candidate_schema():
    schema = contracts.schema()
    public = json.loads(PUBLIC_SCHEMA_PATH.read_text(encoding="utf-8"))
    schema["properties"]["public_content"] = public
    schema["required"].append("public_content")
    schema["title"] = EXTRACTION_CONTRACT
    return schema


def mathematical_candidate(candidate):
    if not isinstance(candidate, dict):
        return None
    return {key: deepcopy(candidate[key]) for key in ("original_text", "root") if key in candidate}


def public_structure_errors(candidate):
    expected = list(scopes(candidate["root"]))
    public_scopes = candidate["public_content"]["scopes"]
    errors = []

    def option_surfaces(options, location):
        values = []
        for index, option in enumerate(options):
            try:
                value = _surface(option['text'])
            except IdentityUnavailable:
                errors.append((f'{location}/{index}/text', '选项中的公式须使用成对且内容非空的 $…$ 标记。'))
                value = None
            values.append((option['label'], value))
        return values

    if "root_label_role" in candidate["public_content"] and not candidate["root"].get("label", "").strip():
        errors.append(("/public_content/root_label_role", "只有实际存在顶层标签时才能声明其角色。"))
    if [item["scope_ref"] for item in public_scopes] != [path for path, _, _ in expected]:
        return [("/public_content/scopes", "所有题干与小问必须按原顺序完整对应 root。")]
    for index, ((path, scope, _), public_scope) in enumerate(zip(expected, public_scopes, strict=True)):
        location = f"/public_content/scopes/{index}/choices"
        if any(scope.get(field) for field in ("definitions", "facts", "goals")) and not public_scope["statement"].strip():
            errors.append((f"/public_content/scopes/{index}/statement", "包含数学内容的作用域不能遗漏其公开题干。"))
        choices = public_scope["choices"]
        targets = [f"{path}/goals/{number}" for number in range(len(scope.get("goals", [])))]
        if [choice["target_ref"] for choice in choices] != targets:
            errors.append((location, "每个所求必须按原顺序明确声明其选项状态。"))
        for number, choice in enumerate(choices):
            options = choice["options"]
            if choice["status"] == "none" and (options or choice["selection_mode"] != "none"):
                errors.append((f"{location}/{number}", "无选项状态不能同时提供选项或选择模式。"))
            if choice["status"] == "complete" and (
                len(options) < 2 or choice["selection_mode"] == "none"
                or len({option["label"] for option in options}) != len(options)
                or any(not option["text"].strip() or not option["label"].strip() for option in options)
            ):
                errors.append((f"{location}/{number}", "完整选项需要至少两项、不重复的标签和非空内容。"))
            goals = scope.get('goals', [])
            if number < len(goals) and goals[number]['kind'] == 'compare_functions':
                goal = goals[number]
                if goal['mode'] == 'pair':
                    if choice['status'] != 'none':
                        errors.append((f'{location}/{number}', '直接比较一对函数没有原题选择项。'))
                else:
                    previous_errors = len(errors)
                    shown = option_surfaces(options, f'{location}/{number}/options')
                    original = option_surfaces(goal['options'], f'{path}/goals/{number}/options')
                    if (len(errors) == previous_errors
                            and (choice['selection_mode'] != goal['selection_mode'] or shown != original)):
                        errors.append((f'{location}/{number}', '公开选项须与函数比较目标的标签、顺序和原文一致。'))
    return errors


def _spaces(text):
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(?<!\w)\s+|\s+(?!\w)", "", text)
    return re.sub(r"(?<=[\u3400-\u9fff])\s+|\s+(?=[\u3400-\u9fff])", "", text).strip()


def _prose(text):
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"(?<=[\u3400-\u9fff]) +(?=[\u3400-\u9fff])", "", text)


def _math(text):
    """Normalize compiled notation without rewriting opaque definition prose."""
    if re.search(r"[\u3400-\u9fff]", text):
        return text.strip()
    text = re.sub(r"\\mathbb\s*\{R\}", "ℝ", text)
    text = re.sub(r"\\([A-Za-z]+)", lambda match: _COMMANDS.get(match[1], match[0]), text)
    for before, after in (("−", "-"), ("×", "*"), ("<=", "≤"), (">=", "≥"), ("!=", "≠")):
        text = text.replace(before, after)
    return _spaces(text)


def _formula(text):
    """Public formulas are untyped: preserve distinct operators and literal TeX."""
    prepared = re.sub(r"\\mathbb\s*\{R\}", "ℝ", text)
    commands = re.findall(r"\\([A-Za-z]+|[^A-Za-z])", prepared)
    if "%" in text or any(command not in _SURFACE_COMMANDS for command in commands) or re.search(r"[\u3400-\u9fff]", text):
        return text.strip()
    prepared = re.sub(r"\\([A-Za-z]+)", lambda match: _SURFACE_COMMANDS[match[1]], prepared)
    for before, after in (("−", "-"), ("<=", "≤"), (">=", "≥"), ("!=", "≠")):
        prepared = prepared.replace(before, after)
    return _spaces(prepared)


def _surface(text):
    parts = text.split("$")
    if len(parts) % 2 == 0 or any(not part.strip() for part in parts[1::2]):
        raise IdentityUnavailable("identity.invalid_formula_delimiters")
    normalized = [_formula(part) if index % 2 else _prose(part)
                  for index, part in enumerate(parts)]
    if any(not part for part in normalized[1::2]):
        raise IdentityUnavailable("identity.empty_formula")
    return "$".join(normalized).strip()


def _root(scope, *, exclude_label=False):
    def goal_content(goal):
        if goal['kind'] == 'compare_functions':
            from ..problem_understanding.notation_function_comparison import (
                canonical_comparison, compile_comparison,
            )

            return canonical_comparison(compile_comparison(goal, 'r.goals[0]'))
        return {key: [_math(item) for item in content] if isinstance(content, list) else _math(content)
                for key, content in goal.items()}

    value = {
        "definitions": [_math(text) for text in scope.get("definitions", [])],
        "facts": [_math(text) for text in scope.get("facts", [])],
        "goals": [goal_content(goal) for goal in scope.get("goals", [])],
        "children": [_root(child) for child in scope.get("children", [])],
    }
    if not exclude_label and scope.get("label"):
        value["label"] = _prose(scope["label"]).strip()
    return value


def build_identity(result):
    if not isinstance(result, dict) or result.get("status") != "reviewed_candidate" or result.get("source_reviewed") is not True:
        raise IdentityUnavailable("identity.not_reviewed")
    candidate = result.get("public_candidate")
    if result.get("output_contract") != EXTRACTION_CONTRACT or not Draft202012Validator(candidate_schema()).is_valid(candidate):
        raise IdentityUnavailable("identity.missing_public_contract")
    if result.get("reviewed_candidate_revision") != revision(candidate):
        raise IdentityUnavailable("identity.review_revision_mismatch")
    mathematical = mathematical_candidate(candidate)
    if result.get("candidate") != mathematical or not validate_candidate(mathematical)["contract_valid"]:
        raise IdentityUnavailable("identity.invalid_mathematics")
    if any(scope.get("uncertainties") for _, scope, _ in scopes(candidate["root"])):
        raise IdentityUnavailable("identity.uncertain_mathematics")
    if not any(scope.get("goals") for _, scope, _ in scopes(candidate["root"])):
        raise IdentityUnavailable("identity.missing_goal")
    public = candidate["public_content"]
    if public["completeness"] != "complete":
        raise IdentityUnavailable("identity.incomplete_problem")
    if public["privacy"] != "separated":
        raise IdentityUnavailable("identity.private_content_unseparated")
    if public["figure"] != "not_required":
        raise IdentityUnavailable("identity.unrepresented_figure")
    if public_structure_errors(candidate):
        raise IdentityUnavailable("identity.invalid_public_structure")
    normalized_scopes, statements = [], []
    scope_labels = {path: scope.get("label", "") for path, scope, _ in scopes(candidate["root"])}
    exclude_root_label = public.get("root_label_role") == "source"
    for scope in public["scopes"]:
        statement = _surface(scope["statement"])
        normalized_choices = []
        label = scope_labels[scope["scope_ref"]] if scope["scope_ref"] != "/root" or not exclude_root_label else ""
        if statement:
            statements.append(_prose(label).strip() + statement)
        for choice in scope["choices"]:
            if choice["status"] not in {"none", "complete"}:
                raise IdentityUnavailable("identity.incomplete_choices")
            options = [{"label": _surface(option["label"]), "text": _surface(option["text"])} for option in choice["options"]]
            if len({option["label"] for option in options}) != len(options):
                raise IdentityUnavailable("identity.invalid_public_structure")
            normalized_choices.append({"target_ref": choice["target_ref"], "selection_mode": choice["selection_mode"], "options": options})
            statements.extend(option["label"] + ". " + option["text"] for option in options)
        normalized_scopes.append({"scope_ref": scope["scope_ref"], "statement": statement, "choices": normalized_choices})
    if not any(scope["statement"] for scope in normalized_scopes):
        raise IdentityUnavailable("identity.missing_statement")
    if any("[无法辨认]" in text for text in statements):
        raise IdentityUnavailable("identity.unreadable_content")
    identity = {"identity_version": IDENTITY_VERSION, "root": _root(candidate["root"], exclude_label=exclude_root_label), "scopes": normalized_scopes}
    return {"identity_version": IDENTITY_VERSION, "fingerprint": revision(identity), "identity": identity,
            "statement": "\n".join(statements), "structured_problem": deepcopy(identity)}
