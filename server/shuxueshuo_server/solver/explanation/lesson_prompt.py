"""Versioned teaching templates and source-bound, read-only route context."""

import json
from hashlib import sha256
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from shuxueshuo_server.solver.family import (
    BASIC_INEQUALITY_FAMILY,
    DEFAULT_FAMILY_REGISTRY,
)
from shuxueshuo_server.solver.runtime._paths import repo_root

TEMPLATE_ROOT = Path(__file__).with_name("prompts")
# Teaching admission does not enable a production solver Family.
TEACHING_FAMILIES = {
    family.family_id: family
    for family in (*DEFAULT_FAMILY_REGISTRY.families, BASIC_INEQUALITY_FAMILY)
}


def _read_asset(path, asset_id):
    raw = path.read_bytes()  # Missing declared resources are configuration errors.
    return raw.decode("utf-8").rstrip("\n"), {
        "id": asset_id,
        "sha256": sha256(raw).hexdigest(),
    }


def _routes(payload, authority):
    """Keep references local to their exact Scope/Goal, after rule composition."""
    routes = []

    def container(scope_ref, goal_ref, steps):
        ref = f"goal:{goal_ref}" if goal_ref else f"scope:{scope_ref}"
        materials = [m for step in steps for m in step.get("materials", [])]
        if not materials:
            return
        records = authority["containers"][ref]
        if [m["step_ref"] for m in materials] != [r["teaching_step_ref"] for r in records]:
            raise ValueError("lesson_route_material_reference_mismatch")
        route = {"scope_ref": scope_ref, "steps": []}
        if goal_ref:
            route["goal_ref"] = goal_ref
        for material, record in zip(materials, records, strict=True):
            step = {
                "source_steps": [material["step_ref"]],
                "purpose": material["goal"],
                "title": record.get("fixed_title", material["title"]),
            }
            if record.get("section_label"):
                step["approach"] = record["section_label"]
            route["steps"].append(step)
        routes.append(route)

    def visit(scope):
        container(scope["scope_ref"], None, scope.get("steps", []))
        for goal_ref, steps in scope.get("goals", {}).items():
            container(scope["scope_ref"], goal_ref, steps)
        for child in scope.get("children", []):
            visit(child)

    visit(payload["root_scope"])
    return routes


class _AuditedLoader(FileSystemLoader):
    """Record every template actually loaded, including dynamic includes."""

    def __init__(self, root):
        super().__init__(root)
        self.assets = {}

    def get_source(self, environment, template):
        source, filename, uptodate = super().get_source(environment, template)
        self.assets[template] = {
            "id": template,
            "sha256": sha256(Path(filename).read_bytes()).hexdigest(),
        }
        return source.rstrip("\n"), filename, uptodate


def render_lesson_prompt(payload, authority, *, output_schema, boundaries, families=None):
    """Prepare validated data; Jinja owns prompt wording, layout and includes."""
    data_assets = []
    registry = TEACHING_FAMILIES if families is None else families
    family = registry.get(authority.get("family_id"))
    strategy = None
    if family and family.strategy_reference:
        text, asset = _read_asset(repo_root() / family.strategy_reference, family.strategy_reference)
        reference = json.loads(text)
        if reference.get("family_id") != family.family_id:
            raise ValueError("lesson_family_strategy_identity_mismatch")
        # Project only mathematical vocabulary, never planner dispatch/protocol.
        overview = reference["strategy_overview"]
        methods = [{key: method[key] for key in (
            "name", "definition", "when_to_use", "combination_note"
        )} for method in reference["methods"]]
        if not isinstance(overview, str) or not overview.strip() or not methods or any(
            not isinstance(v, str) or not v.strip() for method in methods for v in method.values()
        ):
            raise ValueError("lesson_family_strategy_invalid")
        strategy = {"strategy_overview": overview, "methods": methods}
        data_assets.append(asset)
    context = {
        "family_template": family.teaching_template if family else None,
        "strategy": strategy,
        "routes": _routes(payload, authority)
        if family and (family.teaching_template or family.strategy_reference) else None,
        "plan": payload,
        "output_schema": output_schema,
        "boundaries": boundaries,
    }
    # A fresh environment records includes for this request and avoids stale
    # template caches during authoring. Data is never rendered a second time.
    loader = _AuditedLoader(TEMPLATE_ROOT)
    environment = Environment(loader=loader, undefined=StrictUndefined, autoescape=False)
    environment.filters["compact_json"] = lambda value: json.dumps(
        value, ensure_ascii=False, separators=(",", ":")
    )
    system = environment.get_template("system-v1.jinja").render(context)
    user = environment.get_template("user-v1.jinja").render(context)
    return system, user, (*loader.assets.values(), *data_assets)
