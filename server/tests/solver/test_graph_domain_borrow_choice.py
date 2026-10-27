"""Submethod selection distinguishes an unsupported route from a wrong method."""

import json
import subprocess
from pathlib import Path

import pytest

from shuxueshuo_server.learning.graph_walk import grade
from tests.solver.test_graph_domain_parameter_interactions import candidate, execute


@pytest.mark.parametrize("expression", ["sqrt(x^2+k)", "sqrt(k*x^2+k)"])
def test_applicable_borrowed_method_stays_uncovered_without_releasing_results(expression):
    _, _, chunks = execute(candidate(expression))
    borrowed = chunks[2][0]["parts"][0]
    assert borrowed["interaction"]["type"] == "plane"
    assert "separation" in borrowed["alternatives"]
    assert "分离参数法" in borrowed["alternatives"]["separation"]["message"]
    cell = borrowed["expected_answer"]["cell"]
    answers = [[*cell, "separation"], [*cell, "discriminant"],
               ["interval", "free", "separation"], ["real", "given", "separation"],
               [*cell, "interval"]]
    expected = ["uncovered", "passed", "wrong", "wrong", "wrong"]
    # Both graders must check the problem's cell before treating an applicable
    # but unexpanded method as a valid choice.
    assert [grade(borrowed, {"value": answer}, "domain-parameter") for answer in answers] == expected
    program = r"""
      import fs from 'node:fs';
      import assert from 'node:assert/strict';
      import {createState, currentDecision, gradeDecision, submitAnswer, graphState}
        from './site/assets/graph-walk/walk-state.mjs';
      import {nativePracticeContract} from './tools/lib/graph-walk-practice.mjs';
      const {decision, answers, expected} = JSON.parse(fs.readFileSync(0, 'utf8'));
      assert.deepEqual(answers.map(answer => gradeDecision(decision, answer).status), expected);
      const bundle = {bundleVersion: 'probe', intro: [],
        routes: {'domain-parameter': {steps: [decision]}}, graph: {nodes: [], edges: []}};
      let state = createState(bundle);
      state.run.route = 'domain-parameter';
      const before = structuredClone(state);
      state = submitAnswer(bundle, state, {decision: decision.id, answer: answers[0]});
      assert.equal(state.lastFeedback.status, 'uncovered');
      assert.deepEqual(state.run, before.run);
      assert.equal(state.done, false);
      assert.equal(currentDecision(bundle, state).id, decision.id);
      assert.deepEqual(graphState(bundle, state), graphState(bundle, before));
      state = submitAnswer(bundle, state, {decision: decision.id, answer: answers[1]});
      assert.equal(state.lastFeedback.status, 'passed');
      assert.equal(state.done, true);
      const native = nativePracticeContract(bundle);
      assert.deepEqual(native.routes['domain-parameter'].steps[0].alternatives, decision.alternatives);
      bundle.routes['domain-parameter'].steps[0] = {...decision, alternatives: {}};
      assert.equal(Object.hasOwn(nativePracticeContract(bundle).routes['domain-parameter'].steps[0], 'alternatives'), false);
      console.log(JSON.stringify(native));
    """
    result = subprocess.run(["node", "--input-type=module", "-e", program],
                            check=False, cwd=Path(__file__).resolve().parents[3], text=True, capture_output=True,
                            input=json.dumps({"decision": borrowed, "answers": answers, "expected": expected}))
    assert result.returncode == 0, result.stderr
    published = json.loads(result.stdout)["routes"]["domain-parameter"]["steps"][0]
    assert [grade(published, {"value": answer}, "domain-parameter") for answer in answers] == expected
