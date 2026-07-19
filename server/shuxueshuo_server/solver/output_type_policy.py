"""Shared output-type policy constants."""

from __future__ import annotations


TRANSIENT_OUTPUT_TYPES = frozenset({"Point", "PointList", "ParameterValue"})


__all__ = ["TRANSIENT_OUTPUT_TYPES"]
