import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

export const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
export function publicGraphNodes(nodes, homes = new Map()) {
  return nodes.map(n => ({id: n.id, kind: n.kind, subtype: n.subtype, label: n.label,
    summary: n.summary, aliases: n.aliases || [], ...(n.status ? {status: n.status} : {}),
    ...(homes.has(n.id) ? {home: homes.get(n.id)} : {}),
    ...(n.kind === 'method' ? {steps: n.steps.map(s => ({id: s.id, title: s.title,
      calls: (s.calls || []).map(c => c.ref), ...(s.rule ? {rule: s.rule} : {})}))} : {})}));
}
export async function loadSources(root = repoRoot) {
  const dir = path.join(root,'site/data/knowledge-next');
  const manifest = JSON.parse(await fs.readFile(path.join(dir,'catalog.json'),'utf8'));
  const names = (await fs.readdir(path.join(dir,'nodes'))).filter(f=>f.endsWith('.json')).sort();
  const nodes = await Promise.all(names.map(async name=>{
    const node=JSON.parse(await fs.readFile(path.join(dir,'nodes',name),'utf8'));
    if (`${node.id}.json`!==name) throw new Error(`文件名与 ID 不一致：${name}`);
    return node;
  }));
  const outline = JSON.parse(await fs.readFile(path.join(dir,'outline.json'),'utf8'));
  return {nodes,manifest,outline};
}

