import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execFileSync } from "node:child_process";
import vm from "node:vm";

test("standalone compiler embeds runtime and keeps source text inert in inline JSON", () => {
  const root = path.resolve(import.meta.dirname, "../..");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "review-standalone-"));
  try {
    const fixture = path.join(root, "internal/lesson-specs/tj-2026-nankai-yimo-25");
    for (const file of ["geometry-spec.json", "step-decorations.json", "lesson-data.json"])
      fs.copyFileSync(path.join(fixture, file), path.join(dir, file));
    const dataPath = path.join(dir, "lesson-data.json");
    const data = JSON.parse(fs.readFileSync(dataPath, "utf8"));
    data.meta.outputPath = path.join(dir, "lesson.html");
    data.meta.pageTitle = '<script id="injected">window.pwned=true</script>';
    data.ui ??= {};
    data.ui.groupTitles = { unsafe: '</script><script id="injected">alert(1)</script>' };
    fs.writeFileSync(dataPath, JSON.stringify(data));
    execFileSync("node", [path.join(root, "tools/build-lesson-page.mjs"), dir, "--standalone"], { cwd: root });
    const html = fs.readFileSync(data.meta.outputPath, "utf8");
    assert.ok(!html.replace(/<style>[\s\S]*?<\/style>/g, "").includes('<link rel="stylesheet"'));
    assert.ok(!html.includes('<script id="injected">'));
    assert.ok(html.includes("\\u003c/script>"));
    assert.ok(html.includes("GeometryLessonFromSpec"));
    assert.ok(html.includes("<style>"));
    for (const match of html.replace(/<!--[\s\S]*?-->/g, "").matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)) {
      assert.ok(!match[1].includes('src='));
      if (match[1].includes('application/json')) JSON.parse(match[2]);
      else new vm.Script(match[2]);
    }
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});
