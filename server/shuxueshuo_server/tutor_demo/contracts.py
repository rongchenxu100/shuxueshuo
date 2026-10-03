"""Execute the small set of supported components against authored math answers."""

import re
from collections import Counter
from copy import deepcopy
from itertools import combinations


class InvalidAction(ValueError):
    pass


ORDERED_COMPONENTS = {"symmetry", "substitution", "homogeneity", "fill", "checklist", "rewrite"}
PAIR_COMPONENTS = {"structure", "amgm", "equality"} | ORDERED_COMPONENTS


def slot_count(component):
    return len(component.get("slots") or slot_labels(component))


def slot_labels(component):
    return component.get("slot_labels", ("方框", "圆圈"))


def slot_values(slot):
    """A slot with names selects up to len(names) targets, joined by "|" in option order."""
    values = [o["value"] for o in slot["options"]]
    if "names" not in slot:
        return values
    return [""] + [
        "|".join(chosen)
        for size in range(1, len(slot["names"]) + 1)
        for chosen in combinations(values, size)
    ]


def pair_matches(component, actual, expected):
    actual = actual[: slot_count(component)]
    if component["type"] in ORDERED_COMPONENTS:
        return actual == expected
    return Counter(actual) == Counter(expected)


def fresh_state(lesson):
    return deepcopy(lesson["initial_state"])


def route_complete(lesson, state):
    route = lesson["routes"].get(state["method"])
    return bool(route) and state["active"] >= len(route["nodes"])


def current_node(lesson, state):
    route = lesson["routes"].get(state["method"])
    if not route or route_complete(lesson, state):
        return None
    return route["nodes"][state["active"]]


def allowed_actions(node):
    component = node["interaction"]
    if component["type"] in PAIR_COMPONENTS:
        if "slots" in component:
            actions = [
                {
                    "kind": "fill",
                    "index": i,
                    "values": slot_values(slot),
                    "description": slot["label"]
                    + (
                        "；可多选，多个对象按候选顺序用|连接，空字符串表示清除"
                        if "names" in slot
                        else ""
                    ),
                }
                for i, slot in enumerate(component["slots"])
            ]
        else:
            actions = [
                {
                    "kind": "fill",
                    "index": i,
                    "values": component["terms"],
                    "description": name,
                }
                for i, name in enumerate(slot_labels(component))
            ]
        if component["type"] == "structure":
            actions.append(
                {
                    "kind": "swap",
                    "values": ["sum", "product"],
                    "description": "sum为定和求积，product为定积求和",
                }
            )
    elif component["type"] == "choice":
        actions = [
            {
                "kind": "choice",
                "values": [o["value"] for o in component["options"]],
                "description": component.get("description", node["question"]),
            }
        ]
    else:
        raise ValueError(f"Unknown component: {component['type']}")
    return actions + [{"kind": "submit"}]


def validate_answer(node, state):
    component, expected = node["interaction"], node["expected_answer"]
    feedback = node.get("feedback", {})
    if component["type"] in PAIR_COMPONENTS:
        if not pair_matches(
            component, state["pairs"][state["active"]], expected["terms"]
        ):
            raise InvalidAction(feedback.get("terms", "再看看两个数学项是否对应。"))
        if component["type"] == "structure":
            fixed, target = (
                ("product", "sum") if state["swapped"] else ("sum", "product")
            )
            if fixed != expected["fixed"] or target != expected["target"]:
                raise InvalidAction(
                    feedback.get("structure", "再看看条件和目标的关系。")
                )
    elif component["type"] == "choice":
        if state["choices"].get(component["field"]) not in expected["one_of"]:
            raise InvalidAction(
                feedback.get("answer", "还需要表达你对这个问题的判断。")
            )
    else:
        raise ValueError(f"Unknown component: {component['type']}")


def accept_text_answer(node, state):
    """Bind a confirmed answer, only after the session has checked its evidence.

    Preserve equivalent student choices. Never choose between multiple valid
    alternatives on the student's behalf.
    """
    component, expected = node["interaction"], node["expected_answer"]
    if component["type"] in PAIR_COMPONENTS:
        pair = state["pairs"][state["active"]]
        if not pair_matches(component, pair, expected["terms"]):
            pair[: len(expected["terms"])] = expected["terms"]
        if component["type"] == "structure":
            state["swapped"] = expected["fixed"] == "product"
    elif component["type"] == "choice" and len(expected["one_of"]) == 1:
        state["choices"][component["field"]] = expected["one_of"][0]


def apply_action(state, action, lesson):
    if action.kind == "method":
        if (
            state["active"] != 0
            or route_complete(lesson, state)
            or action.value not in {m["id"] for m in lesson["methods"]}
        ):
            raise InvalidAction("当前步骤不能直接更换方法，请使用切换路径。")
        if state["method"] != action.value:
            state.update(fresh_state(lesson))
            state["method"] = action.value
        return
    node = current_node(lesson, state)
    if not node:
        raise InvalidAction("当前没有可作答的节点，请选择可用路径。")
    if action.kind == "submit":
        validate_answer(node, state)
        state["active"] += 1
        return
    for spec in allowed_actions(node):
        if spec["kind"] == action.kind and spec.get("index") == action.index:
            if action.value not in spec["values"]:
                raise InvalidAction("这个值不属于当前组件的候选项。")
            if action.kind == "fill":
                pair = state["pairs"][state["active"]]
                pair.extend([""] * (action.index + 1 - len(pair)))
                pair[action.index] = action.value
            elif action.kind == "swap":
                state["swapped"] = action.value == "product"
            elif action.kind == "choice":
                state["choices"][node["interaction"]["field"]] = action.value
            return
    raise InvalidAction("这个操作不属于当前节点。")


def node_results(node, state):
    """Resolve authored conclusions; they are references, not solver certificates."""
    values = state.get("choices", {})
    results = []
    for result in node.get("results", []):
        names = re.findall(r"\{\{(\w+)\}\}", result)
        if any(values.get(name) is None for name in names):
            continue
        for name in names:
            result = result.replace("{{" + name + "}}", str(values[name]))
        results.append(result)
    return results


def node_contract(node, state):
    if node is None:
        return None
    contract = {
        key: deepcopy(node[key])
        for key in (
            "id",
            "title",
            "question",
            "criteria",
            "required_evidence",
            "expected_answer",
            "completion_reply",
        )
    }
    contract["allowed_actions"] = allowed_actions(node)
    contract["reference_results"] = node_results(node, state)
    contract["answer_values"] = deepcopy(state.get("choices", {}))
    if node["interaction"]["type"] in PAIR_COMPONENTS:
        component = node["interaction"]
        labels = (
            [slot["label"] for slot in component["slots"]]
            if component.get("slots")
            else slot_labels(component)
        )
        pair = state["pairs"][state["active"]]
        contract["current_inputs"] = [
            {"index": i, "label": label, "value": pair[i] if i < len(pair) else ""}
            for i, label in enumerate(labels)
        ]
    return contract


def turn_context(lesson, state, evidence):
    complete = route_complete(lesson, state)
    routes = [{"id": key, "label": r["label"]} for key, r in lesson["routes"].items()]
    selectable = state["active"] == 0 and not complete
    actions = [
        {
            "kind": "switch_route",
            "values": [r["id"] for r in routes],
            "description": "创建新的路径尝试，保存旧记录；单独执行，不能同时提交答案。",
        }
    ]
    if state["method"] is None:
        actions = []
    if selectable:
        actions.append(
            {"kind": "method", "values": [m["id"] for m in lesson["methods"]]}
        )
    previous_results = []
    route = lesson["routes"].get(state["method"])
    if route:
        for node in route["nodes"][: state["active"]]:
            previous_results.extend(node_results(node, state))
    return {
        "state": deepcopy(state),
        "status": "completed" if complete else "learning",
        "node": node_contract(current_node(lesson, state), state),
        "problem_conditions": deepcopy(lesson["problem"]["conditions"]),
        "completed_results": list(dict.fromkeys(previous_results)),
        "accepted_evidence": list(evidence),
        "available_routes": routes,
        "flow_actions": actions,
        "selectable_start_nodes": {
            key: node_contract(r["nodes"][0], fresh_state(lesson))
            for key, r in lesson["routes"].items()
        }
        if selectable
        else {},
    }
