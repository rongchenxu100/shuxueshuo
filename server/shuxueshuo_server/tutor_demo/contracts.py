"""Execute authored node contracts, without problem-specific mathematical branches."""

from copy import deepcopy


class InvalidAction(ValueError):
    pass


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


def read_path(state, path):
    value = state
    for key in path:
        value = value[key]
    return value


def write_path(state, path, value):
    # Only paths from trusted lesson contracts, never paths supplied by the model.
    owner = read_path(state, path[:-1])
    owner[path[-1]] = value


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
        for rule in node["interaction"]["validators"]:
            value = read_path(state, rule["path"])
            operator = rule["operator"]
            if operator == "equals":
                valid = value == rule["value"]
            elif operator == "set_equals":
                valid = len(value) == len(rule["value"]) and set(value) == set(
                    rule["value"]
                )
            elif operator == "not_empty":
                valid = value is not None and value != ""
            else:
                raise ValueError(f"Unknown authored validator: {operator}")
            if not valid:
                raise InvalidAction(rule["message"])
        state["active"] += 1
        return
    for spec in node["interaction"]["actions"]:
        if spec["kind"] == action.kind and spec.get("index") == action.index:
            if action.value not in spec["values"]:
                raise InvalidAction("这个值不属于当前组件的候选项。")
            value = spec.get("mapping", {}).get(action.value, action.value)
            write_path(state, spec["path"], value)
            return
    raise InvalidAction("这个操作不属于当前节点。")


def node_contract(node, state):
    """Teacher-facing contract, excluding internal mutable paths and validators."""
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
            "text_autofill",
            "completion_reply",
            "verified_facts",
        )
    }
    contract["allowed_actions"] = [
        {k: v for k, v in action.items() if k not in ("path", "mapping")}
        for action in node["interaction"]["actions"]
    ] + [{"kind": "submit"}]
    bindings = {
        name: read_path(state, path) for name, path in node.get("bindings", {}).items()
    }
    contract["bindings"] = bindings
    for name, value in bindings.items():
        if value is not None:
            contract["verified_facts"] = [
                fact.replace("{{" + name + "}}", str(value))
                for fact in contract["verified_facts"]
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
    if selectable:
        actions.append(
            {"kind": "method", "values": [m["id"] for m in lesson["methods"]]}
        )
    return {
        "state": deepcopy(state),
        "status": "completed" if complete else "learning",
        "node": node_contract(current_node(lesson, state), state),
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
