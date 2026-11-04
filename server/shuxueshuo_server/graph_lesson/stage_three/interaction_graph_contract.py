"""Validate the JSON drawing protocol before publishing or attaching a graph."""

import json
import math
from functools import lru_cache

from jsonschema import Draft202012Validator

from .contracts import ROOT

SCHEMA = ROOT / "internal/schemas/graph-step-interaction-v1.schema.json"


@lru_cache(maxsize=4)
def _validator(source):
    schema = json.loads(source)
    return Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/graph"})


def _finite_numbers(value):
    if isinstance(value, dict):
        for child in value.values():
            _finite_numbers(child)
    elif isinstance(value, list):
        for child in value:
            _finite_numbers(child)
    elif type(value) in (int, float):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("interaction.graph_nonfinite")


def _ordered(low, high):
    try:
        valid = low < high and math.isfinite(high - low)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("interaction.graph_invalid_bounds")


def _interval(ends, closed):
    if any(end is None and included for end, included in zip(ends, closed, strict=True)):
        raise ValueError("interaction.graph_closed_infinity")
    if all(end is not None for end in ends):
        _ordered(*ends)


def validate_graph(graph):
    """Reject malformed shapes and values that cannot be represented faithfully in JS."""
    # Key the cached validator by schema contents, so edits/tests cannot reuse a
    # stale validator under the same path or filesystem timestamp.
    _validator(SCHEMA.read_text()).validate(graph)
    _finite_numbers(graph)
    params = graph["params"]
    bounds = params["bounds"]
    for index in range(0, len(bounds), 2):
        _ordered(bounds[index], bounds[index + 1])
    if graph["kind"] == "number_line":
        for piece in params["pieces"]:
            _interval([piece["from"], piece["to"]], [piece["left_closed"], piece["right_closed"]])
    else:
        _interval(params["interval"], params["interval_closed"])
        if graph['kind'] == 'piecewise_curve':
            for segment in [*params['segments'], *params.get('reference', [])]:
                _interval(segment['interval'], segment['interval_closed'])
            for piece in [*params.get('highlights', []), *params.get('interval_marks', [])]:
                _interval([piece['from'], piece['to']], [piece['left_closed'], piece['right_closed']])
        if graph['kind'] == 'absolute_affine' and 'reference' in params:
            reference = params['reference']
            _interval(reference['interval'], reference['interval_closed'])
        if graph["kind"] == "reciprocal_sum" and any(point["x"] == 0 for point in params["points"]):
            raise ValueError("interaction.graph_undefined_point")
        if graph["kind"] == "reciprocal_sum":
            for piece in params.get("pieces", []):
                _interval([piece["from"], piece["to"]], [piece["left_closed"], piece["right_closed"]])
                low = piece["from"] if piece["from"] is not None else -math.inf
                high = piece["to"] if piece["to"] is not None else math.inf
                if (low < 0 < high or low == 0 and piece["left_closed"] or
                        high == 0 and piece["right_closed"]):
                    raise ValueError("interaction.graph_reciprocal_pole")
        if graph["kind"] == "axis_explorer":
            axis = params["axis"]
            _ordered(axis["min"], axis["max"])
            if not axis["min"] <= axis["value"] <= axis["max"]:
                raise ValueError("interaction.graph_axis_outside_track")
    return graph


def validate_part_graphs(parts):
    """All graph locations in the interaction protocol, including checklist options."""
    for part in parts:
        for field in ("graph", "completion_graph"):
            if field in part:
                validate_graph(part[field])
        for graph in part.get("completion_graphs", []):
            validate_graph(graph)
        component = part["interaction"]
        for option in component.get("options", []):
            if "graph" in option:
                validate_graph(option["graph"])
        for slot in component.get("slots", []):
            for option in slot["options"]:
                if "graph" in option:
                    validate_graph(option["graph"])
