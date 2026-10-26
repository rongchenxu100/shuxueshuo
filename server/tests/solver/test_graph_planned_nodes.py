"""Catalog-only lifecycle states never opt a type into photo solving."""
from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_two import recognition
from shuxueshuo_server.graph_lesson.stage_three import selection
from shuxueshuo_server.learning.content import validate_graph


def test_planned_type_cannot_match_even_when_a_contract_would_support_it(monkeypatch):
    nodes = recognition.load_nodes()
    target = "type-function-domain"
    assert nodes[target]["status"] == "planned"
    contract = {"type_id": target, "branches": [{"branch_id": "all", "checks": []}]}
    assert recognition.evaluate_types([], contracts=[contract]) == []
    monkeypatch.setattr(recognition, "load_contracts", lambda: [contract])
    assert recognition.evaluate_types([]) == []
    active = deepcopy(nodes)
    active[target].pop("status")
    monkeypatch.setattr(recognition, "load_nodes", lambda: active)
    assert recognition.evaluate_types([], contracts=[contract])[0]["status"] == "supported"


def test_planned_type_cannot_select_existing_quadratic_rule(monkeypatch):
    nodes = selection.load_nodes()
    target = "type-function-domain"
    nodes[target]["rules"] = ["rule-quadratic-method"]
    monkeypatch.setattr(selection, "load_nodes", lambda: nodes)
    assert selection.load_contract(target) is None
    result = selection.evaluate_goal({}, "/root/goals/0", [], target)
    assert result["status"] == "unsupported_type"
    assert result["d3"] is None and result["d4"] is None


def test_import_accepts_collection_membership_without_making_it_a_chapter():
    nodes = [{"id": "junior", "kind": "collection"}, {"id": "fraction", "kind": "knowledge"}]
    edges = [{"source_id": "junior", "target_id": "fraction", "relation_type": "contains"}]
    assert validate_graph(nodes, edges)["junior"] == "collection"
    nodes[1]["kind"] = "method"
    with pytest.raises(ValueError, match="invalid edge types"):
        validate_graph(nodes, edges)


def test_import_rejects_lifecycle_and_method_edge_mismatches():
    body = {"id": "planned", "kind": "problem_type", "status": "planned", "knowledge": ["k"], "features": ["真实线索"], "methods": [], "rules": [], "examples": []}
    nodes = [{"id": "planned", "kind": "problem_type", "body": body}, {"id": "method", "kind": "method"}]
    validate_graph(nodes, [])
    edge = {"source_id": "planned", "target_id": "method", "relation_type": "candidate"}
    with pytest.raises(ValueError, match="method edges"):
        validate_graph(nodes, [edge])
    body["methods"] = ["method"]
    with pytest.raises(ValueError, match="executable routes"):
        validate_graph(nodes, [])
    body["methods"] = []
    body["status"] = "knowledge_only"
    with pytest.raises(ValueError, match="knowledge-only"):
        validate_graph(nodes, [])
    for status in ("active", None):
        if status is None:
            body.pop("status")
        else:
            body["status"] = status
        with pytest.raises(ValueError, match="requires examples"):
            validate_graph(nodes, [])
    body["examples"] = [{"title": "代表题"}]
    with pytest.raises(ValueError, match="requires a method entry"):
        validate_graph(nodes, [])


def test_collection_progress_aggregates_direct_members_without_chapter_wrapper():
    from shuxueshuo_server.learning.associations import directory_progress

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self.rows

    class Connection:
        def execute(self, sql):
            if "FROM knowledge_nodes" in str(sql):
                return Result([{"id": "junior", "kind": "collection", "label": "初中知识"},
                               {"id": "fraction", "kind": "knowledge", "label": "分式"}])
            return Result([{"source_id": "junior", "target_id": "fraction", "relation_type": "contains"}])

    result = directory_progress(Connection(), "junior", [{"node_id": "fraction", "kind": "knowledge", "eligible": False, "status": "unassessed"}])
    assert result["contains"]["node_ids"] == ["fraction"]
    assert result["contains"]["total"] == 1
    assert result["extends"]["total"] == 0
