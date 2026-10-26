"""One graph-walk bundle per resolved goal, in the Demo engine's format.

The bundle reuses the words of ``lesson.present_lesson`` (D1 rows, D2 roles)
and cuts its graph from the public ``site/knowledge/graph.json``: the lit
knowledge nodes, the problem types that involve them, and the method rules and
methods those types lead to. Only node and edge ids are chosen here; positions
come from the public lane layout in the browser (``graph.lanes``).

Routes (S3 onward) do not exist yet, so ``routes`` is empty and ``pending``
names the next step. The AI replay is synthesised from the same answers the
student is graded against; it claims nothing beyond stage two.
"""

import json
from functools import cache
from hashlib import sha256

from shuxueshuo_server.graph_lesson.stage_two.contracts import ROOT

GRAPH = ROOT / "site/knowledge/graph.json"
MAX_TYPES = 8
PENDING = {"title": "选方法", "status": "生成中",
           "text": "接下来要在图谱里为这一问选方法、一步步解出来；这部分还在生成，先看看图谱里亮起的线索和题型。"}


@cache
def _graph():
    raw = GRAPH.read_bytes()
    value = json.loads(raw)
    return {"version": sha256(raw).hexdigest(), "nodes": {n["id"]: n for n in value["nodes"]},
            "edges": {e["id"]: e for e in value["edges"]}}


def _edge(source, kind, target):
    return f"{source}|{kind}|{target}"


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def subgraph(clues, types, primary):
    """Clues, the types that involve them (ranked by coverage), and where the primary type leads."""
    graph = _graph()
    edges = graph["edges"].values()
    involving = {}
    for edge in edges:
        if edge["type"] == "involves" and edge["to"] in clues and edge["from"] in graph["nodes"]:
            involving.setdefault(edge["from"], set()).add(edge["to"])
    ranked = sorted(involving, key=lambda t: (-len(involving[t]), t))
    shown = list(dict.fromkeys([t for t in types if t in graph["nodes"]] + ranked))[:max(MAX_TYPES, len(types))]
    rules = [e["to"] for e in edges if e["type"] == "method_rule" and e["from"] == primary]
    methods = [e["to"] for e in edges
               if ((e["type"] == "selects" and e["from"] in rules)
                   or (e["type"] == "candidate" and e["from"] == primary))
               and graph["nodes"].get(e["to"], {}).get("kind") == "method"]
    ids = list(dict.fromkeys([c for c in clues if c in graph["nodes"]] + shown + rules + methods))
    keep = set(ids)
    nodes = [graph["nodes"][i] for i in ids]
    links = [e for e in edges if e["from"] in keep and e["to"] in keep]
    best = max((len(involving.get(t, ())) for t in shown), default=0)
    lanes = [{"label": "知识线索", "ids": [c for c in clues if c in keep]},
             {"label": "题型", "kind": "problem_type"},
             {"label": "选法判断", "kind": "judgment_rule"},
             {"label": "方法", "kind": "method"}]
    return {"nodes": nodes, "edges": links, "lanes": lanes}, shown, best


def _d1(goal, clues, shown, best):
    rows = goal["d1"]["rows"]
    slots = [{"label": "“" + "…".join(q["text"] for q in row["quote"]) + "”",
              "options": [{"value": o["id"], "label": o["text"], **({"feedback": o["feedback"]} if o["feedback"] else {})}
                          for o in row["options"]]} for row in rows]
    answer = [next(o["id"] for o in row["options"] if o["correct"]) for row in rows]
    summary = goal["d1"]["summary"]
    decision = {
        "id": "D1", "title": "读题", "question": "这一问在说什么？逐句选出你的理解。", "source": "authored",
        "submit_label": "读懂了，看图谱怎么走",
        "interaction": {"type": "checklist", "title": "逐句读题", "slots": slots},
        "expected_answer": {"terms": answer},
        "feedback": {"terms": "有一处读得不对，对照原句再看看。"},
        "candidateNodes": clues + shown,
        "effects": {"nodes": clues, "edges": [], "calls": [], "results": [summary] if summary else [],
                    "log": f"图谱查询：从 {len(clues)} 个知识线索反查，找到 {len(shown)} 个相关题型；"
                           f"最高覆盖 {best}/{len(clues)}。"},
    }
    if goal["d1"].get("interaction") == "choice":
        (slot,), (answer,) = slots, answer
        givens = [item["text"] for item in goal["d1"].get("givens", [])
                  if item["kind"] == "given_domain" and item.get("text")]
        decision.update(question="\n\n".join([*givens, goal["d1"]["question"]]),
                        interaction={"type": "choice", "field": "reading", "options": slot["options"]},
                        expected_answer={"one_of": [answer]},
                        feedback={"answer": "再想一想，定义域描述的是输入还是输出的取值范围。"})
    return decision, answer


def _d2(goal, clues, edges):
    options = goal["d2"]
    primary = goal["primary"]
    label = next(o["label"] for o in options if o["type_id"] == primary)
    reasons = [r.rstrip("。；; ") for r in next(o["reasons"] for o in options if o["type_id"] == primary)]
    others = [o for o in options if o["type_id"] != primary]
    lit = [_edge(primary, "involves", c) for c in clues if _edge(primary, "involves", c) in edges]
    transformation = goal["d1"].get("transformation")
    context = f"已转化为：{transformation['normalized_text']}\n\n" if transformation else ""
    return {
        "id": "D2", "title": "确定题型", "question": context + "哪一个题型最直接描述这一问的条件与求解目标？",
        "source": "authored", "submit_label": "确认题型",
        "interaction": {"type": "choice", "field": "problem_type",
                        "options": [{"value": o["type_id"], "label": o["label"],
                                     **({"feedback": o["feedback"]} if o["role"] == "conflict" else {})}
                                    for o in options]},
        "expected_answer": {"one_of": [primary]},
        "feedback": {"answer": "再对照这一问的条件和问法想一想。"},
        "alternatives": {o["type_id"]: {"message": o["feedback"], "href": f"/knowledge/{o['type_id']}/"}
                         for o in others if o["role"] == "alternative"},
        "candidateNodes": [o["type_id"] for o in options],
        "effects": {"nodes": [primary], "edges": lit, "calls": [],
                    "results": ["判断依据：" + "；".join(reasons) + "。"] if reasons else [],
                    "log": f"作答判断：选择主要题型「{label}」；另外 {len(others)} 个题型保留为对照。"},
    }, label, reasons


def _transformation(value, nodes):
    answer = next(option["id"] for option in value["options"] if option["correct"])
    return {
        "id": "D1-transform", "title": "命题转化", "source": "authored",
        "question": f"题目给出 {value['source_math']}。按量词命题的否定规则，量词和关系应怎样同时改写？",
        "submit_label": "确认转化",
        "interaction": {"type": "choice", "field": "transformation",
                        "options": [{"value": option["id"], "label": option["text"],
                                     **({"feedback": option["feedback"]} if option["feedback"] else {})}
                                    for option in value["options"]]},
        "expected_answer": {"one_of": [answer]},
        "feedback": {"answer": "量词和不等号需要同时取反，再对照原命题想一想。"},
        "candidateNodes": nodes,
        "effects": {"nodes": nodes, "edges": [], "calls": [],
                    "results": [value["equivalence"], value["explanation"], value["normalized_text"]],
                    "log": "命题转化：确认等价条件，后续按转化后的量词与不等式确定题型和方法。"},
    }, answer


def walk(goal, text, problem_id):
    """``{"bundle", "replay"}`` for one presented goal, or None when it has nothing to walk."""
    if goal["status"] != "resolved" or not goal.get("d2") or not goal.get("primary"):
        return None
    if goal["d1"].get("diagnostics"):
        return None
    graph = _graph()
    transformation = goal["d1"].get("transformation")
    reading_items = goal["d1"]["rows"] + goal["d1"].get("givens", [])
    refs = [r for item in reading_items for r in item["knowledge_refs"]] or [k["ref"] for k in goal["knowledge"]]
    if transformation:
        refs += transformation["knowledge_refs"]
    clues = list(dict.fromkeys(r.partition("#")[0] for r in refs if r.partition("#")[0] in graph["nodes"]))
    types = [o["type_id"] for o in goal["d2"]]
    shown_graph, shown, best = subgraph(clues, types, goal["primary"])
    edges = {e["id"] for e in shown_graph["edges"]}
    intro, actions = [], []
    if goal["d1"]["rows"]:
        d1, answer = _d1(goal, clues, shown, best)
        intro.append(d1)
        if d1["interaction"]["type"] == "choice":
            reason = goal["d1"]["summary"]
        else:
            reading = "；".join(f"{slot['label']}——{next(o['label'] for o in slot['options'] if o['value'] == value)}"
                                for slot, value in zip(d1["interaction"]["slots"], answer))
            reason = f"逐句读题：{reading}。"
        actions.append({"decision": "D1", "answer": answer, "reason": reason})
    if transformation:
        nodes = ["quantifiers"] if "quantifiers" in clues else []
        step, answer = _transformation(transformation, nodes)
        intro.append(step)
        actions.append({"decision": "D1-transform", "answer": answer,
                        "reason": f"{transformation['equivalence']}。{transformation['explanation']}"})
    d2, label, reasons = _d2(goal, clues, edges)
    intro.append(d2)
    actions.append({"decision": "D2", "answer": goal["primary"],
                    "reason": f"选「{label}」" + (f"：{'；'.join(reasons)}。" if reasons else "。")})
    bundle = {
        "schemaVersion": 1, "problemId": f"{problem_id}/{goal['target_ref']}",
        "graphVersion": graph["version"], "problem": {"text": text}, "notation": {},
        "intro": intro, "routes": {}, "templates": {}, "pending": PENDING,
        "feedbackLabels": {"uncovered": "也能做 · 这节课先不展开"},
        "completion": {"answer": "", "back": {"href": "/lab/search/", "label": "再拍一题"}},
        "graph": shown_graph,
    }
    if goal["d1"].get("givens"):
        bundle["problem"]["givens"] = goal["d1"]["givens"]
    if transformation:
        bundle["problem"].update(source_text=text, source_meaning=transformation["source_meaning"],
                                 normalized_text=transformation["normalized_text"],
                                 normalization_decision="D1-transform")
    bundle["bundleVersion"] = _digest(bundle)
    replay = {"schemaVersion": 2, "problemId": bundle["problemId"], "bundleVersion": bundle["bundleVersion"],
              "status": "partial", "routes": [], "actions": actions}
    return {"bundle": bundle, "replay": replay}
