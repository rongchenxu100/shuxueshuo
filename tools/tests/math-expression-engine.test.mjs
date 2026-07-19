import assert from "node:assert/strict";
import test from "node:test";

import { loadCalculusRuntime } from "./calculus-test-helpers.mjs";

const { MathExpressionEngine } = loadCalculusRuntime();
const evaluate = (expression, environment = {}) =>
  MathExpressionEngine.evaluate(expression, environment);

test("evaluates precedence, signed powers and variables", () => {
  assert.equal(evaluate("2+3*4"), 14);
  assert.equal(evaluate("(2+3)*4"), 20);
  assert.equal(evaluate("-2^2"), -4);
  assert.equal(evaluate("2^-3"), 0.125);
  assert.equal(evaluate("x^3-x", { x: -2 }), -6);
});

test("evaluates supported elementary functions and constants", () => {
  assert.ok(Math.abs(evaluate("sqrt(9)+abs(-2)+ln(e)") - 6) < 1e-12);
  assert.ok(Math.abs(evaluate("sin(pi/2)+cos(0)+exp(0)") - 3) < 1e-12);
  assert.ok(Math.abs(evaluate("log(e)") - 1) < 1e-12);
});

test("does not execute JavaScript or accept unknown identifiers", () => {
  assert.throws(() => evaluate("globalThis.process.exit()"), /unknown|trailing/);
  assert.throws(() => evaluate("constructor(1)"), /unknown function/);
  assert.throws(() => evaluate("missing+1"), /unknown identifier/);
});

test("keeps undefined mathematical points non-finite", () => {
  assert.equal(evaluate("1/0"), Infinity);
  assert.ok(Number.isNaN(evaluate("ln(-1)")));
  assert.ok(Number.isNaN(evaluate("sqrt(-1)")));
});
