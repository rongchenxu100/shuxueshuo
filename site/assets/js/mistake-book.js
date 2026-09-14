(() => {
  'use strict';

  const root = document.getElementById('this-week');
  const nav = document.getElementById('mistake-browse-nav');
  const topics = document.getElementById('mistake-topic-view');
  const errors = document.getElementById('mistake-error-view');
  const quickLinks = document.getElementById('mistake-quick-links');
  const tabs = [...nav.querySelectorAll('[role="tab"]')];
  const categories = [
    {
      key: 'degree', title: '检查二次项系数是否为0',
      cards: ['question-9', 'training-two-q8'],
    },
    {
      key: 'elements', title: '描述法表示集合先看集合元素是什么',
      cards: ['question-12', 'training-two-q7'],
    },
    {
      key: 'cases', title: '分类列举不遗漏',
      cards: ['training-three-q12', 'training-three-q13'],
    },
    {
      key: 'boundary', title: '边界值一定要代入原集合验证关系',
      cards: ['training-three-q14', 'training-four-q13', 'training-five-q15'],
    },
    {
      key: 'venn', title: '集合关系要画维恩图',
      cards: ['training-four-q7', 'training-four-q12'],
    },
    {
      key: 'universal', title: '“任意”指所有对象都要满足条件',
      cards: ['question-15'],
    },
    {
      key: 'empty', title: '讨论集合包含关系不能忘记空集',
      cards: ['training-two-q5'],
    },
    {
      key: 'duplicates', title: '集合计数或求和，重复元素只算一次',
      cards: ['training-three-q16'],
    },
    {
      key: 'conditions', title: '充分、必要条件要转成集合包含关系',
      cards: ['training-five-q5', 'training-five-q9', 'training-five-q12'],
    },
    {
      key: 'understanding', title: '先理解条件的含义，再明确题目要求的推导方向',
      cards: ['training-five-q11', 'training-five-q13', 'training-five-q14'],
    },
  ];

  const topicLabels = {
    'training-one': '集合概念',
    'training-two': '集合间的关系',
    'training-three': '并集与交集',
    'training-four': '全集与补集',
    'training-five': '充分条件与必要条件',
  };
  const topicGroups = [...topics.querySelectorAll('.mistake-book-subsection')].map(section => ({
    id: section.id,
    title: section.querySelector('.mistake-book-subsection-head span').textContent.trim(),
    label: topicLabels[section.id] || section.querySelector('h3').textContent.trim(),
    count: section.querySelectorAll('.mistake-card').length,
    node: section,
  }));
  const records = new Map();
  let mode = '';
  let scrollFrame = 0;
  let userInteracted = false;
  history.scrollRestoration = 'manual';

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  // Keep one live article per question. Placeholders restore the original order.
  for (const category of categories) {
    const group = element('section', 'mistake-error-group');
    group.id = `error-${category.key}`;
    group.setAttribute('aria-labelledby', `${group.id}-title`);
    const header = element('header', 'mistake-error-group-head');
    const title = element('h3', '', category.title);
    title.id = `${group.id}-title`;
    header.append(title, element('span', 'mistake-group-count', `${category.cards.length}题`));
    const summary = element('div', 'mistake-shared-summary');
    const list = element('div', 'mistake-error-questions');
    group.append(header, summary, list);
    errors.append(group);
    Object.assign(category, { node: group, id: group.id, summary, list });

    for (const id of category.cards) {
      const card = document.getElementById(id);
      const topic = topicGroups.find(item => item.node.contains(card));
      const placeholder = document.createComment(`question home: ${id}`);
      card.before(placeholder);
      card.dataset.training = topic.id.replace('training-', '');
      card.dataset.errorType = category.key;
      const number = id.match(/(?:q|-)(\d+)$/)[1];
      const context = element('div', 'mistake-card-context');
      context.append(element('span', 'mistake-card-source', `${topic.title} · 第${number}题`));
      const tag = element('a', 'mistake-error-tag', category.title);
      tag.href = `#${group.id}`;
      tag.setAttribute('aria-label', `查看同类错题：${category.title}`);
      context.append(tag);
      card.prepend(context);
      const detail = card.querySelector('.mistake-reveal-diff');
      records.set(id, { card, placeholder, detail });
    }

    // Reuse the actual authored summaries; deduplicate equivalent summaries only.
    const seen = new Set();
    category.rules = [];
    for (const id of category.cards) {
      const card = records.get(id).card;
      const rule = card.querySelector('.mistake-general-rule');
      const text = rule.textContent.replace(/\s+/g, '');
      if (seen.has(text)) continue;
      seen.add(text);
      const ruleHome = document.createComment(`summary home: ${id}`);
      rule.before(ruleHome);
      const container = element('div', 'mistake-shared-rule');
      category.rules.push({ rule, ruleHome, container, source: card.querySelector('.mistake-card-source').textContent });
      summary.append(container);
    }
    if (category.rules.length > 1) {
      for (const item of category.rules) {
        item.container.append(element('p', 'mistake-shared-label', `${item.source}的错误总结`));
      }
    }
  }

  const count = records.size;
  root.querySelector('.mistake-question-count').textContent = `${count}道错题`;
  document.querySelector('.mistake-book-archive em').textContent = `${count} 道 · 待复测`;

  function visibleGroups() {
    return mode === 'topic' ? topicGroups : categories;
  }

  function highlightGroup() {
    scrollFrame = 0;
    const groups = visibleGroups();
    const cutoff = nav.getBoundingClientRect().bottom + 45;
    let current = groups[0];
    for (const group of groups) {
      if (group.node.getBoundingClientRect().top <= cutoff) current = group;
    }
    for (const link of quickLinks.children) {
      if (link.hash === `#${current.id}`) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    }
  }

  function renderMode(nextMode) {
    if (nextMode === mode) return;
    if (nextMode === 'error') {
      for (const category of categories) {
        for (const item of category.rules) item.container.append(item.rule);
        for (const id of category.cards) {
          const record = records.get(id);
          category.list.append(record.card);
          record.detail.hidden = true;
        }
      }
    } else {
      for (const category of categories) {
        for (const item of category.rules) item.ruleHome.after(item.rule);
      }
      for (const record of records.values()) {
        record.placeholder.after(record.card);
        record.detail.hidden = false;
      }
    }
    mode = nextMode;
    root.dataset.browseMode = mode;
    topics.hidden = mode !== 'topic';
    errors.hidden = mode !== 'error';
    tabs.forEach((tab, index) => {
      const selected = (index === 0) === (mode === 'topic');
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
    quickLinks.replaceChildren(...visibleGroups().map(group => {
      const link = element('a', '', mode === 'topic' ? group.label : group.title);
      link.href = `#${group.id}`;
      link.append(element('span', '', String(mode === 'topic' ? group.count : group.cards.length)));
      return link;
    }));
    highlightGroup();
  }

  function applyRoute(scroll = true) {
    const hash = location.hash.slice(1);
    const category = categories.find(item => item.id === hash);
    const topic = topicGroups.find(item => item.id === hash);
    if (category || hash === 'by-error') renderMode('error');
    else if (topic || hash === 'by-topic') renderMode('topic');
    else if (!mode) renderMode('topic');
    const target = hash === 'by-error' || hash === 'by-topic'
      ? visibleGroups()[0].node
      : document.getElementById(hash);
    if (scroll && target && !target.closest('[hidden]')) {
      requestAnimationFrame(() => {
        target.scrollIntoView({ block: 'start', behavior: 'instant' });
        highlightGroup();
      });
    }
  }

  function switchView(nextMode) {
    const hash = nextMode === 'topic' ? '#by-topic' : '#by-error';
    if (location.hash !== hash) history.pushState(null, '', hash);
    applyRoute();
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => switchView(index === 0 ? 'topic' : 'error'));
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? 1 : 1 - index;
      tabs[next].focus();
      switchView(next === 0 ? 'topic' : 'error');
    });
  });
  // Delegation keeps examples working when authored summaries move between views.
  root.addEventListener('click', event => {
    const choice = event.target.closest('[data-reading-choice]');
    if (!choice) return;
    const demo = choice.closest('.mistake-reading-demo');
    const selected = choice.dataset.readingChoice;
    const previousTop = demo.getBoundingClientRect().top;
    demo.querySelectorAll('[data-reading-choice]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.readingChoice === selected));
    });
    demo.querySelectorAll('[data-reading-panel]').forEach(panel => {
      panel.hidden = panel.dataset.readingPanel !== selected;
    });
    window.scrollBy({ top: demo.getBoundingClientRect().top - previousTop, behavior: 'instant' });
  });
  window.addEventListener('hashchange', () => applyRoute());
  // pushState navigation is also restored with browser back/forward.
  window.addEventListener('popstate', () => applyRoute());
  window.addEventListener('scroll', () => {
    if (!scrollFrame) scrollFrame = requestAnimationFrame(highlightGroup);
  }, { passive: true });
  function measureNavigation() {
    root.style.setProperty('--mistake-nav-offset', `${nav.offsetHeight + 26}px`);
  }
  new ResizeObserver(measureNavigation).observe(nav);
  for (const event of ['pointerdown', 'keydown', 'wheel', 'touchstart']) {
    window.addEventListener(event, () => { userInteracted = true; }, { once: true, passive: true });
  }
  function settleInitialAnchor() {
    if (!userInteracted && location.hash) {
      measureNavigation();
      applyRoute();
    }
  }
  nav.hidden = false;
  measureNavigation();
  applyRoute(Boolean(location.hash));
  window.addEventListener('load', settleInitialAnchor, { once: true });
  document.fonts.ready.then(settleInitialAnchor);
})();
