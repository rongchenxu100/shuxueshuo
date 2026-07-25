#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const currentFile = fileURLToPath(import.meta.url);
const repoRoot = path.resolve(path.dirname(currentFile), "..");
const GROUP_BY_NUMBER = new Map([
  ...[1, 2, 3].map((number) => [number, "function-concept"]),
  ...[4, 5, 6].map((number) => [number, "function-domain"]),
  ...[7, 8, 9, 10, 11].map((number) => [number, "function-value-and-range"]),
]);

export function validateFunctionBatch(manifestPath, root = repoRoot) {
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  const errors = [];
  if (!manifest.batchId || !Array.isArray(manifest.items)) errors.push("manifest 缺少 batchId 或 items");
  const sourcePath = path.join(root, manifest.sourceImage ?? "");
  if (!fs.existsSync(sourcePath)) errors.push(`缺少原图: ${sourcePath}`);
  if (manifest.items?.length !== 11) errors.push("当前批次必须包含 11 道题");
  const numbers = new Set();
  const ids = new Set();
  for (const item of manifest.items ?? []) {
    if (numbers.has(item.questionNumber)) errors.push(`题号重复: ${item.questionNumber}`);
    numbers.add(item.questionNumber);
    if (ids.has(item.problemId)) errors.push(`problemId 重复: ${item.problemId}`);
    ids.add(item.problemId);
    if (item.groupId !== GROUP_BY_NUMBER.get(item.questionNumber)) errors.push(`第 ${item.questionNumber} 题题组错误`);
    if (item.chapterId !== "functions" || item.sectionId !== "function-concepts-and-representation") errors.push(`第 ${item.questionNumber} 题分类错误`);
    if (!item.sourceLabel || !item.printedText || !Array.isArray(item.knowledgeTags) || item.knowledgeTags.length === 0) errors.push(`第 ${item.questionNumber} 题缺少来源、转录或标签`);
    if (item.confidence < 0.9 && item.status !== "needs_review") errors.push(`第 ${item.questionNumber} 题低置信度不能标记为 ${item.status}`);
    if (item.status === "published" && item.confidence < 0.95) errors.push(`第 ${item.questionNumber} 题未达到发布置信度`);
    const draftDir = path.join(root, "internal/senior-high/lesson-specs", item.problemId);
    for (const fileName of ["01_problem.md", "02_solution.md", "03_visual_steps.md"]) {
      if (!fs.existsSync(path.join(draftDir, fileName))) errors.push(`第 ${item.questionNumber} 题缺少 ${fileName}`);
    }
  }
  if (errors.length) throw new Error(errors.join("\n"));
  return manifest;
}

if (process.argv[1] && path.resolve(process.argv[1]) === currentFile) {
  const input = process.argv[2];
  if (!input) {
    console.error("用法: node tools/validate-senior-high-function-batch.mjs <manifest.json>");
    process.exitCode = 1;
  } else {
    try {
      validateFunctionBatch(path.resolve(input));
      console.log(`OK: ${path.resolve(input)}`);
    } catch (error) {
      console.error(error.message);
      process.exitCode = 1;
    }
  }
}
