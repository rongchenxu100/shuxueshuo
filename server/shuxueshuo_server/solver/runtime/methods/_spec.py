"""MethodSpec 的代码源。

MethodSpec JSON 不再手写维护，而是从每个 method 文件里的 ``SPEC`` 生成。
``description`` 默认取 method class 的 docstring 首段，因此 method 的能力说明会和
代码注释待在一起。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import inspect


@dataclass(frozen=True)
class MethodSpecSource:
    """一个 method 文件内的结构化 MethodSpec 源。

    ``method_cls`` 提供 method_id 和 docstring；其他字段提供 validator 需要的
    输入、输出、solves 和前后置条件。
    """

    method_cls: type
    title: str
    solves: tuple[str, ...]
    inputs: dict[str, dict[str, Any]]
    outputs: dict[str, str]
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    trace_template: tuple[str, ...] = ()
    description: str = ""

    @property
    def method_id(self) -> str:
        return str(self.method_cls.method_id)

    def to_payload(self) -> dict[str, Any]:
        description = self.description or _first_docstring_paragraph(self.method_cls)
        payload: dict[str, Any] = {
            "method_id": self.method_id,
            "title": self.title,
            "description": description,
            "solves": list(self.solves),
            "inputs": self.inputs,
            "outputs": self.outputs,
        }
        if self.preconditions:
            payload["preconditions"] = list(self.preconditions)
        if self.postconditions:
            payload["postconditions"] = list(self.postconditions)
        if self.trace_template:
            payload["trace_template"] = list(self.trace_template)
        return payload


def _first_docstring_paragraph(method_cls: type) -> str:
    doc = inspect.getdoc(method_cls) or ""
    return doc.split("\n\n", 1)[0]
