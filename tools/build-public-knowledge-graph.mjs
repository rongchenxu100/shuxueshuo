#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {validateGraph, RESERVED_PATHS} from '../site/assets/knowledge-next/model.mjs';
import {rewriteResourceLinks} from '../site/assets/knowledge-next/resource-links.mjs';
import {buildCity, homeChapters, recorded} from '../site/assets/knowledge-next/city.mjs';
import {makeRenderer, textHtml} from './lib/public-knowledge-html.mjs';
import {loadTeaching} from './lib/public-knowledge-teaching.mjs';
import {teachingOutputs} from './lib/public-knowledge-teaching-html.mjs';
import {exportRows, practiceCompatibility} from './lib/public-knowledge-export.mjs';
import {redirectPage, legacyNodeOutputs} from './lib/public-knowledge-compat.mjs';

import {repoRoot, loadSources} from './lib/public-knowledge-sources.mjs';
export {repoRoot, loadSources};

const decode = text => text.replace(/&(lt|gt|amp|quot|#39);/g,(_s,k)=>({lt:'<',gt:'>',amp:'&',quot:'"','#39':"'"}[k]));
export function renderResourceMath(html) {
  return html.split(/(<[^>]*>)/g).map((part,i)=>i%2 || !part.includes('$') ? part : textHtml(decode(part))).join('');
}

async function fileUnderSite(root, url) {
  if (!url.startsWith('/') || url.startsWith('//') || url.includes('..') || /[?#]/.test(url)) throw new Error(`资源必须是明确的站内文件路径：${url}`);
  const file=path.join(root,'site',url);
  if (!(await fs.stat(file)).isFile()) throw new Error(`资源不是文件：${url}`);
  return file;
}

export async function generate(root = repoRoot) {
  const {nodes,manifest,outline}=await loadSources(root), edges=validateGraph(nodes,manifest);
  const teaching=await loadTeaching(root,nodes,manifest);
  for (const n of nodes) if (RESERVED_PATHS.includes(n.id)) throw new Error(`节点 ID 与页面路径冲突：${n.id}`);
  const city=buildCity(outline,{nodes,edges,defaultScope:manifest.defaultScope}), homes=homeChapters(outline,{nodes,edges});
  const bookShort=new Map(city.books.map(b=>[b.id,b.short]));
  const chapters=city.chapters.map(c=>({id:c.id,book:bookShort.get(c.book),number:c.number,label:c.label,strand:c.strand,recorded:recorded(c),...(c.node?{node:c.node}:{}),sections:c.sections.filter(s=>s.node).map(s=>({id:s.node,number:s.number,label:s.label}))}));
  // Every current example URL must resolve. No problem routes or steps are copied.
  for (const n of nodes) for (const e of n.examples || []) if (e.url) {
    if (!/^\/(1|2)\/q\d{2}\/$/.test(e.url)) throw new Error(`例题地址不符合本站题页格式：${e.url}`);
    await fileUnderSite(root,`${e.url}index.html`);
  }
  const resourceHtml={}, labels=Object.fromEntries(nodes.map(n=>[n.id,n.label]));
  for (const [id,resource] of Object.entries(manifest.resources)) {
    const file=await fileUnderSite(root,resource.module);
    if (!/^[a-z][a-z0-9-]*$/.test(resource.scope)) throw new Error(`非法图解样式作用域 ${id}`);
    const mod=(await import(pathToFileURL(file).href)).default;
    if (resource.part && typeof mod[resource.part]!=='function') throw new Error(`图解 ${id} 的模块没有 ${resource.part}()`);
    const raw=(resource.part ? mod[resource.part] : mod.render).call(mod,{node:null,tip:null,topic:null});
    const rewritten=rewriteResourceLinks(raw,manifest.resourceLinks,labels);
    if (rewritten.includes('data-explain-open') || /href=["']\/knowledge-next\//.test(rewritten)) throw new Error(`图解仍包含旧导航：${id}`);
    resourceHtml[id]=renderResourceMath(rewritten).replace(/^[ \t]+$/gm,'');
    if (mod.stylesheet) {
      const u=new URL(mod.stylesheet);
      const relative=path.relative(path.dirname(await fs.realpath(file)),fileURLToPath(u)).split(path.sep).join('/');
      resource.stylesheet=path.posix.join(path.posix.dirname(resource.module),relative);
      await fileUnderSite(root,resource.stylesheet);
    }
    const resourceHash=createHash('sha256').update(await fs.readFile(file));
    if(resource.stylesheet) resourceHash.update(await fs.readFile(path.join(root,'site',resource.stylesheet)));
    resource.version=resourceHash.digest('hex').slice(0,12);
  }
  // Detection eligibility is private API state, never inferred from public IDs.
  manifest.drills=[];
  const rows = await exportRows(root,{nodes,edges,manifest,teaching}), release = rows._meta;
  const practiceVersions = Object.fromEntries(rows.practice_problems.map(problem => [problem.id, practiceCompatibility(problem)]));
  // Pages load scripts and styles straight from site/assets/knowledge-next. Those
  // are served no-cache, so editing a module never rewrites the generated pages.
  const render=makeRenderer(nodes,edges,manifest,city,homes,chapters);
  const graph={schemaVersion:1,defaultScope:manifest.defaultScope,chapters,collections:city.collections || [],nodes:nodes.map(n=>({id:n.id,kind:n.kind,subtype:n.subtype,label:n.label,summary:n.summary,aliases:n.aliases || [],...(n.status?{status:n.status}:{}),...(homes.has(n.id)?{home:homes.get(n.id)}:{}),...(n.kind==='method'?{steps:n.steps.map(s=>({id:s.id,title:s.title,calls:(s.calls || []).map(c=>c.ref),...(s.rule?{rule:s.rule}:{})}))}:{})})),edges};
  const outputs=new Map([
    ['index.html',render.overview()],['nodes/index.html',render.list()],['3d/index.html',render.tower()],
    ['graph.json',JSON.stringify(graph,null,2)+'\n'],['city.json',JSON.stringify(city,null,2)+'\n'],
  ]);
  for (const c of chapters.filter(c=>c.recorded)) outputs.set(`chapters/${c.id}/index.html`,render.chapter(c));
  for (const c of city.collections || []) outputs.set(`collections/${c.id}/index.html`,render.chapter(c));
  for (const n of nodes) outputs.set(`${n.id}/index.html`,render.detail(n,resourceHtml));
  for (const [file,body] of teachingOutputs(teaching,nodes,manifest,resourceHtml,render)) outputs.set(file,body);
  // One release fingerprint for deployment verification and rollback. Individual
  // outputs depend on their own content; practice compatibility is per problem.
  outputs.set('teaching/version.json',JSON.stringify(release,null,2)+'\n');
  outputs.set('teaching/problems.json', JSON.stringify({
    problems: Object.fromEntries(teaching.topics.flatMap(topic => Object.entries(topic.problems).map(([id, problem]) => [id, {path: problem.path, topic: topic.id}]))),
  }, null, 2) + '\n');
  for (const topic of teaching.topics) outputs.set(`teaching/topics/${topic.id}.json`, JSON.stringify({
    id: topic.id, label: topic.label, groups: topic.groups, problems: topic.problems,
    ...(topic.path ? {path: topic.path} : {}),
    ...(topic.presentation ? {presentation: topic.presentation} : {}),
  }, null, 2) + '\n');
  for (const [name,body] of outputs) if (/^teaching\/problems\/.+\.json$/.test(name)) {
    const problem = JSON.parse(body);
    outputs.set(name,JSON.stringify({...problem, ...practiceVersions[problem.id]},null,2)+'\n');
  }
  for (const [name, body] of legacyNodeOutputs(teaching.migration, nodes)) outputs.set(name, body);
  const compatibility = new Map([...outputs.keys()].filter(name => name.endsWith('/index.html') || name === 'index.html').map(name => [name, redirectPage(`/knowledge/${name.replace(/index\.html$/, '')}`)]));
  for (const files of [outputs, compatibility]) files.set('manifest.json',JSON.stringify({generator:'tools/build-public-knowledge-graph.mjs',schemaVersion:1,nodeCounts:manifest.expectedCounts,files:[...files.keys(), 'manifest.json'].sort()},null,2)+'\n');
  return {outputs,compatibility,nodes,edges,manifest,teaching};
}

async function filesBelow(dir, prefix='', directories=new Set()) {
  let entries; try {entries=await fs.readdir(dir,{withFileTypes:true});} catch(e) {if(e.code==='ENOENT') return []; throw e;}
  const result=[];
  for(const ent of entries) {
    if(ent.isSymbolicLink()) throw new Error(`输出目录不允许符号链接：${ent.name}`);
    const rel=path.posix.join(prefix,ent.name);
    if(ent.isDirectory()) {
      directories.add(rel);
      result.push(...await filesBelow(path.join(dir,ent.name),rel,directories));
    }
    else result.push(rel);
  }
  return result;
}

function parentDirectories(files) {
  const result=new Set();
  for (const file of files) {
    for (let dir=path.posix.dirname(file); dir!=='.' && dir!=='/'; dir=path.posix.dirname(dir)) result.add(dir);
  }
  return result;
}

export async function publish({root=repoRoot, check=false}={}) {
  const {outputs,compatibility,nodes,edges}=await generate(root);
  const bootstrap = JSON.parse(await fs.readFile(path.join(root, 'tools/data/public-knowledge-legacy-files.json'), 'utf8'));
  const stale=[];
  const writes=[], manifests=[], removals=[], emptyDirectories=[];
  // Validate both output trees completely before changing either one. In
  // particular, a failed bootstrap must not install a manifest that would
  // bypass the old-file hash checks on the next run.
  for (const [directory, files] of [['knowledge', outputs], ['knowledge-next', compatibility]]) {
    const out=path.join(root,'site',directory);
    const directories=new Set();
    const existing=await filesBelow(out,'',directories);
    let previous;
    try {previous=JSON.parse(await fs.readFile(path.join(out,'manifest.json'),'utf8'));} catch(error) {if(error.code!=='ENOENT') throw error;}
    if(previous && previous.generator !== 'tools/build-public-knowledge-graph.mjs') throw Error(`无法管理其他生成器的目录：${directory}`);
    const owned = new Set(previous ? [...previous.files, 'manifest.json'] : directory === 'knowledge' ? Object.keys(bootstrap.files) : []);
    // The bootstrap inventory still identifies old directory ownership after
    // the first replacement. Old hashed bundles have a generator-only layout.
    const managedDirectories=parentDirectories([...owned,...(directory==='knowledge' ? Object.keys(bootstrap.files) : [])]);
    if(previous) for (const dir of directories) if(/^assets\/[a-f0-9]{12}$/.test(dir)) {
      managedDirectories.add(dir);
      managedDirectories.add('assets');
    }
    for (const [rel,body] of files) {
      const file=path.join(out,rel);
      let old; try {old=await fs.readFile(file,'utf8');} catch(e) {if(e.code!=='ENOENT') throw e;}
      if(old!==body) {
        if(old !== undefined && !owned.has(rel)) throw Error(`拒绝覆盖未登记文件：${directory}/${rel}`);
        if(!previous && old !== undefined && bootstrap.files[rel] !== createHash('sha256').update(old).digest('hex')) throw Error(`首次替换发现旧文件已被修改：${directory}/${rel}`);
        stale.push(`${directory}/${rel}`);
        (rel==='manifest.json' ? manifests : writes).push({file,body});
      }
    }
    // Unknown files are never removed. The bootstrap inventory is used only once.
    for (const rel of existing) if(owned.has(rel) && !files.has(rel)) {
      const file=path.join(out,rel);
      if(!previous && bootstrap.files[rel] !== createHash('sha256').update(await fs.readFile(file)).digest('hex')) throw Error(`拒绝删除已修改的旧文件：${directory}/${rel}`);
      stale.push(`obsolete: ${directory}/${rel}`);
      removals.push(file);
    }
    const remainingFiles=new Set([...existing.filter(rel=>!owned.has(rel) || files.has(rel)),...files.keys()]);
    const removedDirectories=new Set();
    for (const dir of [...directories].sort((a,b)=>b.split('/').length-a.split('/').length)) {
      if(!managedDirectories.has(dir)) continue;
      const prefix=dir+'/';
      if([...remainingFiles].some(file=>file.startsWith(prefix))) continue;
      if([...directories].some(child=>child.startsWith(prefix) && !removedDirectories.has(child))) continue;
      stale.push(`obsolete directory: ${directory}/${dir}`);
      removedDirectories.add(dir);
      emptyDirectories.push(path.join(out,dir));
    }
  }
  if(check && stale.length) throw new Error(`生成产物缺失或过期（运行 node tools/build-public-knowledge-graph.mjs）：\n${stale.join('\n')}`);
  if(!check) {
    for (const {file,body} of writes) {await fs.mkdir(path.dirname(file),{recursive:true});await fs.writeFile(file,body);}
    for (const file of removals) await fs.unlink(file);
    for (const directory of emptyDirectories) await fs.rmdir(directory).catch(error=>{if(error.code!=='ENOENT') throw error;});
    // Publish ownership only after all content updates and removals succeed.
    for (const {file,body} of manifests) {await fs.mkdir(path.dirname(file),{recursive:true});await fs.writeFile(file,body);}
  }
  return {nodes:nodes.length,edges:edges.length,files:outputs.size,compatibility:compatibility.size,changed:stale.length};
}
if(process.argv[1] && await fs.realpath(process.argv[1])===await fs.realpath(fileURLToPath(import.meta.url))) {
  if(process.argv.slice(2).some(a=>a!=='--check')) { console.error('Usage: node tools/build-public-knowledge-graph.mjs [--check]');process.exitCode=1; }
  else try {console.log(JSON.stringify(await publish({check:process.argv.includes('--check')})));} catch(e) {console.error(e.message);process.exitCode=1;}
}
