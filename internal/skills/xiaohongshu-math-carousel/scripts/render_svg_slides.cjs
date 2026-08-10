#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");

let sharp;
try {
  sharp = require("sharp");
} catch (_error) {
  console.error("ERROR: sharp is required. Load the bundled workspace dependencies and set NODE_PATH to their node_modules directory.");
  process.exit(2);
}

function fail(message) {
  console.error(`ERROR: ${message}`);
  process.exit(1);
}

function parseSize(args) {
  let width = 1080;
  let height = 1440;
  const positional = [];
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] === "--width") {
      width = Number(args[++index]);
    } else if (args[index] === "--height") {
      height = Number(args[++index]);
    } else {
      positional.push(args[index]);
    }
  }
  if (!Number.isInteger(width) || width <= 0 || !Number.isInteger(height) || height <= 0) {
    fail("width and height must be positive integers");
  }
  return { width, height, positional };
}

function assertSvgCanvas(svgText, sourcePath, width, height) {
  const viewBoxMatch = svgText.match(/\bviewBox\s*=\s*["']\s*([^"']+?)\s*["']/i);
  if (!viewBoxMatch) fail(`${sourcePath}: missing viewBox`);
  const values = viewBoxMatch[1].trim().split(/[\s,]+/).map(Number);
  if (values.length !== 4 || values.some((value) => !Number.isFinite(value))) {
    fail(`${sourcePath}: invalid viewBox`);
  }
  const expected = [0, 0, width, height];
  if (values.some((value, index) => Math.abs(value - expected[index]) > 1e-9)) {
    fail(`${sourcePath}: expected viewBox="0 0 ${width} ${height}", found "${viewBoxMatch[1]}"`);
  }
  if (/<(?:script|foreignObject)\b/i.test(svgText)) {
    fail(`${sourcePath}: script and foreignObject are not allowed in deterministic slide SVGs`);
  }
}

async function renderOne(sourcePath, outputPath, width, height) {
  if (!fs.existsSync(sourcePath)) fail(`missing SVG source: ${sourcePath}`);
  const svgText = fs.readFileSync(sourcePath, "utf8");
  assertSvgCanvas(svgText, sourcePath, width, height);
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  await sharp(Buffer.from(svgText), { density: 144 })
    .resize(width, height, { fit: "fill" })
    .png({ compressionLevel: 9, adaptiveFiltering: true })
    .toFile(outputPath);
  const metadata = await sharp(outputPath).metadata();
  if (metadata.width !== width || metadata.height !== height || metadata.format !== "png") {
    fail(`${outputPath}: rasterized output has unexpected metadata`);
  }
  console.log(`OK ${path.basename(sourcePath)} -> ${path.basename(outputPath)} (${width}x${height})`);
}

async function renderFolder(folderPath, width, height) {
  const sourceDir = path.join(folderPath, "source");
  const manifestPath = path.join(sourceDir, "slide-manifest.json");
  if (!fs.existsSync(manifestPath)) fail(`missing manifest: ${manifestPath}`);
  let manifest;
  try {
    manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  } catch (error) {
    fail(`${manifestPath}: ${error.message}`);
  }
  if (!Array.isArray(manifest.slides)) fail(`${manifestPath}: slides must be an array`);
  let rendered = 0;
  for (const [index, slide] of manifest.slides.entries()) {
    if (!slide || !["svg", "hybrid", "imagegen"].includes(slide.mode) || typeof slide.png !== "string") {
      fail(`${manifestPath}: slides[${index}] has an invalid mode or png name`);
    }
    if (slide.mode === "imagegen") continue;
    if (typeof slide.source !== "string" || path.extname(slide.source).toLowerCase() !== ".svg") {
      fail(`${manifestPath}: ${slide.png} requires an SVG source`);
    }
    const sourcePath = path.resolve(sourceDir, slide.source);
    if (path.dirname(sourcePath) !== path.resolve(sourceDir)) {
      fail(`${manifestPath}: SVG sources must stay directly inside source/`);
    }
    const outputPath = path.resolve(folderPath, slide.png);
    if (path.dirname(outputPath) !== path.resolve(folderPath)) {
      fail(`${manifestPath}: PNG outputs must stay directly inside the post folder`);
    }
    await renderOne(sourcePath, outputPath, width, height);
    rendered += 1;
  }
  if (!rendered) fail(`${manifestPath}: no svg or hybrid slides to render`);
}

async function main() {
  const { width, height, positional } = parseSize(process.argv.slice(2));
  if (positional.length < 1 || positional.length > 2) {
    fail("usage: render_svg_slides.cjs <post-folder> OR <source.svg> <output.png> [--width 1080 --height 1440]");
  }
  const inputPath = path.resolve(positional[0]);
  const stat = fs.existsSync(inputPath) ? fs.statSync(inputPath) : null;
  if (!stat) fail(`input does not exist: ${inputPath}`);
  if (stat.isDirectory()) {
    if (positional.length !== 1) fail("folder mode does not accept an output path");
    await renderFolder(inputPath, width, height);
    return;
  }
  if (path.extname(inputPath).toLowerCase() !== ".svg" || positional.length !== 2) {
    fail("single-file mode requires <source.svg> <output.png>");
  }
  await renderOne(inputPath, path.resolve(positional[1]), width, height);
}

main().catch((error) => fail(error.stack || error.message));
