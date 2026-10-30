"""Family-free contract adapter for the shared, bounded extraction workflow."""

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator

from shuxueshuo_server.problem_understanding.candidate_common import strict_json
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_parser import definition, parse
from shuxueshuo_server.problem_understanding.notation_semantics import canonical
from shuxueshuo_server.problem_understanding.review_contract import pointer
from shuxueshuo_server.problem_understanding.workflow import (
    MathNotationWorkflowContract,
)
from shuxueshuo_server.problem_understanding.workflow_diagnostics import (
    diagnose as math_diagnose,
)
from shuxueshuo_server.problem_understanding.workflow_diagnostics import (
    review_diagnostics,
)
from shuxueshuo_server.problem_understanding.workflow_ledger import WorkflowStop, save
from shuxueshuo_server.problem_understanding.workflow_storage import FileWorkflowStorage
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    MultimodalExtractionPrompt,
)

from . import contracts
from .repair_authority import (  # noqa: F401
    AmbiguousScopeMapping,
    changed_paths,
    edits,
    repair_violations,
)

REPO = Path(__file__).resolve().parents[4]
REPAIR_SCOPE = (
    "保留没有诊断授权的题文与数学内容，只修复列出的诊断。每条诊断只授权它所指的一项："
    "分问归属错误只能移动已有内容，遗漏条件或遗漏目标只能在所指分问追加，"
    "表达式或目标错误只能原位改正，只有新增题设可以删除。"
)
JSON_REPAIR = (
    r"上一轮输出不是合法 JSON，解析错误见 issues。JSON 字符串里的反斜杠必须成对书写，"
    r"例如 \le 写作 \\le；original_text 的公式用 $…$ 包围，不使用 \( \) 或 \[ \]。"
    "返回完整、合法 JSON。"
)


def frozen_files():
    """Portable identity for every executable or textual input to this stage."""
    package = REPO / "server/shuxueshuo_server"
    paths = [
        *Path(__file__).parent.glob("*.py"),
        package / "graph_lesson/function_equality.py",
        package / "graph_lesson/function_evaluation.py",
        package / "graph_lesson/domain_expression.py",
        package / "graph_lesson/range_syntax.py",
        *(package / "problem_understanding").glob("*.py"),
        package / "solver/extraction/multimodal_provider.py",
        package / "solver/extraction/deepseek_files.py",
        *contracts.TEMPLATE_FILES,
    ]
    return {
        str(p.relative_to(REPO)): sha256(p.read_bytes()).hexdigest()
        for p in sorted(set(paths))
    }


def _nodes(tree, kind):
    found = [tree] if tree[0] == kind else []
    for child in tree[1:]:
        if isinstance(child, list) and child and isinstance(child[0], str):
            found.extend(_nodes(child, kind))
    return found


def _polynomial_syntax(tree):
    """Only transparent scalar arithmetic is eligible for representation repair."""
    if tree[0] in {"name", "number"}:
        return True
    if tree[0] == "neg":
        return _polynomial_syntax(tree[1])
    if tree[0] in {"+", "-", "*"}:
        return all(_polynomial_syntax(child) for child in tree[1:])
    if tree[0] == "^" and tree[2][0] == "number":
        power = tree[2][1]
        return power.isdigit() and 0 <= int(power) <= 12 and _polynomial_syntax(tree[1])
    return False


def scopes(root, path="/root", ancestors=()):
    """Yield (pointer, scope, ancestor pointers) in document order."""
    yield path, root, ancestors
    for index, child in enumerate(root.get("children", [])):
        yield from scopes(child, f"{path}/children/{index}", (*ancestors, path))


def scope_policy(candidate):
    """Reject scalar aliases which capture a quantified variable's name.

    This is a graph-extraction representation check, not an equivalence rewrite:
    the old notation compiler continues to treat the equality literally.
    A model must repair the scoped expression against the image.
    """
    tree = list(scopes(candidate["root"]))
    diagnostics = []
    for path, scope, ancestors in tree:
        # An alias interacts with its ancestors and descendants, never siblings.
        related = [
            item
            for item in tree
            if item[0] in ancestors or item[0] == path or path in item[2]
        ]
        diagnostics.extend(_alias_policy(scope, path, related))
    # Do not partially repair an alias group with unresolved shared meaning.
    if any(item["action"] == "code_gap" for item in diagnostics):
        for item in diagnostics:
            item["action"] = "code_gap"
    return {"ok": not diagnostics, "diagnostics": diagnostics}


def _alias_policy(scope, scope_path, related):
    expressions = [
        (f"{path}/{collection}/{index}", definition(text))
        for path, item, _ in related
        for collection in ("definitions", "facts")
        for index, text in enumerate(item.get(collection, []))
    ]
    quantified = [
        (path, tree)
        for path, expression in expressions
        for tree in _nodes(expression, "quantifier")
    ]
    goals = set()
    for path, item, ancestors in related:
        if path != scope_path and scope_path not in ancestors:
            continue
        for goal in item.get("goals", []):
            if goal['kind'] == 'finite_sum':
                # Sum index binders belong to their own term blocks.
                continue
            if goal['kind'] == 'compare_functions':
                # The dedicated compiler owns option-local function binders;
                # these are not global scalar aliases or parameter targets.
                continue
            if goal['kind'] in ('find_abstract_domain', 'find_abstract_domain_parameter', 'find_abstract_range'):
                # Abstract calls bind a local function identity without a body;
                # known_call / target_call are not global scalar aliases.
                continue
            target = next(
                goal[key] for key in ("symbol", "expression", "object") if key in goal
            )
            goals.update(node[1] for node in _nodes(parse(target), "name"))
    own = {
        f"{scope_path}/{collection}/{index}"
        for collection in ("definitions", "facts")
        for index in range(len(scope.get(collection, [])))
    }
    assignments = []
    for path, tree in expressions:
        if tree[0] != "=":
            continue
        left, right = tree[1:]
        if left[0] == "name":
            assignments.append((path, left[1], right))
        elif right[0] == "name":
            assignments.append((path, right[1], left))
    alias_names = {name for _, name, _ in assignments}
    diagnostics = []
    for path, alias, value in assignments:
        if path not in own:
            continue
        names = {node[1] for node in _nodes(value, "name")}
        dependencies = [(qpath, tree) for qpath, tree in quantified if tree[2] in names]
        if not dependencies:
            continue
        external_use = any(
            other_path != path
            and not _nodes(expression, "quantifier")
            and alias in {node[1] for node in _nodes(expression, "name")}
            for other_path, expression in expressions
        )
        supported = (
            alias not in goals
            and alias not in names
            and not external_use
            and sum(name == alias for _, name, _ in assignments) == 1
            and not names & (alias_names - {alias})
            and _polynomial_syntax(value)
            and len(quantified) == 1
        )
        diagnostic = {
            "stage": "scope_policy",
            "path": path,
            "code": "scope_policy.quantifier_dependent_alias"
            if supported
            else "scope_policy.unsupported_alias_scope",
            "action": "repair" if supported else "code_gap",
            "alias": alias,
            "definition_path": path,
            "bound_variables": sorted({tree[2] for _, tree in dependencies}),
            "quantified_paths": sorted({qpath for qpath, _ in dependencies}),
            "message": (
                "该量词外标量别名等式的右侧含有量词绑定的同名变量，不能把它另存为题设。"
                "按原图将定义直接展开到对应量词体内，删除这个全局别名等式；保留original_text，"
                "保留其它条件及目标，不求解。"
                if supported
                else "该标量赋值与量词变量存在作用域冲突，但别名涉及所求、额外全局约束、递归/链式定义、多个量词或不支持的结构。"
                "当前不能确认可安全采用的表示，不授权删除定义或更改数学关系。"
            ),
        }
        # Deleting the global equality and expanding its quantified use are
        # distinct edits. Neither grants authority over another fact or goal.
        affected_paths = (
            [path, *diagnostic["quantified_paths"]] if supported else [path]
        )
        diagnostics.extend({**diagnostic, "path": target} for target in affected_paths)
    return diagnostics


def validate_candidate(raw):
    """Keep schema and mathematics independent; never manufacture family fields."""
    result = {"contract": contracts.CONTRACT, "contract_valid": False, "reports": {}}
    try:
        candidate = strict_json(raw) if isinstance(raw, str) else raw
    except (ValueError, RecursionError) as exc:
        result["reports"]["json"] = {"ok": False, "issues": [str(exc)]}
        return result
    errors = list(Draft202012Validator(contracts.schema()).iter_errors(candidate))
    if errors:
        result["reports"]["ir"] = {
            "ok": False,
            "issues": [
                {
                    "path": "/" + "/".join(map(str, e.absolute_path)),
                    "code": "schema.invalid",
                    "message": e.message,
                }
                for e in errors[:32]
            ],
        }
        return result
    result["revision"] = revision(candidate)
    report = NotationValidator().validate_root(
        candidate["root"], contracts.schema()["$defs"]
    )
    result["reports"]["ir"] = report.payload()
    if report.ok:
        try:
            result["canonical"] = canonical(report)
        except (ValueError, TypeError, RecursionError) as exc:
            result["reports"]["ir"]["ok"] = False
            result["reports"]["ir"]["issues"].append(
                {
                    "path": "/root",
                    "code": "notation.semantic_invalid",
                    "message": str(exc),
                }
            )
    policy = scope_policy(candidate) if report.ok else {"ok": True, "diagnostics": []}
    result["reports"]["scope_policy"] = policy
    result["compiled"] = {
        "root": report.semantic,
        "objects": report.objects,
        "source_locations": report.source_locations,
        "normalization_report": report.normalization_report,
    }
    result["contract_valid"] = result["reports"]["ir"]["ok"] and policy["ok"]
    return result


class GraphStageOneContract(MathNotationWorkflowContract):
    def validate_request(self, request, registry, mode):
        if (
            registry
            or request.contract_version != contracts.CONTRACT
            or request.contract_schema != contracts.schema()
        ):
            raise WorkflowStop("workflow.unsupported_or_stale_contract")

    def schema(self):
        return contracts.schema()

    def frozen_files(self):
        return frozen_files()

    def parse(self, raw, *, problem_id, source_hash, registry, store):
        parsed = validate_candidate(raw)
        parsed["binding"] = {"problem_id": problem_id, "source_sha256": source_hash}
        if store:
            store.put_bytes(
                kind="graph_stage_one_raw",
                content=raw.encode(),
                media_type="text/plain",
                suffix=".txt",
            )
            store.put_json(kind="graph_stage_one_validation", payload=parsed)
        return parsed

    def request_for(
        self,
        base,
        stage,
        candidate,
        registry,
        diagnostics=(),
        feedback=(),
        *,
        validation=None,
    ):
        is_review = stage == "review"
        payload = {
            "response_schema": contracts.review_schema()
            if is_review
            else contracts.schema(),
            "math_expression_catalog": contracts.expression_catalog(),
            "candidate" if is_review else "base_candidate": candidate,
        }
        if is_review:
            payload["code_validation"] = {
                "candidate_revision": revision(candidate),
                "notation_valid": bool(
                    validation and validation["contract_valid"]
                ),
                "image_alignment_verified": False,
            }
            if feedback:
                payload["review_feedback"] = list(feedback)
        else:
            payload.update(
                diagnostics=list(diagnostics), repair_feedback=list(feedback)
            )
        return replace(
            base,
            contract_version=contracts.REVIEW_CONTRACT
            if is_review
            else contracts.CONTRACT,
            contract_schema=payload["response_schema"],
            prompt=MultimodalExtractionPrompt(
                contracts.REVIEW_SYSTEM if is_review else contracts.REPAIR_SYSTEM,
                json.dumps(payload, ensure_ascii=False),
                "对照本次完整题图，只返回指定 Schema 的 JSON。",
            ),
        )

    def validate_review(self, raw, candidate):
        review = strict_json(raw)
        Draft202012Validator(contracts.review_schema()).validate(review)
        for finding in review["findings"]:
            path = finding["path"]
            if not path or not path.startswith(("/root", "/original_text")):
                raise ValueError("review.invalid_pointer")
            pointer(candidate, path)
            if finding["kind"] == "wrong_transcription" and path != "/original_text":
                raise ValueError("review.invalid_transcription_pointer")
        return review

    def invalid_review_feedback(self):
        return [
            {
                "code": "review.invalid_response",
                "message": "上一轮复核响应未通过严格格式校验。请重新对照原图复核同一candidate，"
                "只输出status和findings两个顶层字段。不得输出candidate、root或修改后的题意；"
                "需要改题意时仅在findings报告问题。必须输出完整JSON。",
            }
        ]

    def diagnose(self, parsed, candidate):
        diagnoses = math_diagnose(parsed, candidate)
        issues = parsed["reports"].get("json", {}).get("issues", [])
        if issues:
            return [{**item, "issues": issues, "message": JSON_REPAIR} for item in diagnoses]
        diagnoses.extend(
            parsed["reports"].get("scope_policy", {}).get("diagnostics", [])
        )
        return diagnoses

    def review_diagnostics(self, review, candidate):
        return review_diagnostics(review, candidate)

    def repair_diagnostics(self, current, proposed, diagnostics):
        try:
            violations = repair_violations(current, proposed, diagnostics)
        except AmbiguousScopeMapping as exc:
            return [
                {
                    "code": "repair.ambiguous_scope_mapping",
                    "path": path,
                    "message": "多个小问的数学内容不足以唯一确定修复前后的对应，不能猜测局部授权归属。"
                    "请先仅修复分问层次或顺序、保留各问数学内容，复核后再修复局部条件或目标；"
                    "无法确认对应时在uncertainties中说明。",
                }
                for path in exc.paths
            ]
        return [
            {"code": "repair.outside_authorized_path", "path": path, "message": REPAIR_SCOPE}
            for path in violations
        ]

    def result_fields(self, current):
        return {"output_contract": contracts.CONTRACT}

    def continuation_fields(self, current):
        return {}


class StageOneStorage(FileWorkflowStorage):
    """Retain rejected as well as adopted candidates for human debugging."""

    def proposed(self, candidate, parsed, number):
        save(
            self.directory.parent / "candidates" / f"{number:02d}-proposed.json",
            candidate,
        )
        save(
            self.directory.parent / "candidates" / f"{number:02d}-validation.json",
            parsed,
        )

    def adopt(self, candidate, parsed, number):
        save(
            self.directory.parent / "candidates" / f"{number:02d}-adopted.json",
            candidate,
        )
