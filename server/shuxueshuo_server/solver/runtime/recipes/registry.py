"""RecipeSpec 注册表。"""

from __future__ import annotations

from ._spec import RecipeSpec, RecipeSpecSource, recipe_spec_from_source


class RecipeSpecRegistry:
    """内存中的 RecipeSpec 注册表。"""

    def __init__(self, specs: dict[str, RecipeSpec]) -> None:
        self.specs = specs

    @classmethod
    def load_from_code(cls) -> "RecipeSpecRegistry":
        from shuxueshuo_server.solver.runtime.recipes import ALL_RECIPE_SPEC_SOURCES

        specs: dict[str, RecipeSpec] = {}
        for source in ALL_RECIPE_SPEC_SOURCES:
            spec = recipe_spec_from_source(source)
            if spec.recipe_id in specs:
                raise ValueError(f"duplicate recipe_id: {spec.recipe_id}")
            specs[spec.recipe_id] = spec
        return cls(specs)

    def get(self, recipe_id: str) -> RecipeSpec | None:
        return self.specs.get(recipe_id)


def recipe_spec_payloads() -> list[dict]:
    from shuxueshuo_server.solver.runtime.recipes import ALL_RECIPE_SPEC_SOURCES

    return [source.to_payload() for source in ALL_RECIPE_SPEC_SOURCES]


__all__ = ["RecipeSpecRegistry", "recipe_spec_payloads"]
