import assert from "node:assert/strict";
import test from "node:test";

import {
  loadCalculusRuntime,
  readGoldenJson,
} from "./calculus-test-helpers.mjs";

const { CalculusLessonFromSpec } = loadCalculusRuntime();
const spec = readGoldenJson("calculus-spec.json");
const decorations = readGoldenJson("calculus-decorations.json");
const lessonData = readGoldenJson("lesson-data.json");

test("resolves the golden common-tangent state at x1=-1", () => {
  const state = CalculusLessonFromSpec.resolveState(spec, -1, {});
  assert.equal(spec.parameter.name, "x1");
  assert.equal(state.env.x1, -1);
  assert.equal(Object.hasOwn(state.env, "t"), false);
  assert.equal(state.env.x2, 1);
  assert.equal(state.env.a, 3);
  assert.equal(state.tangents.tangentF.slope, 2);
  assert.equal(state.tangents.tangentF.intercept, 2);
  assert.equal(state.tangents.tangentG.slope, 2);
  assert.equal(state.tangents.tangentG.intercept, 2);
});

test("reveals the two tangent constructions step by step", () => {
  const renderer = CalculusLessonFromSpec.createSpecRenderer(
    spec,
    decorations,
    lessonData.steps,
    lessonData.policies,
  );
  const fromF = renderer.diagramMarkupFor(0, -1, {});
  const fromG = renderer.diagramMarkupFor(1, -1, {});
  const matched = renderer.diagramMarkupFor(2, -1, {});
  const substituted = renderer.diagramMarkupFor(3, -1, {});

  assert.match(fromF, /stroke="#dc2626"/);
  assert.doesNotMatch(fromF, /stroke="#7c3aed"/);
  assert.match(fromF, /P\(x₁,f\(x₁\)\)/);
  assert.match(fromG, /stroke="#7c3aed"/);
  assert.doesNotMatch(fromG, /stroke="#dc2626"/);
  assert.match(fromG, /Q\(x₂,g\(x₂\)\)/);
  assert.match(matched, /stroke="#dc2626"/);
  assert.match(matched, /stroke="#7c3aed"/);
  assert.match(substituted, /P\(−1,0\)/);
  assert.match(substituted, /Q\(1,4\)/);
});

test("analytic derivatives agree with finite differences", () => {
  const environment = CalculusLessonFromSpec.resolveState(spec, -1, {}).env;
  for (const definition of spec.functions.filter((item) => item.derivativeExpr)) {
    for (const x of [-1, -0.25, 0.5, 1]) {
      const h = 1e-6;
      const left = CalculusLessonFromSpec.evaluateFunction(
        definition,
        x - h,
        environment,
      );
      const right = CalculusLessonFromSpec.evaluateFunction(
        definition,
        x + h,
        environment,
      );
      const numeric = (right - left) / (2 * h);
      const analytic = CalculusLessonFromSpec.evaluateDerivative(
        definition,
        x,
        environment,
      );
      assert.ok(Math.abs(numeric - analytic) < 1e-4, `${definition.id} at ${x}`);
    }
  }
});

test("sampling splits a curve around a discontinuity", () => {
  const rational = {
    variable: "x",
    expr: "1/x",
    domain: [{ min: -1, max: 1 }],
  };
  const segments = CalculusLessonFromSpec.sampleFunction(
    rational,
    {},
    { minX: -1, maxX: 1, minY: -5, maxY: 5 },
    200,
  );
  assert.ok(segments.length >= 2);
  assert.ok(segments.flat().every((point) => Number.isFinite(point.y)));
});

test("focuses the final range step on the auxiliary-function panel", () => {
  const renderer = CalculusLessonFromSpec.createSpecRenderer(
    spec,
    decorations,
    lessonData.steps,
    lessonData.policies,
  );
  const markup = renderer.diagramMarkupFor(7, 1, {});
  assert.match(markup, /辅助函数 a＝h\(x₁\)/);
  assert.doesNotMatch(markup, /函数曲线与公切线/);
  assert.doesNotMatch(markup, /y=f\(x\)=x³−x/);
  assert.match(markup, /h\(−1\/3\)=5\/27/);
  assert.match(markup, /h\(0\)=1\/4/);
  assert.match(markup, /h\(1\)=−1/);
  assert.doesNotMatch(markup, /NaN|Infinity|undefined/);
  assert.ok((markup.match(/<path /g) ?? []).length >= 1);
});

test("shows exactly three critical positions in the derivative step", () => {
  const renderer = CalculusLessonFromSpec.createSpecRenderer(
    spec,
    decorations,
    lessonData.steps,
    lessonData.policies,
  );
  const markup = renderer.diagramMarkupFor(5, -1 / 3, {});
  const positions = [...markup.matchAll(/<circle cx="([^"]+)" cy="([^"]+)"/g)]
    .map((match) => `${Number(match[1]).toFixed(2)},${Number(match[2]).toFixed(2)}`);

  assert.doesNotMatch(markup, /函数曲线与公切线/);
  assert.match(markup, /x₁=−1\/3/);
  assert.match(markup, /x₁=0/);
  assert.match(markup, /x₁=1/);
  assert.equal(new Set(positions).size, 3);
});

test("keeps the coefficient range proof in four student-facing steps", () => {
  assert.equal(lessonData.steps.length, 8);
  assert.deepEqual(
    lessonData.steps.slice(4).map((step) => step.id),
    ["q2s1", "q2s2", "q2s3", "q2s4"],
  );
  assert.match(lessonData.steps[4].title, /构造辅助函数/);
  assert.match(lessonData.steps[5].title, /临界点/);
  assert.match(lessonData.steps[6].title, /单调性/);
  assert.match(lessonData.steps[7].title, /取值范围/);
});
