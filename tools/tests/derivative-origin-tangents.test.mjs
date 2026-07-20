import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  loadCalculusRuntime,
  repoRoot,
} from "./calculus-test-helpers.mjs";

const lessonDir = path.join(
  repoRoot,
  "internal/senior-high/lesson-specs/cn-2022-new-gaokao-i-15",
);

function readJson(name) {
  return JSON.parse(fs.readFileSync(path.join(lessonDir, name), "utf8"));
}

const { CalculusLessonFromSpec } = loadCalculusRuntime();
const spec = readJson("calculus-spec.json");
const decorations = readJson("calculus-decorations.json");
const lessonData = readJson("lesson-data.json");

test("generates two distinct tangents through the origin for a positive parameter", () => {
  const state = CalculusLessonFromSpec.resolveState(spec, -1, {});

  assert.equal(state.env.a, 0.5);
  assert.equal(state.env.x1, 0.5);
  assert.notEqual(state.env.x0, state.env.x1);
  assert.ok(Math.abs(state.tangents.tangent0.intercept) < 1e-12);
  assert.ok(Math.abs(state.tangents.tangent1.intercept) < 1e-12);
  assert.notEqual(state.tangents.tangent0.slope, state.tangents.tangent1.slope);
});

test("keeps a linked to the moving contact parameter", () => {
  for (const x0 of [-1, 1.5]) {
    const state = CalculusLessonFromSpec.resolveState(spec, x0, {});
    assert.ok(Math.abs(state.env.a - x0 ** 2 / (1 - x0)) < 1e-12);
    assert.notEqual(state.env.x0, state.env.x1);
    assert.ok(Math.abs(state.tangents.tangent0.intercept) < 1e-12);
    assert.ok(Math.abs(state.tangents.tangent1.intercept) < 1e-12);
  }
});

test("treats a equals zero and minus four as one-contact boundary states", () => {
  const zero = CalculusLessonFromSpec.resolveState(spec, 0, {});
  const minusFour = CalculusLessonFromSpec.resolveState(spec, 2, {});

  assert.equal(zero.env.a, 0);
  assert.ok(Math.abs(zero.env.x0 - zero.env.x1) < 1e-12);
  assert.equal(minusFour.env.a, -4);
  assert.equal(minusFour.env.x0, minusFour.env.x1);
});

test("keeps every lesson step focused on the original function panel", () => {
  const renderer = CalculusLessonFromSpec.createSpecRenderer(
    spec,
    decorations,
    lessonData.steps,
    lessonData.policies,
  );
  const markup = renderer.diagramMarkupFor(2, -1, {});

  assert.match(markup, /函数曲线与过原点切线/);
  assert.match(markup, /y=f\(x\)=\(x\+a\)eˣ/);
  assert.doesNotMatch(JSON.stringify(lessonData), /h\(x₀\)|参数图/);
  assert.doesNotMatch(markup, /NaN|Infinity|undefined/);
  assert.equal(spec.panels.length, 1);
});
