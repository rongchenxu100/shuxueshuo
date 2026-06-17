"""Role binder registry for ExplanationBuilder teaching drafts."""

from __future__ import annotations

from dataclasses import dataclass

from .methods import MethodRoleBinder, method_role_binders
from .recipes import RecipeRoleBinder, recipe_role_binders


class RoleBindingError(ValueError):
    """Raised when an explanation spec references an unknown role binder."""


@dataclass(frozen=True)
class RoleBinderRegistry:
    """Registry for method and recipe explanation role binders."""

    method_binders: dict[str, MethodRoleBinder]
    recipe_binders: dict[str, RecipeRoleBinder]

    @classmethod
    def default(cls) -> "RoleBinderRegistry":
        return cls(
            method_binders=method_role_binders(),
            recipe_binders=recipe_role_binders(),
        )

    def require_method(self, binder_id: str) -> MethodRoleBinder:
        binder = self.method_binders.get(binder_id)
        if binder is None:
            raise RoleBindingError(f"unknown method role_binder_id: {binder_id}")
        return binder

    def require_recipe(self, binder_id: str) -> RecipeRoleBinder:
        binder = self.recipe_binders.get(binder_id)
        if binder is None:
            raise RoleBindingError(f"unknown recipe role_binder_id: {binder_id}")
        return binder


__all__ = [
    "MethodRoleBinder",
    "RecipeRoleBinder",
    "RoleBinderRegistry",
    "RoleBindingError",
]
