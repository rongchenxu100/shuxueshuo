"""Full-expression rows with a highlighted local operation, from verified data."""


def expression_row(expression, *, focus=None, label="", relation=""):
    parts = []
    if focus:
        if expression.count(focus) != 1:
            raise ValueError("expression_flow_focus_not_unique")
        before, after = expression.split(focus)
        if before:
            parts.append({"expression": before})
        parts.append({"expression": focus, "highlight": True})
        if after:
            parts.append({"expression": after})
    else:
        parts.append({"expression": expression})
    return {"parts": parts, "label": label, "relation": relation}


def flow_visual(rows, *, title):
    return {
        "kind": "basic-inequality-structure-scan",
        "showFocus": False,
        "showRoute": False,
        "condition": {"label": "当前式", "expression": "当前已验证表达式"},
        "target": {"label": "本步目标", "expression": title},
        "reading": "局部处理",
        "route": title,
        "organization": {"expressionFlow": rows},
    }
