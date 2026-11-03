import {ABILITY_KINDS, STATUS_LABELS, learningApi, learningDirectoryHref, progressScope, practiceEventView, renderLearningMath} from './learning-model.mjs';
import {isPreview, bindModeLinks, modeHref} from '../practice/learning-mode.mjs';
import {personalState} from './personal-state.mjs';
import {bindPersonalOverlay, updateLocalDrillProgress} from './personal-overlay.mjs';
import {escapeHtml as h} from './resource-links.mjs';

const preview = isPreview(location.search);
const when = iso => new Date(iso).toLocaleString('zh-CN', {month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit'});
const nodeConfig = document.querySelector('#node-page-config');
const config = nodeConfig ? JSON.parse(nodeConfig.textContent) : null;
bindModeLinks(document, location.href);
if (config?.redirectHref) {
  location.replace(learningDirectoryHref(config, location.href));
} else {
  const hero = document.querySelector('main .hero');
  const actions = hero?.querySelector('.detail-actions') || hero;
  // A node's own status is one line in the action row; its records follow the article.
  const nodePage = !!config && (ABILITY_KINDS.includes(config.kind) || config.kind === 'judgment_rule');
  const mine = document.createElement('div');
  mine.className = 'kx-mine';
  mine.setAttribute('aria-live', 'polite');
  mine.hidden = true;
  const records = document.createElement('section');
  records.className = 'kx-records';
  records.setAttribute('aria-label', config?.kind === 'judgment_rule' ? '我的判断记录' : '我的练习记录');
  records.hidden = true;
  if (nodePage) {
    actions?.append(mine);
    const article = document.querySelector('.detail-body');
    const source = article?.querySelector(':scope > .source');
    if (source) source.before(records);
    else if (article) article.append(records);
    else hero?.after(records);
  }
  const controls = document.querySelector('[data-personal-controls]') || document.createElement('div');
  controls.classList.add('kx-learning-entry');
  const panel = document.createElement('section');
  panel.className = 'kx-learning-panel';
  panel.setAttribute('aria-label', '个人学习记录');
  panel.setAttribute('aria-live', 'polite');
  panel.hidden = true;
  // Chapter graphs keep the switch and the scope summary on one bar; the overview follows the saved preference without a switch.
  if (document.querySelector('#graph-config')) {
    const bar = document.createElement('div');
    bar.className = 'kx-learning-bar';
    bar.append(controls, panel);
    hero?.after(bar);
  } else {
    if (!controls.isConnected && (preview || !document.querySelector('main.kx-overview'))) actions?.append(controls);
    hero?.after(panel);
  }
  if (preview) {
    controls.innerHTML = `<span>无记录预览</span> · <a data-learning-exit href="${h(modeHref(location.href))}">返回正式图谱</a>`;
  } else {
    const store = personalState();
    bindPersonalOverlay(store);
    const graphConfig = document.querySelector('#graph-config');
    const graph = graphConfig ? JSON.parse(graphConfig.textContent) : null;
    const scope = () => config && ['textbook', 'chapter', 'section', 'collection'].includes(config.kind) ? config.id : progressScope(location.search, graph);
    // Only an entry anchor narrows the records; other in-page anchors change nothing.
    const entryAnchor = () => {
      const anchor = location.hash.slice(1);
      return config?.entryIds?.includes(anchor) ? anchor : '';
    };
    let ticket = 0, rendered = '', evidenceController, localDrillProgress = null;
    const drawDrillProgress = () => updateLocalDrillProgress(mine.querySelector('[data-drill-progress]'),
      localDrillProgress, store.snapshot().userId, config?.id);
    // Formula rendering is an enhancement; a failed script must not hide evidence.
    const renderMath = async target => {
      try { await renderLearningMath(target); }
      catch {
        const retry = document.createElement('button');
        retry.type = 'button';
        retry.textContent = '公式排版暂不可用，重试';
        retry.onclick = () => { retry.remove(); renderMath(target); };
        target.append(retry);
      }
    };
    const KIND_NAMES = {knowledge: '知识点', skill: '技能', method: '方法', problem_type: '题型'};
    const count = (row, status) => row?.statuses?.[status] || 0;
    const cell = row => row?.total
      ? `<b>${count(row, 'mastered')}</b> / ${row.total}${count(row, 'needs_review') ? ` <span class="needs_review">${count(row, 'needs_review')} 待巩固</span>` : ''}`
      : '<span class="kx-none">—</span>';
    const progressTable = groups => {
      const kinds = Object.keys(KIND_NAMES).filter(kind => groups.some(([, value]) => value.by_kind?.[kind]?.total));
      const row = (label, cells, cls = '') => `<tr${cls ? ` class="${cls}"` : ''}><th scope="row">${label}</th>${cells.join('')}</tr>`;
      return `<table class="kx-progress-table"><thead><tr><th></th>${groups.map(([name, value]) => `<th scope="col">${name} <span>${value.total} 个</span></th>`).join('')}</tr></thead><tbody>${
        kinds.map(kind => row(KIND_NAMES[kind], groups.map(([, value]) => `<td>${cell(value.by_kind?.[kind])}</td>`))).join('')
      }${row('合计', groups.map(([, value]) => `<td>${cell(value)}</td>`), 'kx-progress-total')
      }${row('有检测题', groups.map(([, value]) => `<td>${value.eligible} 个</td>`), 'kx-progress-eligible')}</tbody></table>`;
    };
    const meter = (name, value) => {
      const m = count(value, 'mastered'), r = count(value, 'needs_review'), pct = n => `${(n / value.total * 100).toFixed(1)}%`;
      return `<span class="kx-meter"><span class="kx-meter-name">${name}</span><span class="kx-meter-bar" role="img" aria-label="${name}已掌握 ${m} 个，待巩固 ${r} 个，共 ${value.total} 个"><i class="mastered" style="width:${pct(m)}"></i><i class="needs_review" style="width:${pct(r)}"></i></span><span class="kx-meter-num"><b>${m}</b> / ${value.total}</span></span>`;
    };
    let progressOpen = false;
    function drawControls(current) {
      if (!current.userId) {
        controls.innerHTML = '<button type="button" class="kx-login" data-login>登录后记录掌握情况</button>';
        controls.querySelector('[data-login]').onclick = () => window.SiteAuth?.requireLogin({title:'登录后记录学习情况', intro:'检测结果和练习记录会保存在你的账号里。'});
        return;
      }
      const legend = current.enabled && current.phase === 'ready' && !nodePage
        ? `<span class="kx-personal-legend"><span class="mastered"><i aria-hidden="true">✓</i>${STATUS_LABELS.mastered}</span><span class="needs_review"><i aria-hidden="true">!</i>${STATUS_LABELS.needs_review}</span></span>` : '';
      controls.innerHTML = `<label><input type="checkbox" data-toggle-personal ${current.enabled ? 'checked' : ''}> ${nodePage ? '显示我的记录' : '标出我的掌握情况'}</label>${legend}${current.phase === 'loading' ? '<span>读取中…</span>' : current.phase === 'error' ? `<span role="status">${h(current.error.message)}</span><button type="button" data-retry>重试</button>` : ''}`;
      controls.querySelector('[data-toggle-personal]').onchange = event => store.setEnabled(event.target.checked);
      controls.querySelector('[data-retry]')?.addEventListener('click', () => store.refresh());
    }
    async function refresh(current = store.snapshot()) {
      const key = `${current.revision}|${scope() || ''}|${entryAnchor()}`;
      if (key === rendered) return;
      rendered = key;
      const stamp = ++ticket;
      evidenceController?.abort();
      evidenceController = new AbortController();
      const signal = evidenceController.signal;
      panel.replaceChildren(); panel.hidden = true;
      mine.replaceChildren(); mine.hidden = true;
      records.replaceChildren(); records.hidden = true;
      drawControls(current);
      if (current.phase !== 'ready') return;
      const user = {id:current.userId};
      // Overviews and 3D have compact per-directory summaries instead of a duplicate panel.
      if (!config && !scope()) return;
      if (!nodePage) panel.hidden = false;
      try {
        if (config && ABILITY_KINDS.includes(config.kind)) {
          const state = current.nodes.get(config.id);
          if (!state) throw Error('这里暂时不能记录学习情况。');
          const result = state.attempt_id
            ? `上次检测${state.correct_count === 5 ? ' 5/5 全对' : `答对 ${state.correct_count}/5`} · ${h(when(state.completed_at))}`
            : state.eligible ? '' : '暂时没有检测题';
          const action = !state.eligible ? '' : state.in_progress ? '继续检测' : state.attempt_id ? '再测一次' : '做 5 道题检测';
          mine.innerHTML = `<span class="kx-status ${h(state.status)}" title="做完 5 道检测题后更新：全对为已掌握，有错为待巩固">${STATUS_LABELS[state.status]}</span>${result ? `<span class="kx-mine-text">${result}</span>` : ''}<span class="kx-mine-text" data-drill-progress>${state.in_progress ? ' · 有一轮没做完' : ''}</span>${action ? `<button type="button" data-start-drill>${action}</button>` : ''}`;
          mine.hidden = false;
          drawDrillProgress();
          const start = mine.querySelector('[data-start-drill]');
          if (start) start.onclick = async () => {
            start.disabled = true;
            try {
              const {openDrill} = await import('./learning-drill.mjs');
              await openDrill({node:config.id, label:config.label, drillVersion:state.drill_version});
            } catch (error) { start.after(document.createTextNode(error.message)); }
            finally { start.disabled = false; }
          };
          await loadEvidence(config.id, user.id, stamp, signal);
        } else if (config?.kind === 'judgment_rule') {
          await loadEvidence(config.id, user.id, stamp, signal);
        } else if (scope()) {
          const [result] = await store.getProgress([scope()]);
          if (stamp !== ticket) return;
          if (!result) throw Error('目录进度暂不可用，请重试。');
          const groups = [['课内', result.contains], ['拓展', result.extends]].filter(([, value]) => value?.total);
          const note = '<p class="kx-progress-note">只有做完 5 道检测题才算掌握；做例题不改变掌握情况。</p>';
          const body = groups.length ? `${progressTable(groups)}${note}` : '<p>这里还没有可以检测的内容。</p>';
          panel.classList.toggle('kx-learning-compact', !!graph);
          if (graph) {
            panel.innerHTML = `<div class="kx-progress-head"><span class="kx-progress-label">我已掌握</span>${groups.map(([name, value]) => meter(name, value)).join('') || '<span class="kx-none">暂无内容</span>'}${groups.length ? `<button type="button" class="kx-progress-toggle" aria-expanded="${progressOpen}">明细</button>` : ''}</div><div class="kx-progress-body"${progressOpen ? '' : ' hidden'}>${body}</div>`;
            panel.querySelector('.kx-progress-toggle')?.addEventListener('click', event => {
              progressOpen = !progressOpen;
              event.currentTarget.setAttribute('aria-expanded', String(progressOpen));
              panel.querySelector('.kx-progress-body').hidden = !progressOpen;
            });
          } else panel.innerHTML = `<h2>我的进度</h2>${body}`;
        } else panel.innerHTML = '<p>进入具体章节查看我的进度，或打开某个知识点做检测。</p>';
      } catch (error) {
        if (stamp !== ticket) return;
        if (nodePage) {
          records.hidden = true;
          mine.hidden = false;
          mine.innerHTML = `<span class="kx-mine-text">${h(error.message)}</span><button type="button" data-retry>重试</button>`;
          mine.querySelector('[data-retry]').onclick = () => store.refresh();
          return;
        }
        panel.innerHTML = `<p>${h(error.message)} 公共正文仍可阅读。</p><button type="button" data-retry>重试读取</button>`;
        panel.querySelector('[data-retry]').onclick = () => store.refresh();
      }
    }
    // Records fail on their own; the status line and drill button stay usable.
    async function loadEvidence(id, user, stamp, signal) {
      try { await evidence(records, id, user, stamp, signal); }
      catch (error) {
        if (stamp !== ticket || signal.aborted) return;
        records.innerHTML = `<p class="kx-records-error">练习记录暂时读不出来：${h(error.message)} <button type="button" data-retry-records>重试</button></p>`;
        records.hidden = false;
        records.querySelector('[data-retry-records]').onclick = () => {
          records.replaceChildren(); records.hidden = true;
          loadEvidence(id, user, stamp, signal);
        };
      }
    }
    async function evidence(host, id, user, stamp, signal) {
      const entry = entryAnchor();
      const query = entry ? `?entry=${encodeURIComponent(entry)}` : '';
      const result = await learningApi(`/nodes/${encodeURIComponent(id)}/evidence${query}`, {user, signal});
      if (stamp !== ticket) return;
      const rows = result.evidence;
      const rounds = new Map();
      for (const row of result.drills || []) (rounds.get(row.attempt_id) || rounds.set(row.attempt_id, []).get(row.attempt_id)).push(row);
      if (!rounds.size && !rows.length) return;
      const roundState = {in_progress:'进行中', closed:'中途结束'};
      const drillItems = [...rounds].map(([attempt, items]) => {
        const first = items.reduce((a, b) => a.answered_at <= b.answered_at ? a : b);
        const meta = [`答对 ${items.filter(row => row.is_correct).length}/${items.length}`, roundState[first.status]].filter(Boolean).join(' · ');
        return `<li><div class="kx-rec-head"><span class="kx-rec-main">${h(when(first.answered_at))} 的检测</span><span class="kx-rec-meta">${meta}</span><button type="button" data-drill-record="${h(attempt)}" data-positions="${items.map(row => row.position).join(',')}">看题</button></div><div class="kx-record"></div></li>`;
      }).join('');
      // One problem attempt per group; its steps keep the server's recency order.
      const attempts = new Map();
      for (const row of rows) (attempts.get(row.attempt_id) || attempts.set(row.attempt_id, []).get(row.attempt_id)).push(row);
      const attemptState = {in_progress:'做到一半', completed:'整题完成', closed:'中途结束'};
      const practiceItems = [...attempts.values()].map(steps => {
        const first = steps[0], name = h(first.label || first.problem_id || '练习');
        const title = first.path ? `<a href="${h(modeHref(first.path, {preview:false}, location.href))}">${name}</a>` : name;
        return `<li class="kx-rec-problem"><div class="kx-rec-head"><span class="kx-rec-main">${title}</span><span class="kx-rec-meta">${attemptState[first.status] || ''}</span></div><ul>${steps.map(row => {
          const meta = [row.passed ? '做对了' : '还没做完', row.wrong_count ? `答错 ${row.wrong_count} 次` : '', row.hint_used ? '看过提示' : ''].filter(Boolean).join(' · ');
          return `<li><div class="kx-rec-head"><span class="kx-rec-step">${h(row.title || row.step_id || '')}</span><span class="kx-rec-meta">${meta}</span><button type="button" data-record="${h(row.attempt_id)}" data-step="${h(row.step_id || '')}">回看</button></div><div class="kx-record"></div></li>`;
        }).join('')}</ul></li>`;
      }).join('');
      const counts = [rounds.size ? `检测 ${rounds.size} 次` : '', attempts.size ? `例题 ${attempts.size} 道` : '', entry ? '只看当前条目' : ''].filter(Boolean).join(' · ');
      host.innerHTML = `<details><summary><span class="kx-records-title">${config.kind === 'judgment_rule' ? '我的判断记录' : '我的练习记录'}</span><span class="kx-rec-meta">${counts}</span></summary>${drillItems ? `<h3>检测题</h3><ul>${drillItems}</ul>` : ''}${practiceItems ? `<h3>做过的例题里用到它的步骤</h3><ul>${practiceItems}</ul>` : ''}</details>`;
      host.hidden = false;
      host.onclick = async event => {
        const button = event.target.closest('[data-record], [data-drill-record]');
        if (!button) return;
        const target = button.closest('li').querySelector('.kx-record');
        const label = button.dataset.drillRecord ? '看题' : '回看';
        if (target.innerHTML) { target.replaceChildren(); button.textContent = label; return; }
        button.disabled = true;
        try {
          if (button.dataset.drillRecord) {
            const run = await learningApi(`/drills/${button.dataset.drillRecord}`, {user, signal});
            if (stamp !== ticket) return;
            const keep = new Set(button.dataset.positions.split(',').map(Number));
            target.innerHTML = `<ol>${run.items.filter(item => keep.has(item.position)).map(item => {
              const picked = item.options.filter(option => item.selected?.includes(option.value)).map(option => option.label).join('；');
              return `<li class="${item.is_correct ? 'is-right' : 'is-wrong'}"><p data-math-text>${h(item.statement_md)}</p><p class="kx-rec-meta" data-math-text>${item.is_correct ? '答对' : '答错'}${picked ? ` · 你选了：${h(picked)}` : ''}</p></li>`;
            }).join('')}</ol>`;
          } else {
            const history = await learningApi(`/practice/${button.dataset.record}`, {user, signal});
            if (stamp !== ticket) return;
            const contexts = new Map(history.events.filter(e => e.event_type === 'context').map(e => [e.id, e.payload]));
            target.innerHTML = history.events.filter(e => e.step_id === button.dataset.step).map(e => {
              const view = practiceEventView(e, contexts);
              return `<div class="kx-event"><p><strong>${h(view.title)}</strong>${e.created_at ? ` <span class="kx-rec-meta">${h(when(e.created_at))}</span>` : ''}</p>${view.text ? `<p data-math-text>${h(view.text)}</p>` : ''}${view.details.map(detail => `<p class="kx-rec-meta" data-math-text>${h(detail)}</p>`).join('')}</div>`;
            }).join('') || '<p>这一步还没有记录。</p>';
          }
          button.textContent = '收起';
          await renderMath(target);
        } catch (error) { target.textContent = error.message; }
        finally { button.disabled = false; }
      };
    }
    store.subscribe(refresh);
    const syncUser = () => {
      localDrillProgress = null;
      return store.setUser(window.SiteAuth?.user);
    };
    const refreshAssessments = () => {
      localDrillProgress = null;
      return store.refresh();
    };
    window.addEventListener('site-auth-change', syncUser);
    window.addEventListener('learning-drill-progress', event => {
      if (event.detail.userId !== store.snapshot().userId || event.detail.nodeId !== config?.id) return;
      localDrillProgress = event.detail;
      drawDrillProgress();
    });
    window.addEventListener('learning-nodes-change', refreshAssessments);
    for (const type of ['knowledge-scope-change', 'popstate', 'hashchange']) window.addEventListener(type, () => refresh());
    window.addEventListener('storage', event => {
      if (event.key === 'sss-learning-change') refreshAssessments();
      else if (event.key?.startsWith('sss-knowledge-personal:')) store.syncPreference();
    });
    Promise.resolve(window.SiteAuth?.ready).then(syncUser);
  }
}
