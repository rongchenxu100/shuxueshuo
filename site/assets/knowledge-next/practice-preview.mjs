import { select, confirmedChoices, libraryPath, previewTarget, previewHref } from './teaching-model.mjs';
import { KINDS, splitRef, nodeHref } from './model.mjs';
import { escapeHtml as h } from './resource-links.mjs';
import { stylesheet, mountResource } from './resource-runtime.mjs';

function math(root) {
  root.querySelectorAll('[data-math-text]').forEach((el) => {
    if (!el.querySelector('.katex')) window.PracticeMath?.render(el, el.textContent);
  });
}
async function read(url) {
  const response = await fetch(url, { cache: 'no-cache' });
  if (!response.ok) throw Error(`加载失败（${response.status}）`);
  return response.json();
}
export async function createPreview(lesson, host, {learning = false, useServerProgress = () => learning, onShown = null, getConfirmedChoices = null, getPassedFields = null, expectedContentVersion = null, expectedPracticeVersion = null, problem: loaded = null} = {}) {
  const [problem, catalog] = await Promise.all([
    loaded || read(`/knowledge/teaching/problems/${encodeURIComponent(lesson.id)}.json`),
    read('/knowledge/teaching/catalog.json'),
    stylesheet(new URL('./practice-preview.css', import.meta.url).pathname)
  ]);
  if (expectedPracticeVersion ? problem.practice_version !== expectedPracticeVersion
    : expectedContentVersion && problem.content_version !== expectedContentVersion) {
    throw Object.assign(Error('本题关联版本已变化，请刷新页面后再保存。'), {code: 'content_version_mismatch'});
  }
  const topic = `/knowledge/topics/${problem.topic}/`;
  const modeHref = path => previewHref(path, learning);
  const label = (ref) => {
    const { id, entry } = splitRef(ref),
      n = catalog[id];
    return `${n.label}${entry ? ` · ${n.entries[entry]}` : ''}`;
  };
  const chip = (ref) =>
    `<a href="${modeHref(nodeHref(ref))}">${h(label(ref))}<small>${KINDS[catalog[splitRef(ref).id].kind]}</small></a>`;
  const choiceSteps = Object.values(lesson.routes)
    .flat()
    .filter((s) => s.interaction.type === 'choice');
  const optionValues = Object.fromEntries(
    choiceSteps.map((s) => [s.interaction.field, s.interaction.options.map((o) => o.value)])
  );
  function selection(tree, choices, passed) {
    const { actual, candidates, withheld } = select(tree, choices, optionValues, passed);
    const refs = [...new Set(actual.flatMap((b) => b.value))];
    return `${refs.map(chip).join('')}${candidates.length ? `<span class="kxp-candidates">候选关联（未确认选择）：${[...new Set(candidates.flatMap((b) => b.value))].map(chip).join('')}</span>` : ''}${withheld ? '<span class="kxp-candidates">作答后显示对应关联</span>' : ''}`;
  }
  const box = document.createElement('div');
  box.className = 'kxp-associations';
  host.append(box);
  box.addEventListener('click', (event) => {
    const button = event.target.closest?.('[data-node-ref]');
    if (button) openNode(button.dataset.nodeRef);
  });
  // Preserve the preview on topic/back/adjacent-problem navigation.
  const targets = { paths: problem.problemPaths, library: libraryPath(problem.path), topic, learning };
  for (const a of document.querySelectorAll('a[href]')) {
    const url = new URL(a.href, location.href);
    if (url.origin !== location.origin) continue;
    const href = previewTarget(url, targets);
    if (href) a.href = href;
  }
  const choices = Object.fromEntries(choiceSteps.map((s) => [s.interaction.field, s.interaction.options]));
  const conditionLabel = (conditions) =>
    Object.entries(conditions)
      .map(([field, value]) => choices[field]?.find((o) => o.value === value)?.label || value)
      .join('，');
  // Navigation mode is independent of recording availability. Guests and local
  // fallback sessions use only passed local choices; recorded sessions must not
  // interpret restored standard answers or pending submissions as real choices.
  const confirmed = (state) => useServerProgress() ? (getConfirmedChoices?.() || {}) : confirmedChoices(lesson.routes[state.method], state);
  const passedFields = (state) => useServerProgress() ? (getPassedFields?.() || []) : (lesson.routes[state.method] || [])
    .slice(0, state.active).filter(step => step.interaction.type === 'choice').map(step => step.interaction.field);
  const resources = new Map();
  function readResource(id) {
    if (!resources.has(id)) {
      resources.set(
        id,
        read(`/knowledge/teaching/resources/${encodeURIComponent(id)}.json`).catch((error) => {
          resources.delete(id);
          throw error;
        })
      );
    }
    return resources.get(id);
  }
  // Route-level methods of every route; a conditional method stays hidden until
  // the choice that decides it is passed, exactly like step hints. Only methods
  // of a confirmed branch of the current route are marked as current.
  function problemMethods(state, picked, passed) {
    const methods = new Map();
    for (const [rid, route] of Object.entries(problem.routes)) {
      const current = rid === state.method;
      const { actual, candidates } = select(route.methods, current ? picked : {}, optionValues, current ? passed : []);
      for (const ref of actual.flatMap((b) => b.value)) methods.set(ref, methods.get(ref) || current);
      for (const ref of candidates.flatMap((b) => b.value)) if (!methods.has(ref)) methods.set(ref, false);
    }
    return methods;
  }
  const nodeButton = (ref, current = false) => {
    const kind = catalog[splitRef(ref).id].kind;
    return `<button type="button" class="kxp-chip${current ? ' is-current' : ''}" data-kind="${kind}" data-node-ref="${h(ref)}"${current ? ' title="当前解法用到"' : ''}><i aria-hidden="true"></i><span>${h(label(ref))}</span><small>${KINDS[kind]}</small></button>`;
  };
  let dialog = null,
    cleanup = null,
    ticket = 0,
    shownFor = null;
  function update(snapshot) {
    const route = problem.routes[snapshot.state.method],
      picked = confirmed(snapshot.state), passed = passedFields(snapshot.state);
    const methods = problemMethods(snapshot.state, picked, passed);
    const marked = route && Object.keys(problem.routes).length > 1;
    box.innerHTML = `<span class="kxp-label">本题涉及</span><div class="kxp-chips">${problem.types.map((ref) => nodeButton(ref)).join('')}${[...methods].map(([ref, current]) => nodeButton(ref, marked && current)).join('')}</div>${learning ? '' : `<a class="kxp-review" href="${modeHref(topic + 'review/')}">关联审阅表</a>`}`;
    document.querySelectorAll('.kxp-step-refs').forEach((el) => el.remove());
    // Per-step associations are a review aid; the formal exercise keeps steps clean.
    if (route && !learning)
      lesson.routes[snapshot.state.method].forEach((step, i) => {
        const card = document.getElementById(`step-${i}`);
        if (!card) return;
        const refs = document.createElement('div');
        refs.className = 'kxp-step-refs';
        refs.innerHTML = `<span>本步关联</span>${selection(route.steps[step.id].refs, picked, passed)}`;
        card.append(refs);
      });
    // Do not leave a sheet from a previous route/attempt on screen.
    const key = `${snapshot.attempt_id}|${snapshot.state.method}`;
    if (shownFor !== null && shownFor !== key && dialog?.open) dialog.close();
    shownFor = key;
  }
  function close() {
    ticket++;
    cleanup?.();
    cleanup = null;
  }
  let history = [];
  function sheet(title, kind = '') {
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.className = 'kxp-sheet';
      dialog.setAttribute('aria-labelledby', 'kxp-sheet-title');
      dialog.innerHTML =
        '<header><button type="button" class="kxp-back" aria-label="返回上一项" hidden>‹</button><div class="kxp-heading"><small class="kxp-sheet-kind"></small><h2 id="kxp-sheet-title"></h2></div><button type="button" class="kxp-close" aria-label="关闭">×</button></header><div class="kxp-sheet-body"></div><footer class="kxp-sheet-foot" hidden></footer>';
      document.body.append(dialog);
      dialog.querySelector('.kxp-close').onclick = () => dialog.close();
      dialog.querySelector('.kxp-back').onclick = () => {
        history.pop();
        const previous = history.pop();
        if (typeof previous === 'string') openNode(previous, true);
        else previous?.reopen();
      };
      // A click on the backdrop lands on the dialog element itself.
      dialog.addEventListener('click', (event) => {
        if (event.target === dialog) return dialog.close();
        const a = event.target.closest?.('.kxp-sheet-body a[href]');
        if (a && !event.defaultPrevented) follow(a, event);
      });
      dialog.addEventListener('close', () => {
        close();
        history = [];
      });
    }
    close();
    heading(title, kind);
    dialog.querySelector('.kxp-back').hidden = history.length < 2;
    dialog.querySelector('.kxp-sheet-foot').hidden = true;
    if (!dialog.open) dialog.showModal();
    return dialog.querySelector('.kxp-sheet-body');
  }
  function heading(title, kind = '', prefix = '') {
    dialog.querySelector('#kxp-sheet-title').textContent = title;
    const kicker = dialog.querySelector('.kxp-sheet-kind');
    kicker.textContent = [prefix, kind && KINDS[kind]].filter(Boolean).join(' · ');
    kicker.hidden = !kicker.textContent;
    dialog.setAttribute('data-kind', kind);
  }
  function footLink(ref) {
    const foot = dialog.querySelector('.kxp-sheet-foot');
    foot.innerHTML = `<a href="${modeHref(nodeHref(ref))}" target="_blank" rel="noopener">打开完整页面 ↗</a>`;
    foot.hidden = false;
  }
  // Any link in the sheet, including ones a diagram adds later: in-page anchors
  // scroll inside the sheet, catalog nodes open in place (with a way back), and
  // anything else opens in a new tab so the exercise and its progress stay put.
  function follow(a, event) {
    const href = a.getAttribute('href');
    if (href.startsWith('#')) {
      event.preventDefault();
      dialog.querySelector('.kxp-sheet-body').querySelector(`[id="${CSS.escape(href.slice(1))}"]`)?.scrollIntoView({ block: 'start' });
      return;
    }
    const url = new URL(href, location.href);
    const target = url.origin === location.origin && url.pathname.match(/^\/knowledge\/([a-z0-9-]+)\/$/)?.[1];
    if (target && catalog[target] && !(event.metaKey || event.ctrlKey || event.shiftKey)) {
      event.preventDefault();
      openNode(target + url.hash);
      return;
    }
    a.target = '_blank';
    a.rel = 'noopener';
  }
  // Worked examples stay out of every sheet: one of them may be this very problem.
  function nodeDetail(detail, entry) {
    const parsed = new DOMParser().parseFromString(detail.html, 'text/html');
    parsed.querySelectorAll('#examples,.resource-section,.entry-users,.anchor').forEach((el) => el.remove());
    const basis = parsed.querySelector('#basis .chips');
    if (basis) basis.outerHTML = basisList(basis);
    return (entry ? parsed.getElementById(entry)?.outerHTML : null) || parsed.body.innerHTML;
  }
  // "节点 · 条目" links regrouped by node: one row per node, its entries as tags.
  function basisList(chips) {
    const groups = new Map();
    for (const a of chips.querySelectorAll('a[href]')) {
      const url = new URL(a.getAttribute('href'), location.href);
      const id = url.pathname.match(/^\/knowledge\/([a-z0-9-]+)\/$/)?.[1];
      if (!catalog[id]) return chips.outerHTML;
      if (!groups.has(id)) groups.set(id, []);
      if (url.hash) groups.get(id).push(url.hash.slice(1));
    }
    return `<ul class="kxp-basis">${[...groups].map(([id, entries]) => {
      const n = catalog[id];
      const tags = entries.map((e) => `<a href="${nodeHref(`${id}#${e}`)}">${h(n.entries?.[e] || e)}</a>`).join('');
      return `<li data-kind="${n.kind}"><a class="kxp-basis-node" href="${nodeHref(id)}"><i aria-hidden="true"></i>${h(n.label)}</a>${tags ? `<span class="kxp-basis-entries">${tags}</span>` : ''}</li>`;
    }).join('')}</ul>`;
  }
  // Problem-level types and methods open in place; worked examples stay out so
  // a sheet opened mid-exercise cannot hand over a solution.
  async function openNode(ref, fromHistory = false) {
    const { id, entry } = splitRef(ref),
      n = catalog[id];
    if (!n) return;
    if (!fromHistory || history.at(-1) !== ref) history.push(ref);
    const body = sheet(label(ref), n.kind);
    const stamp = ticket;
    footLink(ref);
    body.innerHTML = `<p class="kxp-lead" data-math-text>${h(n.summary)}</p><div class="kxp-detail"><p class="kxp-load-status" role="status">正在加载…</p></div>`;
    math(body);
    body.scrollTop = 0;
    try {
      const detail = await read(`/knowledge/teaching/nodes/${id}.json`);
      if (stamp !== ticket) return;
      body.querySelector('.kxp-detail').innerHTML = nodeDetail(detail, entry);
    } catch {
      if (stamp !== ticket) return;
      body.querySelector('.kxp-detail').innerHTML =
        '<p class="kxp-load-status" role="status">详细内容加载失败。<button type="button" class="kxp-retry">重试</button></p>';
      body.querySelector('.kxp-retry').onclick = () => openNode(ref, true);
      return;
    }
    math(body);
  }
  async function openStep(rid, stage, snapshot) {
    const step = problem.routes[rid]?.steps[lesson.routes[rid]?.[stage]?.id];
    if (!step?.tip) return;
    history = [{ reopen: () => openStep(rid, stage, snapshot) }];
    sheet('学习提示');
    const selection = select(step.tip, confirmed(snapshot.state), optionValues, passedFields(snapshot.state)),
      passed = stage < snapshot.state.active;
    const items = [...selection.actual, ...selection.candidates];
    const body = dialog.querySelector('.kxp-sheet-body');
    if (!items.length) {
      // Recorded sessions wait for the server to confirm a passed choice.
      body.textContent = !selection.withheld
        ? '当前选择未匹配有效关联。可以继续修改答案。'
        : passed && useServerProgress()
          ? '这一步的作答还没保存到账号，保存成功后显示对应提示。'
          : '这一步的提示和你的选择有关，作答后显示对应提示。';
      return;
    }
    if (selection.candidates.length) {
      body.innerHTML =
        `<p>${passed ? '本步已通过，但没有记录具体选择。' : '尚未选择完整分支。'}下面是候选提示，不代表已采用的方法。</p><div class="kxp-tip-options"></div><div class="kxp-tip-content"></div>`;
      items.forEach((b) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = label(b.value.ref) + '（' + conditionLabel(b.conditions) + '）';
        button.setAttribute('data-math-text', '');
        button.onclick = () => show(b.value, passed, body.querySelector('.kxp-tip-content'), false, {snapshot, stage});
        body.querySelector('.kxp-tip-options').append(button);
      });
      math(body);
    } else await show(items[0].value, passed, body, false, {snapshot, stage});
  }
  async function show(tip, passed, body, retry = false, evidence = null) {
    close();
    const stamp = ticket;
    const { id, entry } = splitRef(tip.ref),
      n = catalog[id];
    heading(label(tip.ref), n.kind, '学习提示');
    footLink(tip.ref);
    body.innerHTML = `<p class="kxp-lead" data-math-text>${h(n.summary)}</p>${n.conditions ? `<p class="condition" data-math-text><strong>注意：</strong>${h(n.conditions)}</p>` : ''}<div class="kxp-detail"></div><div class="kxp-resource"></div><p class="kxp-load-status" role="status">正在加载提示…</p><button class="kxp-retry" type="button" hidden>重试加载提示</button>`;
    const retryButton = body.querySelector('.kxp-retry');
    retryButton.onclick = () => show(tip, passed, body, true, evidence);
    math(body);
    const failures = [];
    // Text and diagrams load independently: a failed resource must not hide the text.
    await Promise.all([
      (async () => {
        if (passed) {
          const detail = await read(`/knowledge/teaching/nodes/${id}.json`);
          if (stamp !== ticket) return;
          body.querySelector('.kxp-detail').innerHTML = nodeDetail(detail, entry);
        } else {
          body.querySelector('.kxp-detail').innerHTML =
            '<p class="kxp-locked">答完这一步后，这里会展开完整说明。</p>';
        }
      })().catch(() => failures.push('正文')),
      (async () => {
        if (!tip.resource) return;
        const resource = await readResource(tip.resource);
        await stylesheet('/assets/explain/explain.css?v=1');
        if (stamp !== ticket) return;
        const root = body.querySelector('.kxp-resource');
        root.className = `kxp-resource explain-inline explain-${resource.scope}`;
        root.innerHTML = `${resource.conditions ? `<p class="condition" data-math-text>${h(resource.conditions)}</p>` : ''}${resource.html}`;
        const unmount = await mountResource(root, resource, { node: n, tip: passed ? tip : null, retry });
        if (stamp !== ticket) {
          unmount?.();
          return;
        }
        cleanup = unmount;
      })().catch(() => {
        failures.push('图解');
      })
    ]);
    if (stamp !== ticket) return;
    body.querySelector('.kxp-load-status').textContent = failures.length
      ? `${failures.join('、')}加载失败，可重试或打开详情；练习仍可继续。`
      : '';
    retryButton.hidden = !failures.length;
    math(body);
    if (!failures.length && evidence && dialog?.open) onShown?.(evidence.snapshot, evidence.stage, tip);
  }
  return { update, openStep, openNode, contentVersion: problem.content_version };
}
