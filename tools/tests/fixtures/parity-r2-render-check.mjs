// Used by the Python source/card test; never reads or rebuilds public courses.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createRequire} from 'node:module';

const context = vm.createContext({window: {}});
vm.runInContext(fs.readFileSync(new URL('../../../site/assets/practice/components.js', import.meta.url), 'utf8'), context);
const api = context.window.PracticeComponents;
const katex = createRequire(import.meta.url)('../../../site/assets/practice/vendor/katex-0.18.9/katex.min.js');
const render = text => katex.renderToString(text, {throwOnError: true, strict: 'ignore'});
function visit(value) {
  if (Array.isArray(value)) return value.forEach(visit);
  if (!value || typeof value !== 'object') return;
  for (const [key, item] of Object.entries(value)) {
    if (key === 'math' && typeof item === 'string') render(item);
    else if (typeof item === 'string') for (const match of item.matchAll(/\$\$([\s\S]*?)\$\$|\$([^$]+)\$/g)) render(match[1] ?? match[2]);
    else visit(item);
  }
}
const parts = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
visit(parts);
const graphs = parts.flatMap(p => [...(p.completion_graphs || []), ...(p.completion_graph ? [p.completion_graph] : [])]);
assert.ok(graphs.length);
for (const [i, graph] of graphs.entries()) {
  assert.ok(api.validateGraph(graph));
  const svg = api.graph({...graph, uid: 'r2-' + i});
  assert.match(svg, /^<svg/);
  assert.doesNotMatch(svg, /NaN|Infinity/);
  assert.match(svg, /sampled-trace/);
  const bad = structuredClone(graph);
  bad.params.traces[0].markers.push({x: 0, y: Infinity, closed: true});
  assert.equal(api.validateGraph(bad), false);
}
