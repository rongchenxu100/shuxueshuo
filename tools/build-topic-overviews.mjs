#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadSources, repoRoot} from './lib/public-knowledge-sources.mjs';
import {loadTeaching} from './lib/public-knowledge-teaching.mjs';
import {topicOverviewOutputs, PAGE_MARKER} from './lib/topic-overview-html.mjs';

export async function generateTopicOverviews(root = repoRoot) {
  const {nodes, manifest} = await loadSources(root);
  const {topics} = await loadTeaching(root, nodes, manifest);
  const indexHtml = await fs.readFile(path.join(root, 'site/topics/index.html'), 'utf8');
  return topicOverviewOutputs(topics, nodes, indexHtml);
}

export async function publishTopicOverviews({root = repoRoot, check = false} = {}) {
  const outputs = await generateTopicOverviews(root), changes = [];
  for (const [name, body] of outputs) {
    let current;
    try { current = await fs.readFile(path.join(root, 'site', name), 'utf8'); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (current === body) continue;
    if (name !== 'topics/index.html' && current !== undefined && !current.includes(PAGE_MARKER)) throw Error(`拒绝覆盖非生成专题页：${name}`);
    changes.push([name, body]);
  }
  if (check && changes.length) throw Error(`专题总览缺失或过期（运行 node tools/build-topic-overviews.mjs）：\n${changes.map(([name]) => name).join('\n')}`);
  for (const [name, body] of changes) {
    const file = path.join(root, 'site', name);
    await fs.mkdir(path.dirname(file), {recursive:true});
    await fs.writeFile(file, body);
  }
  return {changed:changes.length};
}

if (process.argv[1] && await fs.realpath(process.argv[1]) === await fs.realpath(fileURLToPath(import.meta.url))) {
  try {
    if (process.argv.slice(2).some(arg => arg !== '--check')) throw Error('Usage: node tools/build-topic-overviews.mjs [--check]');
    console.log(JSON.stringify(await publishTopicOverviews({check:process.argv.includes('--check')})));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
