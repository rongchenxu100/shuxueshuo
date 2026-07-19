import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

import { repoRoot } from "./calculus-test-helpers.mjs";

const validator = path.join(repoRoot, "tools/validate-calculus-spec.mjs");
const goldenDir = path.join(
  repoRoot,
  "internal/senior-high/lesson-specs/cn-2022-gaokao-jia-wen-20",
);

function runValidator(inputDir) {
  return spawnSync(process.execPath, [validator, inputDir], {
    cwd: repoRoot,
    encoding: "utf8",
  });
}

function copyGoldenInput(prefix) {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  for (const name of [
    "calculus-spec.json",
    "calculus-decorations.json",
    "lesson-data.json",
  ]) {
    fs.copyFileSync(path.join(goldenDir, name), path.join(tempDir, name));
  }
  return tempDir;
}

test("accepts the golden lesson", () => {
  const result = runValidator(goldenDir);
  assert.equal(result.status, 0, result.stderr);
});

test("rejects an unknown function reference", (context) => {
  const tempDir = copyGoldenInput("calculus-invalid-");
  context.after(() => fs.rmSync(tempDir, { recursive: true, force: true }));
  const specPath = path.join(tempDir, "calculus-spec.json");
  const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
  spec.functionPoints[0].functionId = "missing-function";
  fs.writeFileSync(specPath, JSON.stringify(spec), "utf8");

  const result = runValidator(tempDir);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /引用未知 function/);
});

test("rejects an incorrect derivative expression", (context) => {
  const tempDir = copyGoldenInput("calculus-derivative-");
  context.after(() => fs.rmSync(tempDir, { recursive: true, force: true }));
  const specPath = path.join(tempDir, "calculus-spec.json");
  const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
  spec.functions[0].derivativeExpr = "0";
  fs.writeFileSync(specPath, JSON.stringify(spec), "utf8");

  const result = runValidator(tempDir);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /与数值导数不一致/);
});

test("rejects an unknown panel reference", (context) => {
  const tempDir = copyGoldenInput("calculus-panel-");
  context.after(() => fs.rmSync(tempDir, { recursive: true, force: true }));
  const specPath = path.join(tempDir, "calculus-spec.json");
  const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
  spec.functions[0].panelId = "missing-panel";
  fs.writeFileSync(specPath, JSON.stringify(spec), "utf8");

  const result = runValidator(tempDir);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /引用未知 panel/);
});

test("rejects a missing decoration step", (context) => {
  const tempDir = copyGoldenInput("calculus-step-");
  context.after(() => fs.rmSync(tempDir, { recursive: true, force: true }));
  const decorationsPath = path.join(tempDir, "calculus-decorations.json");
  const decorations = JSON.parse(fs.readFileSync(decorationsPath, "utf8"));
  delete decorations.steps.q2s2;
  fs.writeFileSync(decorationsPath, JSON.stringify(decorations), "utf8");

  const result = runValidator(tempDir);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /calculus-decorations\.steps 缺少: q2s2/);
});
