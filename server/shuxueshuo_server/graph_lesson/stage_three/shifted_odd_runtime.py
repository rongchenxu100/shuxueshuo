"""T6's own M5 branch; source goals and parameter roles survive every stage."""

from copy import deepcopy

from ..shifted_odd_math import name, parse_sources, solve, verify
from .capabilities import CapabilityGap, LocalCheckFailed, result
from .goals import _exact_math
from .math_values import math_value
from .trajectory import decode_value, encode_value


def model(description):
    try:
        return solve(description)
    except (ValueError, NotImplementedError) as exc:
        raise CapabilityGap(str(exc)) from exc


def check_domain(description):
    m = model(description)
    return result(
        {
            "domain_evidence": {
                "domain": m["domain"],
                "identity": m["identity"],
                "existence": m["existence"],
            }
        },
        [],
        [{"kind": "original_input_domains_and_consistency", "passed": True}],
    )


def rewrite(description):
    m = model(description)
    return result(
        {"rewrite": {"K": m["K"], "maps": m["maps"], "identity": m["identity"]}},
        [],
        [{"kind": "source_bound_offset_relation", "passed": True}],
    )


def evaluate(description, rewrite):
    m = model(description)
    if rewrite != {"K": m["K"], "maps": m["maps"], "identity": m["identity"]}:
        raise LocalCheckFailed("shifted_odd.relation_changed")
    return result(
        {
            "rule_values": {
                "groups": m["groups"],
                "existence": m["existence"],
                "extrema": m["extrema"],
            }
        },
        [],
        [{"kind": "original_target_and_attainment", "passed": True}],
    )


def confirm(description, rewrite, rule_values):
    m = model(description)
    if (
        rewrite != {"K": m["K"], "maps": m["maps"], "identity": m["identity"]}
        or rule_values
        != {"groups": m["groups"], "existence": m["existence"], "extrema": m["extrema"]}
        or not verify(description, m)
    ):
        raise LocalCheckFailed("shifted_odd.certificate_failed")
    return result(
        {"symmetry_result": m},
        [],
        [{"kind": "shifted_odd_target_certified", "passed": True}],
    )


def finish(state, context, previous):
    m = decode_value(state["symmetry_result_exact"])
    d = context["shifted_odd_goal"]
    if not verify(d, m):
        raise LocalCheckFailed("shifted_odd.finalization_failed")
    determined = m["proof"]["status"] == "determined"
    sources = parse_sources(d)
    f = name(
        next(
            (r for r in sources["refs"] if r not in sources["odd"]), sources["refs"][0]
        )
    )
    answer = {
        "kind": d["source"]["kind"],
        "status": "complete" if determined else "insufficient_information",
        "result_type": "finite_sum"
        if d["source"]["kind"] == "finite_sum"
        else "scalar_value",
        "defined": True,
        "domain": math_value(m["domain"])
        if m["domain"] is not None
        else {"expression": "Dom(" + f + ")", "latex": "D_{" + f + "}"},
        "value": math_value(m["proof"]["value"]) if determined else None,
        "expression": None,
        "is_constant": None,
    }
    if d["source"]["kind"] in ("find_range", "find_extrema_expression"):
        # The certificate proves the requested sum, not the individual extrema
        # or the complete image set. Preserve the existing answer-request wire format.
        if not determined or not m["extrema"]:
            raise CapabilityGap("shifted_odd.extrema_sum_undetermined")
        answer = {"kind": "find_extrema_expression", "status": "value",
                  "value": _exact_math(m["proof"]["value"])}
        if "answer_request" in d["source"]:
            answer.update(kind="derived_answer", request_kind="expression")
    consistency = (
        "conflict"
        if any(
            r["status"] == "verified" and r.get("answer") != answer for r in previous
        )
        else "consistent"
    )
    return {
        "state": deepcopy(state),
        "answer": answer,
        "symmetry_result_exact": encode_value(m),
        "consistency": consistency,
    }
