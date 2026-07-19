import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

export const repoRoot = path.resolve(import.meta.dirname, "../..");

export function loadCalculusRuntime() {
  const sandbox = { window: {}, console, Math };
  vm.createContext(sandbox);
  for (const file of [
    "site/assets/js/math-expression-engine.js",
    "site/assets/js/calculus-lesson-from-spec.js",
  ]) {
    vm.runInContext(fs.readFileSync(path.join(repoRoot, file), "utf8"), sandbox, {
      filename: file,
    });
  }
  return sandbox.window;
}

export function readGoldenJson(fileName) {
  return JSON.parse(
    fs.readFileSync(
      path.join(
        repoRoot,
        "internal/senior-high/lesson-specs/cn-2022-gaokao-jia-wen-20",
        fileName,
      ),
      "utf8",
    ),
  );
}
