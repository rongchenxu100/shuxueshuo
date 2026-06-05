"""Strategy Planner prompt payload 与 debug artifact。

本模块负责把 LLM ProblemIR、FamilySpec、method/recipe catalog 与 schema 渲染成
DeepSeek probe 使用的 prompt，并写出调试文件。
"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY, FamilyRegistry
from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.question_goals import extract_question_goals
from shuxueshuo_server.solver.runtime._paths import repo_root
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.context_inventory import ContextInventory
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.strategy_few_shots import (
    query_goal_types_from_problem,
    select_few_shot_examples,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ExecutablePlanResolutionReport,
    STEP_INTENT_JSON_SCHEMA,
    StepIntentDraft,
    StepIntentNormalizationReport,
    StepIntentValidationReport,
    StrategyPrompt,
)
from shuxueshuo_server.solver.runtime.strategy_resolver import (
    _method_capability_summary,
)

class StrategyPayloadBuilder:
    """把 PlannerInputs 压缩成 LLM 可读的 probe payload。

    Phase 1 不再把 RuntimeContext 拆成 scope/relation/signal 多张工程表，而是把
    结构化 ProblemIR 作为主要读题材料直接交给 LLM。这样模型更像在读题，而不是
    在做 ContextPath 查表。
    """

    def __init__(
        self,
        *,
        few_shot_examples: list[dict[str, Any]] | None = None,
        few_shot_dir: Path | str | None = None,
        allow_same_problem_few_shot: bool = True,
        problem_payload: dict[str, Any] | None = None,
    ) -> None:
        self.few_shot_examples = few_shot_examples
        self.few_shot_dir = Path(few_shot_dir) if few_shot_dir is not None else None
        self.allow_same_problem_few_shot = allow_same_problem_few_shot
        self.problem_payload = problem_payload

    def build(
        self,
        inputs: PlannerInputs,
        *,
        problem_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """生成 prompt payload；每个顶层字段都对应一个可独立 fake 的来源。"""
        problem_payload = problem_payload or self.problem_payload
        if problem_payload is None:
            if inputs.problem is not None:
                problem_payload = problem_to_llm_payload(inputs.problem)
            else:
                raise ValueError(
                    "StrategyPayloadBuilder requires canonical problem payload; "
                    "StrategyPlanner should provide it via RuntimeProjection"
                )
        method_ids = inputs.family_spec.method_ids or tuple(
            sorted(inputs.method_specs.specs)
        )
        # 显式传入的 LLM ProblemIR 是 prompt 的唯一题目事实源。这里在 payload 边界
        # 校验，避免旧 solver fixture 的 relations/target_path 等字段混入 LLM 链路。
        CanonicalHandleRegistry.from_problem_payload(problem_payload)
        return {
            "problem_id": inputs.problem_id,
            "family_id": inputs.family_spec.family_id,
            "problem_ir": dict(problem_payload),
            "family_spec": _family_spec_payload(inputs.family_spec),
            "method_catalog": _method_catalog_payload(
                inputs.method_specs,
                method_ids,
            ),
            "recipe_catalog": _recipe_catalog_payload(inputs.family_spec),
            "few_shot_examples": self._few_shot_examples(inputs, problem_payload),
            "previous_attempts": list(inputs.previous_errors),
            "output_json_schema": STEP_INTENT_JSON_SCHEMA,
        }

    def _few_shot_examples(
        self,
        inputs: PlannerInputs,
        problem_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """选择 few-shot；显式注入优先，目录无命中则回退虚构示例。"""
        if self.few_shot_examples is not None:
            return self.few_shot_examples
        query_goal_types = query_goal_types_from_problem(
            problem_payload=problem_payload,
            question_goals=inputs.question_goals,
        )
        selected = select_few_shot_examples(
            family_id=inputs.family_spec.family_id,
            goal_types=query_goal_types,
            problem_id=inputs.problem_id,
            allow_same_problem=self.allow_same_problem_few_shot,
            top_k=1,
            few_shot_dir=self.few_shot_dir,
        )
        if selected:
            return selected
        return _default_few_shot_examples(inputs.family_spec.family_id)


class StrategyPromptRenderer:
    """渲染 Strategy Planner 的 system/user prompt。"""

    def __init__(self, template_dir: Path | str | None = None) -> None:
        self.template_dir = Path(template_dir) if template_dir else _default_template_dir()
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters["pretty_json"] = _pretty_json

    def render(self, payload: dict[str, Any]) -> StrategyPrompt:
        """把分来源 payload 渲染成 Chat messages。"""
        system = self.env.get_template("strategy-system.jinja").render(
            output_json_schema=STEP_INTENT_JSON_SCHEMA,
        )
        user = self.env.get_template("strategy-user.jinja").render(payload=payload)
        return StrategyPrompt(system=system.strip(), user=user.strip())

def build_strategy_probe_inputs(
    problem: ProblemIR,
    *,
    family_registry: FamilyRegistry = DEFAULT_FAMILY_REGISTRY,
) -> PlannerInputs:
    """构建 Phase 1 DeepSeek probe 所需的 PlannerInputs。

    Strategy prompt 消费 canonical ProblemIR 投影后的 LLM payload，因此这里不再
    构建 ``ContextInventory`` 的 visible paths / planning signals；保留空 inventory
    只是为了复用 ``PlannerInputs`` 这个输入包。
    """
    family = family_registry.match(problem)
    if family is None:
        raise ValueError(
            f"no solver family for pattern={problem.pattern}, type={problem.problem_type}"
        )
    specs = MethodSpecRegistry.load_from_code()
    question_goals = extract_question_goals(problem)
    return PlannerInputs(
        problem_id=problem.problem_id,
        family_spec=family,
        question_goals=question_goals,
        context_inventory=ContextInventory(),
        method_specs=specs,
        problem=problem,
        original_text=dict(problem.original_text),
        previous_errors=[],
    )

def write_strategy_debug_artifacts(
    debug_dir: Path | str,
    *,
    payload: dict[str, Any],
    prompt: StrategyPrompt,
    raw_response: str,
    draft: StepIntentDraft | None,
    report: StepIntentValidationReport,
    normalization_report: StepIntentNormalizationReport | None = None,
    resolution_report: ExecutablePlanResolutionReport | None = None,
    llm_metadata: dict[str, Any] | None = None,
) -> None:
    """把 DeepSeek probe 的输入输出按来源落盘，方便人工 review prompt。"""
    target = Path(debug_dir)
    target.mkdir(parents=True, exist_ok=True)
    _clear_previous_debug_artifacts(target)
    (target / "prompt.system.md").write_text(prompt.system, encoding="utf-8")
    (target / "prompt.user.md").write_text(prompt.user, encoding="utf-8")
    source_keys = [
        "problem_ir",
        "family_spec",
        "method_catalog",
        "recipe_catalog",
        "few_shot_examples",
        "previous_attempts",
    ]
    for key in source_keys:
        _write_json(target / f"payload.{key}.json", payload.get(key))
    _write_json(target / "output.schema.json", STEP_INTENT_JSON_SCHEMA)
    (target / "raw-response.txt").write_text(raw_response, encoding="utf-8")
    _write_json(
        target / "parsed-step-intents.json",
        draft.to_payload() if draft else None,
    )
    _write_json(target / "validation-report.json", report.to_payload())
    if normalization_report is not None:
        _write_json(target / "normalization-report.json", normalization_report)
        _write_json(
            target / "normalized-step-intents.json",
            draft.to_payload() if draft else None,
        )
    if report.handle_resolution is not None:
        _write_json(target / "handle-resolution-report.json", report.handle_resolution)
    if report.recipe_alignment is not None:
        _write_json(target / "recipe-alignment.json", report.recipe_alignment)
    if resolution_report is not None:
        _write_json(
            target / "candidate-resolution-report.json",
            resolution_report,
        )
    if llm_metadata is not None:
        _write_json(target / "llm-call.json", llm_metadata)


def _clear_previous_debug_artifacts(target: Path) -> None:
    """清理同一 probe 目录里的旧版 payload，避免人工 review 看到过期文件。"""
    for pattern in ("payload.*.json",):
        for path in target.glob(pattern):
            path.unlink()
    for name in (
        "prompt.system.md",
        "prompt.user.md",
        "output.schema.json",
        "raw-response.txt",
        "parsed-step-intents.json",
        "validation-report.json",
        "normalization-report.json",
        "normalized-step-intents.json",
        "handle-resolution-report.json",
        "recipe-alignment.json",
        "candidate-resolution-report.json",
        "llm-call.json",
    ):
        path = target / name
        if path.exists():
            path.unlink()

def _family_spec_payload(family: SolverFamilySpec) -> dict[str, Any]:
    """把 FamilySpec 中的题型策略字段压成 prompt payload。"""
    return {
        "family_id": family.family_id,
        "common_goal_types": list(family.common_goal_types),
        "strategy_principles": list(family.strategy_principles),
        "method_ids": list(family.method_ids),
    }


def _method_catalog_payload(
    specs: MethodSpecRegistry,
    method_ids: tuple[str, ...],
) -> dict[str, Any]:
    """生成当前 family 可见的 method 能力摘要。

    StepIntent 阶段不要求 LLM 绑定 method input slot，因此这里只给“这项能力能做
    什么”的短摘要，不给完整 MethodSpec schema。完整输入输出槽位仍由后续 resolver
    和 PlanValidator 在代码层使用。
    """
    methods: list[dict[str, Any]] = []
    missing: list[str] = []
    for method_id in method_ids:
        try:
            spec = specs.require(method_id)
        except KeyError:
            missing.append(method_id)
            continue
        methods.append(
            {
                "method_id": spec.method_id,
                "title": spec.title,
                "solves": list(spec.solves),
                "summary": _method_capability_summary(spec),
            }
        )
    return {
        "methods": methods,
        "missing_method_ids": missing,
    }


def _recipe_catalog_payload(family: SolverFamilySpec) -> dict[str, Any]:
    """生成当前 family 的 recipe 菜单摘要。

    这里完整输出 family 配置的 recipe，不做题内 top-k。LLM 需要看到的是“这类题
    推荐有哪些标准动作”，具体某一步最终能否执行由后续 resolver/trial 验算。
    """
    return {
        "recipes": [
            {
                "recipe_id": recipe.recipe_id,
                "goal_type": recipe.goal_type,
                "title": recipe.title,
                "description": recipe.description,
                "method_ids": list(recipe.method_ids),
                **({"priority": recipe.priority} if recipe.priority else {}),
            }
            for recipe in family.step_recipes
        ]
    }

def _default_few_shot_examples(family_id: str) -> list[dict[str, Any]]:
    """提供虚构 few-shot，只展示 recipe 范式，不给当前题完整答案。"""
    return [
        {
            "family_id": family_id,
            "note": (
                "这是虚构简化场景，只展示路径最值 recipe 的意图格式；不要照抄"
                "题号、点名、handle 或答案。"
            ),
            "scopes": [
                {
                    "scope_id": "demo_i",
                    "label": "虚构示例：先产生全题公共结论",
                    "steps": [
                        {
                            "step_id": "derive_anchor_coordinate",
                            "recipe_hint": "quadratic_axis_from_relation",
                            "goal_type": "derive_constructed_point",
                            "target": "fact:problem:anchor_coordinate",
                            "strategy": "先求出后续全题都会用到的公共点坐标。",
                            "reads": [
                                "point:problem:Anchor",
                                "fact:problem:coefficient_relation",
                            ],
                            "creates": [],
                            "produces": [
                                {
                                    "handle": "fact:problem:anchor_coordinate",
                                    "valid_scope": "problem",
                                    "description": "公共点 Anchor 的坐标结论，后续 scope 只 reads 复用",
                                    "output_type": "Point",
                                }
                            ],
                            "reason": (
                                "公共结论只 produces 一次；后续步骤需要时直接 reads "
                                "fact:problem:anchor_coordinate。"
                            ),
                        }
                    ],
                },
                {
                    "scope_id": "demo",
                    "label": "虚构示例：路径最值公共步骤",
                    "steps": [
                        {
                            "step_id": "reduce_two_moving_points_path",
                            "recipe_hint": "two_moving_points_path_reduction",
                            "goal_type": "reduce_path_expression",
                            "target": "fact:demo:single_moving_path_equivalence",
                            "strategy": "利用两个动点之间的线段比例和所在轨迹，把双动点路径转化为等价单动点折线路径。",
                            "reads": [
                                "point:problem:Anchor",
                                "fact:problem:anchor_coordinate",
                                "fact:demo:path_target",
                                "fact:demo:first_moving_point_on_segment",
                                "fact:demo:second_moving_point_on_segment",
                                "fact:demo:segment_ratio_relation",
                            ],
                            "creates": [],
                            "produces": [
                                {
                                    "handle": "fact:demo:single_moving_path_equivalence",
                                    "valid_scope": "demo",
                                    "description": "双动点路径已经转化成只含一个动点的等价折线路径",
                                    "output_type": "PathTransformation",
                                }
                            ],
                            "reason": (
                                "路径最值先降维，避免直接把两个动点都参数化。示例中"
                                " point:problem:Anchor 虽在 demo scope 使用，也必须原样引用"
                                " problem scope 的 canonical handle。"
                            ),
                        },
                        {
                            "step_id": "straighten_reduced_path",
                            "recipe_hint": "broken_path_straightening_and_select",
                            "goal_type": "straighten_broken_path",
                            "target": "fact:demo:straightened_path_choice",
                            "strategy": "对等价折线路径构造拉直候选，并选择最方便计算的拉直方案。",
                            "reads": [
                                "fact:demo:single_moving_path_equivalence",
                                "segment:demo:motion_segment",
                            ],
                            "creates": [
                                {
                                    "handle": "point:demo:Aux",
                                    "entity_type": "point",
                                    "valid_scope": "demo",
                                    "description": "用于折线拉直的辅助点",
                                }
                            ],
                            "produces": [
                                {
                                    "handle": "fact:demo:straightened_path_choice",
                                    "valid_scope": "demo",
                                    "description": "已经选定可计算的折线拉直方案",
                                    "output_type": "StraighteningCandidate",
                                }
                            ],
                            "reason": "单动点折线最短路径通常通过拉直处理。",
                        },
                        {
                            "step_id": "compute_straightened_minimum",
                            "recipe_hint": "path_minimum_by_straightened_distance",
                            "goal_type": "derive_minimum_value",
                            "target": "fact:demo:path_minimum_value_expr",
                            "strategy": "在拉直方案确定后，用对应端点间距离得到路径最小值表达式。",
                            "reads": [
                                "fact:demo:straightened_path_choice",
                                "point:demo:Aux",
                            ],
                            "creates": [],
                            "produces": [
                                {
                                    "handle": "fact:demo:path_minimum_value_expr",
                                    "valid_scope": "demo",
                                    "description": "路径最小值表达式",
                                    "output_type": "MinimumExpression",
                                }
                            ],
                            "reason": "拉直后的最短路径转化为端点间距离。",
                        },
                    ],
                },
            ],
        }
    ]

def _pretty_json(value: Any) -> str:
    """Jinja 过滤器：输出可读中文 JSON。"""
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _write_json(path: Path, value: Any) -> None:
    """写入 pretty JSON。"""
    path.write_text(_pretty_json(_to_jsonable(value)) + "\n", encoding="utf-8")


def _to_jsonable(value: Any) -> Any:
    """把 dataclass/tuple 转成 JSON 友好对象。"""
    if hasattr(value, "to_payload"):
        return value.to_payload()
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    return value


def _default_template_dir() -> Path:
    """定位 internal/llm-prompts，避免硬编码固定 parents 层级。"""
    return repo_root(Path(__file__)) / "internal" / "llm-prompts"
