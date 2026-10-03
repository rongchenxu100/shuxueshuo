#!/usr/bin/env node
// Keep static top-level entry pages connected to the shared account component.
// Lesson pages load it through their shared runtimes, including future builds.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const pages = ['index.html', 'nav/index.html', 'senior-high/index.html', 'mistake-book/index.html',
  'topics/index.html', '1/index.html', '2/index.html'];
function collect(directory) {
  for (const entry of fs.readdirSync(directory, {withFileTypes: true})) {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) collect(file);
    else if (entry.name.endsWith('.html')) {
      const source = fs.readFileSync(file, 'utf8');
      if (!/lesson-page-runtime\.js|practice\/runtime\.js|js\/problem-page\.js|http-equiv="refresh"/i.test(source)) {
        pages.push(path.relative(path.join(root, 'site'), file));
      }
    }
  }
}
collect(path.join(root, 'site/problems'));
for (const page of pages) {
  const file = path.join(root, 'site', page);
  let source = fs.readFileSync(file, 'utf8');
  if (source.includes('/auth/site-auth.js')) continue;
  const relative = path.relative(path.dirname(file), path.join(root, 'site/assets/auth/site-auth.js'));
  source = source.replace(/^([ \t]*)<\/head>/m, (_, indent) =>
    `${indent}  <script type="module" src="${relative}?v=1"></script>\n${indent}</head>`);
  fs.writeFileSync(file, source);
}
