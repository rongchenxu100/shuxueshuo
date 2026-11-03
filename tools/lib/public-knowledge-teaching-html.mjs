import { textHtml as renderText, shell } from './public-knowledge-html.mjs';
import { escapeHtml as h } from '../../site/assets/knowledge-next/resource-links.mjs';
import { KINDS, nodeHref, splitRef } from '../../site/assets/knowledge-next/model.mjs';
import { branches, previewHref } from '../../site/assets/knowledge-next/teaching-model.mjs';

const textHtml = (text) => renderText(text, { legacy: true });

export function teachingOutputs(teaching, nodes, manifest, resourceHtml, render) {
  const outputs = new Map(),
    byId = new Map(nodes.map((n) => [n.id, n]));
  const link = (ref) => {
    const { id, entry } = splitRef(ref),
      n = byId.get(id);
    const title = entry
      ? ['entries', 'operations', 'steps', 'branches']
          .flatMap((key) => n[key] || [])
          .find((item) => item.id === entry)?.title
      : null;
    if (entry && !title) throw Error(`审阅表引用条目不存在：${ref}`);
    return `<a href="${nodeHref(ref)}">${h(n.label)}${title ? ` · ${h(title)}` : ''}<small>（${KINDS[n.kind]}）</small></a>`;
  };
  const condition = (c) =>
    Object.entries(c)
      .map(([k, v]) => `${k} = ${v}`)
      .join('；') || '固定关联';
  const selection = (tree) =>
    branches(tree)
      .map(
        (b) =>
          `<p><small>${h(condition(b.conditions))}</small><br>${(Array.isArray(b.value) ? b.value : [b.value.ref]).map(link).join('、')}</p>`
      )
      .join('');
  const table = (head, rows) =>
    `<div class="teaching-table"><table><thead><tr>${head.map((x) => `<th>${x}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((x) => `<td>${x}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  const page = (title, body) =>
    shell(
      title,
      `<main id="main" class="workspace teaching-page"><section class="hero"><p class="eyebrow" data-teaching-mode>教学关联</p><h1>${h(title)}</h1><p data-preview-notice>本页用于查看教学关联；可进入正式练习或无记录预览。</p><nav><a href="/knowledge/">知识图谱</a> · <a href="/knowledge/topics/">专题与迁移审阅</a></nav></section>${body}</main>`,
      `<link rel="stylesheet" href="/assets/knowledge-next/teaching.css">`
    );
  const index = teaching.topics
    .map(
      (t) =>
        `<li><a href="/knowledge/topics/${t.id}/">${h(t.label)}</a> · <a href="/knowledge/topics/${t.id}/review/">题目、步骤和图解关联表</a></li>`
    )
    .join('');
  outputs.set(
    'topics/index.html',
    page(
      '教学关联迁移',
      `<p>${teaching.counts.problems} 道题 · ${teaching.counts.routes} 条路线 · ${teaching.counts.steps} 个步骤 · ${teaching.counts.tips} 个提示分支</p><ul>${index}<li><a href="/knowledge/topics/drills/">小题去向表 · ${teaching.drills.totalCount} 道</a></li><li><a href="/knowledge/topics/migration/">旧新节点身份清单 · ${teaching.migration.nodes.length} 个旧节点</a></li></ul><p>训练分组沿用现有编排；每道题的公共题型单独标注。仅按已提交通过的选择解析关联；候选分支未覆盖全部选项时，作答后显示。</p>`
    )
  );
  outputs.set(
    'topics/migration/index.html',
    page(
      '旧新节点身份清单',
      `<p>${h(teaching.migration.note)}</p>${table(
        ['旧节点 ID', '处理', '新公共身份或内部条目', '说明'],
        teaching.migration.nodes.map((r) => [
          h(r.legacy),
          h(r.action),
          r.targets.map(link).join('、'),
          h(r.reason)
        ])
      )}`
    )
  );
  outputs.set('teaching/migration.json', JSON.stringify(teaching.migration, null, 2) + '\n');
  for (const t of teaching.topics) {
    const cards = t.groups
      .map(
        (g) =>
          `<section id="group-${g.id}"><h2>${h(g.label)}</h2><p>${textHtml(g.description)}</p><ol class="teaching-problems">${g.problems
            .map((pid) => {
              const p = t.problems[pid];
              return `<li><a href="${h(p.path)}"><b>${h(p.label)}</b> · ${textHtml(p.statement)}</a> · <a href="${previewHref(p.path)}">无记录预览</a><p>公共题型：${p.types.map(link).join('、')}</p><p>路线：${Object.values(
                p.routes
              )
                .map((r) => h(r.label))
                .join('、')}</p></li>`;
            })
            .join('')}</ol></section>`
      )
      .join('');
    outputs.set(
      `topics/${t.id}/index.html`,
      page(
        t.label,
        `<p><a href="review/">查看本专题完整关联表 →</a></p><nav class="teaching-groups">${t.groups.map((g) => `<a href="#group-${g.id}">${h(g.label)}</a>`).join('')}</nav>${cards}`
      )
    );
    const pr = [],
      sr = [],
      tr = [];
    for (const [pid, p] of Object.entries(t.problems)) {
      outputs.set(
        `teaching/problems/${pid}.json`,
        JSON.stringify({ topic: t.id, id: pid, ...p }, null, 2) + '\n'
      );
      const pl = `<a href="${previewHref(p.path)}">${h(p.label)}</a>`;
      for (const [rid, r] of Object.entries(p.routes)) {
        pr.push([pl, h(r.label), p.types.map(link).join('、'), selection(r.methods)]);
        for (const [sid, s] of Object.entries(r.steps)) {
          sr.push([
            pl,
            `<code>${rid}</code>`,
            `<code>${sid}</code> · ${s.position}. ${h(s.title)}`,
            selection(s.refs) || h(s.reason)
          ]);
          for (const b of branches(s.tip))
            tr.push([
              pl,
              `${h(rid)} / ${h(sid)}`,
              h(condition(b.conditions)),
              link(b.value.ref),
              b.value.resource
                ? `<code>${h(b.value.resource)}</code>${b.value.case ? ` · ${h(b.value.case)}` : ''}`
                : '正文与例子',
              textHtml(b.value.note || '')
            ]);
        }
      }
    }
    outputs.set(
      `topics/${t.id}/review/index.html`,
      page(
        `${t.label}关联表`,
        `<p><a href="../">回到专题目录</a></p><h2>题目与路线</h2>${table(['题目', '原路线', '公共题型', '实际方法 / 待选择的候选方法'], pr)}<h2>步骤关联</h2>${table(['题目', '路线', '步骤', '关联'], sr)}<h2>图解提示分支</h2><p>此审阅表含完成后的说明；练习弹层在步骤完成前隐藏这些说明。</p>${table(['题目', '步骤', '条件', '节点或条目', '资源 / case', '完成后说明'], tr)}`
      )
    );
  }
  const drills = teaching.drills;
  outputs.set(
    'topics/drills/index.html',
    page(
      '小题迁移去向',
      `<p>迁移来源 ${drills.sourceCount} 道${drills.newCount ? `；新增 ${drills.newCount} 道` : ''}；有效 ${drills.active} 道；暂时停用 ${drills.retired} 道。五题检测从节点详情页进入，实际资格以学习服务为准。</p>${table(
        ['主要考查节点', '有效题数', '五题检测资格'],
        drills.sets.map((s) => [link(s.node), s.count, s.eligible ? '数量满足' : '不足五题'])
      )}${table(
        ['原题身份', '迁移动作', '新归属', '说明'],
        drills.records.map((r) => [
          h(`${r.origin.node} / ${r.origin.item}`),
          h(r.action),
          r.target ? link(r.target) : '暂时停用',
          h(r.reason)
        ])
      )}`
    )
  );
  outputs.set('teaching/reverse.json', JSON.stringify(teaching.reverse, null, 2) + '\n');
  outputs.set('teaching/drill-audit.json', JSON.stringify(drills, null, 2) + '\n');
  for (const [id, resource] of Object.entries(manifest.resources)) {
    outputs.set(
      `teaching/resources/${id}.json`,
      JSON.stringify({ ...resource, html: resourceHtml[id] }) + '\n'
    );
  }
  outputs.set(
    'teaching/catalog.json',
    JSON.stringify(
      Object.fromEntries(
        nodes.map((n) => [
          n.id,
          {
            id: n.id,
            label: n.label,
            kind: n.kind,
            summary: n.summary,
            conditions: n.conditions,
            entries: Object.fromEntries(
              ['entries', 'operations', 'steps'].flatMap((k) => (n[k] || []).map((e) => [e.id, e.title]))
            )
          }
        ])
      )
    ) + '\n'
  );
  for (const n of nodes.filter((n) => !['textbook', 'chapter', 'section'].includes(n.kind))) {
    const html = render.detailBody(n, {}, { includeResources: false });
    outputs.set(`teaching/nodes/${n.id}.json`, JSON.stringify({ id: n.id, html }) + '\n');
  }
  outputs.set(
    'teaching/manifest.json',
    JSON.stringify({
      schemaVersion: 1,
      module: '/assets/knowledge-next/practice-preview.mjs',
      counts: teaching.counts
    }) + '\n'
  );
  return outputs;
}
