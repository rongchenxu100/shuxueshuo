(function initializeSeniorHighLibrary() {
  const model = window.SeniorHighLibraryModel;
  if (!model) {
    return;
  }
  const {
    canonicalRational,
    normalizeExactMathExpression,
    parseFiniteSetValues,
    parseRelationSequence,
    parseVariableDomainExclusions,
  } = model;

  const elements = {
    chapterNav: document.querySelector("#chapter-nav"),
    title: document.querySelector("#catalog-title"),
    count: document.querySelector("#catalog-count"),
    filters: document.querySelector(".senior-library-filters"),
    sectionTabs: document.querySelector("#section-tabs"),
    collectionTabs: document.querySelector("#collection-tabs"),
    difficulty: document.querySelector("#difficulty-filter"),
    source: document.querySelector("#source-filter"),
    sort: document.querySelector("#sort-filter"),
    grid: document.querySelector("#problem-grid"),
    worksheet: document.querySelector("#worksheet-view"),
    learning: document.querySelector("#learning-view"),
    pagination: document.querySelector("#pagination"),
  };

  let catalog = null;
  let state = { ...model.DEFAULT_STATE };
  const expandedChapters = new Set();
  const collapsedChapters = new Set();

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function publicAssetUrl(relativePath) {
    return new URL(`../${String(relativePath).replace(/^\/+/, "")}`, window.location.href).href;
  }

  async function loadCatalog() {
    try {
      const response = await fetch("../data/senior-high-catalog.json?v=24");
      if (!response.ok) {
        throw new Error("高中题库目录加载失败");
      }
      return await response.json();
    } catch (error) {
      return window.__SENIOR_HIGH_CATALOG__ || { chapters: [], problems: [] };
    }
  }

  function getChapter(chapterId) {
    return catalog.chapters.find((chapter) => chapter.id === chapterId);
  }

  function getSection(chapterId, sectionId) {
    return getChapter(chapterId)?.sections.find((section) => section.id === sectionId);
  }

  function getCollection(collectionId) {
    return (catalog.collections || []).find((collection) => collection.id === collectionId);
  }

  function getLearningTopic(topicId) {
    return (catalog.learningTopics || []).find((topic) => topic.id === topicId);
  }

  function getCollectionsForSection(section) {
    return (section?.collectionIds || [])
      .map(getCollection)
      .filter(Boolean);
  }

  function collectionCountForChapter(chapterId) {
    return (catalog.collections || [])
      .filter((collection) => chapterId === "all" || collection.chapterId === chapterId)
      .reduce((total, collection) => total + model.collectionProblemCount(collection), 0);
  }

  function topicProblemCount(topic) {
    return (topic?.modules || []).reduce((total, module) => {
      if (module.type === "knowledge") return total + (module.examples || []).length;
      return total + (module.items || []).filter((item) => item.status === "published").length;
    }, 0);
  }

  function learningCountForChapter(chapterId) {
    return (catalog.learningTopics || [])
      .filter((topic) => chapterId === "all" || topic.chapterId === chapterId)
      .reduce((total, topic) => total + topicProblemCount(topic), 0);
  }

  function countChapter(chapterId) {
    const standaloneCount = model.publishedProblems(catalog).filter((problem) => (
      chapterId === "all" || problem.chapterId === chapterId
    )).length;
    return standaloneCount + collectionCountForChapter(chapterId) + learningCountForChapter(chapterId);
  }

  function countSection(chapterId, sectionId) {
    return model.publishedProblems(catalog).filter((problem) => (
      problem.chapterId === chapterId && (sectionId === "all" || problem.sectionId === sectionId)
    )).length;
  }

  function sectionItemCount(section) {
    if (section.presentation === "worksheet") {
      return getCollectionsForSection(section)
        .reduce((sum, item) => sum + model.collectionProblemCount(item), 0);
    }
    if (section.presentation === "learning") {
      return topicProblemCount(getLearningTopic(section.topicId));
    }
    return countSection(state.chapter, section.id);
  }

  function renderChapters() {
    const chapters = [
      { id: "all", label: "全部题目" },
      ...catalog.chapters,
    ];
    elements.chapterNav.innerHTML = chapters.map((chapter) => {
      const sections = chapter.sections || [];
      const nestedSections = sections.filter((section) => (
        section.presentation === "worksheet" || section.presentation === "learning"
      ));
      const hasChildren = nestedSections.length > 0;
      const active = state.chapter === chapter.id && state.section === "all";
      const parentActive = state.chapter === chapter.id && state.section !== "all";
      const expanded = hasChildren
        && !collapsedChapters.has(chapter.id)
        && (expandedChapters.has(chapter.id) || state.chapter === chapter.id);
      return `
        <div class="senior-library-chapter-group">
          <div class="senior-library-chapter-row">
            ${hasChildren ? `
              <button
                class="senior-library-chapter-toggle"
                type="button"
                data-chapter-toggle="${escapeHtml(chapter.id)}"
                aria-expanded="${expanded}"
                aria-label="${expanded ? "收起" : "展开"}${escapeHtml(chapter.label)}子目录"
              >${expanded ? "⌄" : "›"}</button>
            ` : '<span class="senior-library-chapter-toggle is-empty" aria-hidden="true"></span>'}
            <button
              class="senior-library-chapter${active ? " is-active" : ""}${parentActive ? " is-parent-active" : ""}"
              type="button"
              data-chapter="${escapeHtml(chapter.id)}"
              ${active ? 'aria-current="page"' : ""}
            >
              <span class="senior-library-chapter-name">${escapeHtml(chapter.label)}</span>
              <span class="senior-library-chapter-count">${countChapter(chapter.id)}</span>
            </button>
          </div>
          ${hasChildren && expanded ? `
            <div class="senior-library-subchapters">
              ${nestedSections.map((section) => {
                const selected = state.chapter === chapter.id && state.section === section.id;
                const topic = section.presentation === "learning"
                  ? getLearningTopic(section.topicId)
                  : null;
                return `
                  <div class="senior-library-subchapter-group">
                    <button
                      class="senior-library-subchapter${selected ? " is-active" : ""}"
                      type="button"
                      data-subchapter="${escapeHtml(section.id)}"
                      data-parent-chapter="${escapeHtml(chapter.id)}"
                      ${selected && state.module === "overview" ? 'aria-current="page"' : ""}
                    >
                      <span>${escapeHtml(section.label)}</span>
                      <span>${sectionItemCount(section)}</span>
                    </button>
                    ${selected && topic ? `
                      <div class="senior-library-modules" aria-label="${escapeHtml(section.label)}子目录">
                        ${topic.modules.map((module) => `
                          <button
                            class="senior-library-module${state.module === module.id ? " is-active" : ""}"
                            type="button"
                            data-learning-module="${escapeHtml(module.id)}"
                            data-learning-topic="${escapeHtml(topic.id)}"
                            ${state.module === module.id ? 'aria-current="page"' : ""}
                          >
                            <span>${escapeHtml(module.label)}</span>
                            ${module.status === "pending" ? "<small>待补</small>" : ""}
                          </button>
                        `).join("")}
                      </div>
                    ` : ""}
                  </div>
                `;
              }).join("")}
            </div>
          ` : ""}
        </div>
      `;
    }).join("");
  }

  function renderSections() {
    const chapter = getChapter(state.chapter);
    const cardSections = (chapter?.sections || []).filter(
      (section) => (section.presentation ?? "cards") === "cards",
    );
    if (!chapter || cardSections.length === 0) {
      elements.sectionTabs.hidden = true;
      elements.sectionTabs.innerHTML = "";
      return;
    }

    const sections = cardSections;
    elements.sectionTabs.hidden = false;
    elements.sectionTabs.innerHTML = sections.map((section) => {
      const active = state.section === section.id;
      return `
        <button
          class="senior-library-section${active ? " is-active" : ""}"
          type="button"
          data-section="${escapeHtml(section.id)}"
          ${active ? 'aria-current="page"' : ""}
        >
          ${escapeHtml(section.label)}<span>${countSection(chapter.id, section.id)}</span>
        </button>
      `;
    }).join("");
  }

  function renderSourceOptions() {
    const sources = [...new Set(
      model.publishedProblems(catalog).map((problem) => problem.source?.region).filter(Boolean),
    )].sort((left, right) => left.localeCompare(right, "zh-Hans-CN"));
    elements.source.innerHTML = [
      '<option value="all">全部来源</option>',
      ...sources.map((source) => (
        `<option value="${escapeHtml(source)}">${escapeHtml(source)}卷</option>`
      )),
    ].join("");
    elements.source.value = state.source;
  }

  function relativeTime(updatedAt) {
    const then = new Date(updatedAt);
    const now = new Date();
    const days = Math.max(0, Math.floor((now - then) / 86400000));
    if (days === 0) return "今天更新";
    if (days < 7) return `${days} 天前`;
    if (days < 35) return `${Math.floor(days / 7)} 周前`;
    if (days < 365) return `${Math.floor(days / 30)} 个月前`;
    return `${Math.floor(days / 365)} 年前`;
  }

  function renderDifficulty(level) {
    const dots = Array.from({ length: 5 }, (_, index) => (
      `<i class="${index < level ? "is-filled" : ""}"></i>`
    )).join("");
    return `<span class="senior-library-difficulty" aria-label="难度 ${level} / 5">${dots}</span>`;
  }

  function renderTags(tags) {
    const visible = tags.slice(0, 3);
    const remaining = tags.length - visible.length;
    return [
      ...visible.map((tag) => `<span class="senior-library-tag">${escapeHtml(tag)}</span>`),
      ...(remaining > 0 ? [`<span class="senior-library-tag">+${remaining}</span>`] : []),
    ].join("");
  }

  function renderProblem(problem) {
    const section = getSection(problem.chapterId, problem.sectionId);
    const sourceParts = [
      `${problem.source.year} ${problem.source.examLabel}`,
      `第 ${problem.source.questionNumber} 题`,
      problem.source.score ? `${problem.source.score} 分` : "",
    ].filter(Boolean);
    return `
      <a class="senior-library-card" href="${publicAssetUrl(problem.path)}">
        <div class="senior-library-thumbnail">
          <img src="${publicAssetUrl(problem.thumbnail)}" alt="${escapeHtml(problem.title)}的函数图像缩略图" />
        </div>
        <div class="senior-library-card-body">
          <p class="senior-library-card-type">${escapeHtml(section?.label || "高中数学")}</p>
          <h2>${escapeHtml(problem.title)}</h2>
          <div class="senior-library-tags">${renderTags(problem.tags)}</div>
          <div class="senior-library-card-footer">
            <div>
              <div class="senior-library-source" title="${escapeHtml(sourceParts.join(" · "))}">${escapeHtml(sourceParts.join(" · "))}</div>
              <div class="senior-library-update">${escapeHtml(relativeTime(problem.updatedAt))}</div>
            </div>
            <div class="senior-library-card-meta">
              ${renderDifficulty(problem.difficulty)}
              <span class="senior-library-arrow" aria-hidden="true">→</span>
            </div>
          </div>
        </div>
      </a>
    `;
  }

  function collectionHref(collection) {
    const url = new URL(window.location.href);
    url.search = model.stateToSearch({
      ...model.DEFAULT_STATE,
      chapter: collection.chapterId,
      section: collection.sectionId,
      collection: collection.id,
    });
    return url.href;
  }

  function renderCollectionTabs(collection) {
    const section = getSection(collection.chapterId, collection.sectionId);
    const collections = getCollectionsForSection(section);
    elements.collectionTabs.hidden = collections.length < 2;
    elements.collectionTabs.innerHTML = collections.map((item) => `
      <button
        class="senior-library-collection-tab${item.id === collection.id ? " is-active" : ""}"
        type="button"
        data-worksheet-collection="${escapeHtml(item.id)}"
        aria-pressed="${item.id === collection.id ? "true" : "false"}"
        ${item.id === collection.id ? 'aria-current="page"' : ""}
      >
        <span>${escapeHtml(item.label || item.title)}</span>
        <small>${model.collectionProblemCount(item)} 题</small>
      </button>
    `).join("");
  }

  function renderCollectionEntry(collection) {
    return `
      <a
        class="senior-library-collection-entry"
        href="${escapeHtml(collectionHref(collection))}"
        data-collection="${escapeHtml(collection.id)}"
      >
        <div>
          <p>章节练习</p>
          <h2>${escapeHtml(collection.title)}</h2>
          <span>按教材顺序展开 ${model.collectionProblemCount(collection)} 道原题</span>
        </div>
        <span class="senior-library-collection-action">开始练习&nbsp;→</span>
      </a>
    `;
  }

  function renderLearningTopicEntry(topic) {
    const moduleCount = (topic.modules || []).length;
    return `
      <a
        class="senior-library-collection-entry senior-learning-topic-entry"
        href="${escapeHtml(topicHref(topic, "overview"))}"
        data-learning-topic-entry="${escapeHtml(topic.id)}"
      >
        <div>
          <p>学习专题</p>
          <h2>${escapeHtml(topic.title)}</h2>
          <span>知识导图 · ${moduleCount} 个学习模块 · ${topicProblemCount(topic)} 道已发布例题与练习</span>
        </div>
        <span class="senior-library-collection-action">进入专题&nbsp;→</span>
      </a>
    `;
  }

  function renderWorksheetLine(line, problem, lineIndex) {
    if (line.figures) {
      const figureLayoutClass = line.figures.length === 1
        ? " is-single"
        : " is-multiple";
      const figures = line.figures.map((figure) => {
        const originalFigure = (problem.originalFigures || []).find(
          (candidate) => candidate.id === figure.id,
        );
        if (!originalFigure) return "";
        const figureKindClass = originalFigure.kind === "valueTable"
          ? " is-value-table"
          : "";
        const figureViewHeight = originalFigure.kind === "valueTable" ? 280 : 500;
        return `
          <figure class="senior-worksheet-figure${figureKindClass}">
            ${figure.title ? `<figcaption>${escapeHtml(figure.title)}</figcaption>` : ""}
            <svg
              id="worksheet-figure-${escapeHtml(originalFigure.renderId)}"
              viewBox="0 0 720 ${figureViewHeight}"
              role="img"
              aria-label="${escapeHtml(figure.ariaLabel || line.ariaLabel || "原题图形")}"
              data-worksheet-figure="${escapeHtml(originalFigure.renderId)}"
            ></svg>
            ${figure.caption ? `<p>${escapeHtml(figure.caption)}</p>` : ""}
          </figure>
        `;
      }).join("");
      return `<div class="senior-worksheet-figures${figureLayoutClass}">${figures}</div>`;
    }
    const source = lineIndex === 0 && problem.source
      ? `<span class="senior-worksheet-source">（${escapeHtml(problem.source)}）</span>`
      : "";
    const lineHtml = line.html || escapeHtml(line.text);
    const optionGroup = model.splitWorksheetOptions(lineHtml);
    if (!optionGroup) {
      return `<div class="senior-worksheet-line">${source}${lineHtml}</div>`;
    }

    const stem = optionGroup.stemHtml
      ? `<div class="senior-worksheet-line">${source}${optionGroup.stemHtml}</div>`
      : "";
    const options = optionGroup.options.map((option) => `
      <div class="senior-worksheet-option">
        <span class="senior-worksheet-option-label">${option.label}.</span>
        <span>${option.html}</span>
      </div>
    `).join("");
    return `
      ${stem}
      <div class="senior-worksheet-options${optionGroup.stacked ? " is-stacked" : ""}">
        ${options}
      </div>
    `;
  }

  function renderWorksheetProblem(problem) {
    return `
      <article class="senior-worksheet-problem" id="worksheet-problem-${problem.number}">
        <div class="senior-worksheet-problem-number" aria-hidden="true">${problem.number}.</div>
        <div class="senior-worksheet-problem-body">
          ${problem.problem.lines.map((line, index) => (
            renderWorksheetLine(line, problem, index)
          )).join("")}
          <a
            class="senior-worksheet-solution-link"
            href="${publicAssetUrl(problem.solutionPath)}"
            target="_blank"
            rel="noopener noreferrer"
          >查看解析&nbsp;↗</a>
        </div>
      </article>
    `;
  }

  function renderWorksheet(collection) {
    elements.worksheet.innerHTML = collection.groups.map((group) => `
      <section class="senior-worksheet-group" aria-labelledby="worksheet-group-${escapeHtml(group.id)}">
        <div class="senior-worksheet-group-heading">
          <h2 id="worksheet-group-${escapeHtml(group.id)}">${escapeHtml(group.label)}</h2>
          <span>${group.problems.length} 题</span>
        </div>
        ${group.problems.map(renderWorksheetProblem).join("")}
      </section>
    `).join("");
    renderWorksheetFigures(collection);
  }

  function renderWorksheetFigures(collection) {
    if (!window.FunctionLessonFromSpec) return;
    collection.groups.flatMap((group) => group.problems).forEach((problem) => {
      if (!problem.figureSpec || problem.originalFigures.length === 0) return;
      problem.originalFigures.forEach((figure) => {
        const height = figure.kind === "valueTable" ? 280 : 500;
        const figurePanel = problem.figureSpec.panels.find(
          (panel) => panel.id === figure.renderId,
        );
        if (!figurePanel) return;
        const renderer = window.FunctionLessonFromSpec.createSpecRenderer(
          { ...problem.figureSpec, panels: [figurePanel] },
          { steps: {} },
          [{ id: "worksheet", title: "原题图形" }],
          {},
          { W: 720, H: height },
        );
        const element = document.getElementById(`worksheet-figure-${figure.renderId}`);
        if (element) {
          element.innerHTML = renderer.originalFigureMarkupFor(figure.renderId);
        }
      });
    });
  }

  function topicHref(topic, moduleId) {
    const url = new URL(window.location.href);
    url.search = model.stateToSearch({
      ...model.DEFAULT_STATE,
      chapter: topic.chapterId,
      section: topic.sectionId,
      module: moduleId,
    });
    return url.href;
  }

  function learningMethodHref(topic, moduleId, methodId) {
    const url = new URL(window.location.href);
    url.search = model.stateToSearch({
      ...model.DEFAULT_STATE,
      chapter: topic.chapterId,
      section: topic.sectionId,
      module: moduleId,
      method: methodId,
    });
    return url.href;
  }

  function learningMethodGuideHref(topic, moduleId, methodId) {
    const href = learningMethodHref(topic, moduleId, methodId);
    return methodId === "all" ? href : `${href}#selected-method-heading`;
  }

  function renderLearningLine(line) {
    if (line.figureHtml) {
      return `<div class="senior-learning-problem-figure">${line.figureHtml}</div>`;
    }
    const lineHtml = line.html || escapeHtml(line.text);
    const optionGroup = model.splitWorksheetOptions(lineHtml);
    if (!optionGroup) {
      return `<div class="senior-learning-problem-line">${lineHtml}</div>`;
    }
    return `
      ${optionGroup.stemHtml ? `<div class="senior-learning-problem-line">${optionGroup.stemHtml}</div>` : ""}
      <div class="senior-learning-options${optionGroup.stacked ? " is-stacked" : ""}">
        ${optionGroup.options.map((option) => `
          <div class="senior-learning-option">
            <span>${option.label}.</span>
            <span>${option.html}</span>
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderLearningLessonCard(topic, lesson, meta = {}) {
    return `
      <article class="senior-learning-example-card">
        <div class="senior-learning-example-heading">
          <div>
            <p>${escapeHtml(meta.eyebrow || "例题精讲")}</p>
            <h3>${escapeHtml(lesson.title)}</h3>
          </div>
          ${meta.number ? `<span class="senior-learning-question-number">${meta.number}</span>` : ""}
        </div>
        ${meta.summary ? `<p class="senior-learning-example-summary">${escapeHtml(meta.summary)}</p>` : ""}
        <div class="senior-learning-problem">
          ${(lesson.problem?.lines || []).map(renderLearningLine).join("")}
        </div>
        <a
          class="senior-learning-solution-link"
          href="${publicAssetUrl(lesson.solutionPath)}"
          target="_blank"
          rel="noopener noreferrer"
        >查看分步解析&nbsp;↗</a>
      </article>
    `;
  }

  function renderInteractiveProblem(example) {
    const schema = example.answerSchema;
    let relationSlotIndex = 0;
    return (example.lesson.problem?.lines || []).map((line) => {
      if (schema.type === "relation-sequence") {
        const lineHtml = line.html || escapeHtml(line.text);
        const inlineBlanks = lineHtml.replace(/_{3,}/g, () => {
          relationSlotIndex += 1;
          return `<button
            class="senior-learning-inline-blank${relationSlotIndex === 1 ? " is-active" : ""}"
            type="button"
            data-relation-slot
            data-relation-index="${relationSlotIndex - 1}"
            aria-label="第 ${relationSlotIndex} 空，未填写"
          ><span aria-hidden="true"></span></button>`;
        });
        return `<div class="senior-learning-problem-line">${inlineBlanks}</div>`;
      }
      if (schema.type !== "single-choice") return renderLearningLine(line);
      const optionGroup = learningOptionGroup(example, line.html || escapeHtml(line.text));
      if (!optionGroup) return renderLearningLine(line);
      return optionGroup.stemHtml
        ? `<div class="senior-learning-problem-line">${optionGroup.stemHtml}</div>`
        : "";
    }).join("");
  }

  function learningOptionGroup(example, lineHtml) {
    return example.answerSchema.choiceStyle === "ordinal"
      ? model.splitOrdinalOptions(lineHtml)
      : model.splitWorksheetOptions(lineHtml);
  }

  function learningChoiceOptions(example) {
    return (example.lesson.problem?.lines || []).flatMap((line) => {
      const optionGroup = learningOptionGroup(example, line.html || escapeHtml(line.text));
      return optionGroup?.options || [];
    });
  }

  function mathKeyboardKeys(tokens) {
    const definitions = {
      x: { label: "x", insert: "x" },
      y: { label: "y", insert: "y" },
      a: { label: "a", insert: "a" },
      m: { label: "m", insert: "m" },
      real: { label: "ℝ", insert: "ℝ" },
      in: { label: "∈", insert: "∈" },
      "not-in": { label: "∉", insert: "∉" },
      "not-equals": { label: "≠", insert: "≠" },
      "set-braces": { label: "{ }", insert: "{}", cursorBack: 1 },
      "set-minus": { label: "∖", insert: "∖" },
      comma: { label: "，", insert: "," },
      plus: { label: "+", insert: "+" },
      negative: { label: "−", insert: "-" },
      fraction: { label: "分数", insert: "/" },
      radical: { label: "√", insert: "√" },
      interval: { label: "( )", insert: "()", cursorBack: 1 },
      brackets: { label: "[ ]", insert: "[]", cursorBack: 1 },
      infinity: { label: "∞", insert: "∞" },
      semicolon: { label: "；", insert: ";" },
      pipe: { label: "|", insert: "|" },
      equals: { label: "=", insert: "=" },
      "greater-equal": { label: "≥", insert: "≥" },
      "less-equal": { label: "≤", insert: "≤" },
      union: { label: "∪", insert: "∪" },
      caret: { label: "x²", insert: "^2" },
    };
    return tokens.flatMap((token) => {
      if (token === "digits") {
        return Array.from({ length: 10 }, (_, value) => ({
          label: String(value),
          insert: String(value),
        }));
      }
      return definitions[token] ? [definitions[token]] : [];
    });
  }

  function renderMathKeyboard(tokens = []) {
    const keys = mathKeyboardKeys(tokens);
    return `
      <div class="senior-learning-math-keyboard" role="toolbar" aria-label="数学输入键盘">
        ${keys.map((key) => (
          `<button
            type="button"
            data-math-key
            data-math-insert="${escapeHtml(key.insert)}"
            ${key.cursorBack ? `data-cursor-back="${key.cursorBack}"` : ""}
          >${["ℕ", "ℤ", "ℚ", "ℝ", "ℂ"].includes(key.label)
            ? `<span class="math-blackboard">${escapeHtml(key.label)}</span>`
            : escapeHtml(key.label)}</button>`
        )).join("")}
        <button type="button" data-math-key data-math-action="backspace" aria-label="删除前一个字符">⌫</button>
        <button type="button" data-math-key data-math-action="clear">清空</button>
      </div>
    `;
  }

  function renderAnswerInteraction(example) {
    const schema = example.answerSchema;
    if (schema.type === "single-choice") {
      return `
        <div class="senior-learning-answer" data-answer-root data-answer-type="single-choice" data-expected="${escapeHtml(schema.expected)}">
          <div class="senior-learning-choice-grid" role="group" aria-label="选择答案">
            ${learningChoiceOptions(example).map((option) => `
              <button
                class="senior-learning-choice"
                type="button"
                data-answer-choice="${escapeHtml(option.label)}"
                aria-pressed="false"
              >
                <span>${escapeHtml(option.label)}</span>
                <span>${option.html}</span>
              </button>
            `).join("")}
          </div>
          <div class="senior-learning-answer-actions">
            <button class="senior-learning-submit" type="button" data-answer-submit>提交答案</button>
            <p class="senior-learning-answer-feedback" data-answer-feedback aria-live="polite"></p>
          </div>
        </div>
      `;
    }

    if (schema.type === "relation-sequence") {
      const relationLabels = {
        "∈": "属于",
        "∉": "不属于",
        "=": "相等",
        "≠": "不相等",
        "⊆": "子集",
        "⊄": "不是子集",
        "⊊": "真子集",
        "⊋": "真包含",
        "⊇": "包含",
      };
      const relations = schema.input?.relations || ["∈", "∉"];
      return `
        <div
          class="senior-learning-answer is-inline-relation"
          data-answer-root
          data-answer-type="relation-sequence"
          data-expected="${escapeHtml(schema.expected.join("|"))}"
          data-relation-count="${schema.expected.length}"
        >
          <input type="hidden" data-answer-field value="">
          <div class="senior-learning-relation-toolbar" role="toolbar" aria-label="填写关系符号">
            <span data-relation-status>选择题目中的第 1 空</span>
            <div class="senior-learning-relation-options" role="group" aria-label="关系符号">
              ${relations.map((relation) => `
                <button type="button" data-relation-key="${escapeHtml(relation)}">
                  <span class="senior-learning-relation-glyph" aria-hidden="true">${escapeHtml(relation)}</span>
                  <span>${escapeHtml(relationLabels[relation] || relation)}</span>
                </button>
              `).join("")}
            </div>
          </div>
          <div class="senior-learning-answer-actions">
            <button class="senior-learning-submit" type="button" data-answer-submit>提交答案</button>
            <p class="senior-learning-answer-feedback" data-answer-feedback aria-live="polite"></p>
          </div>
        </div>
      `;
    }

    if (schema.type === "multipart-choice") {
      return `
        <div
          class="senior-learning-answer is-expression is-multipart is-multipart-choice"
          data-answer-root
          data-answer-type="multipart-choice"
          data-expected-json="${escapeHtml(JSON.stringify(schema.expected.map((part) => part.expected)))}"
        >
          <span class="senior-learning-answer-prefix is-multipart-prefix" aria-hidden="true">快速判断：</span>
          <div class="senior-learning-multipart-list">
            ${schema.expected.map((part, index) => `
              <div class="senior-learning-multipart-row" data-answer-part="${index}">
                <div class="senior-learning-multipart-prompt">
                  <span>${escapeHtml(part.label || `（${index + 1}）`)}</span>
                  <span>${part.promptHtml || escapeHtml(part.prompt || "")}</span>
                </div>
                <div class="senior-learning-quick-choice-options" role="group" aria-label="${escapeHtml(part.label || `第 ${index + 1} 小题`)}选择答案">
                  ${schema.choices.map((choice) => `
                    <button
                      type="button"
                      data-part-choice="${escapeHtml(choice)}"
                      aria-pressed="false"
                    >${escapeHtml(choice)}</button>
                  `).join("")}
                </div>
                <p class="senior-learning-part-feedback" data-answer-part-feedback aria-live="polite"></p>
              </div>
            `).join("")}
          </div>
          <div class="senior-learning-answer-actions">
            <button class="senior-learning-submit" type="button" data-answer-submit>提交全部答案</button>
            <p class="senior-learning-answer-feedback" data-answer-feedback aria-live="polite"></p>
          </div>
        </div>
      `;
    }

    if (schema.type === "multipart-exact" && schema.layout === "per-part") {
      return `
        <div
          class="senior-learning-answer is-expression is-multipart"
          data-answer-root
          data-answer-type="multipart-exact"
          data-answer-layout="per-part"
          data-expected-json="${escapeHtml(JSON.stringify(schema.expected.map((part) => part.aliases)))}"
        >
          <span class="senior-learning-answer-prefix is-multipart-prefix" aria-hidden="true">答：</span>
          <div class="senior-learning-multipart-list">
            ${schema.expected.map((part, index) => `
              <div class="senior-learning-multipart-row" data-answer-part="${index}">
                <div class="senior-learning-multipart-prompt">
                  <span>${escapeHtml(part.label || `（${index + 1}）`)}</span>
                  <span>
                    ${part.promptHtml || escapeHtml(part.prompt || "")}
                    ${part.note ? `
                      <span class="senior-learning-symbol-note">
                        <button
                          type="button"
                          class="senior-learning-symbol-note-button"
                          aria-label="查看特殊符号提示"
                          aria-describedby="learning-symbol-note-${escapeHtml(example.lesson.id)}-${index}"
                        >i</button>
                        <span
                          class="senior-learning-symbol-note-popover"
                          id="learning-symbol-note-${escapeHtml(example.lesson.id)}-${index}"
                          role="tooltip"
                        >${escapeHtml(part.note)}</span>
                      </span>
                    ` : ""}
                  </span>
                </div>
                <label class="senior-learning-multipart-field">
                  <span class="sr-only">${escapeHtml(part.label || `第 ${index + 1} 小题`)}的答案</span>
                  <textarea
                    rows="2"
                    inputmode="text"
                    autocomplete="off"
                    data-answer-field
                    data-answer-index="${index}"
                    aria-label="${escapeHtml(part.label || `第 ${index + 1} 小题`)}的答案"
                    placeholder="${escapeHtml(schema.input.placeholder)}"
                  ></textarea>
                </label>
                <p class="senior-learning-part-feedback" data-answer-part-feedback aria-live="polite"></p>
              </div>
            `).join("")}
          </div>
          ${schema.input.mode === "math-expression" ? `
            <div class="senior-learning-multipart-symbols">
              <button
                class="senior-learning-symbol-toggle"
                type="button"
                data-symbol-toggle
                aria-expanded="false"
                aria-label="打开数学符号面板"
                title="数学符号"
              >∑</button>
            </div>
            ${renderMathKeyboard(schema.input.keyboard)}
          ` : ""}
          <div class="senior-learning-answer-actions">
            <button class="senior-learning-submit" type="button" data-answer-submit>提交全部答案</button>
            <p class="senior-learning-answer-feedback" data-answer-feedback aria-live="polite"></p>
          </div>
        </div>
      `;
    }

    if (
      schema.type === "variable-domain"
      || schema.type === "finite-set-values"
      || schema.type === "integer"
      || schema.type === "exact-expression"
      || schema.type === "multipart-exact"
    ) {
      const expected = schema.type === "variable-domain"
        ? schema.expected.excludedValues
        : schema.type === "multipart-exact"
          ? schema.expected.map((part) => part.aliases[0])
        : Array.isArray(schema.expected)
          ? schema.expected
          : [schema.expected];
      const rows = schema.type === "multipart-exact" ? Math.max(2, schema.expected.length) : 2;
      return `
        <div
          class="senior-learning-answer is-expression"
          data-answer-root
          data-answer-type="${escapeHtml(schema.type)}"
          data-expected="${escapeHtml(expected.join("|"))}"
          ${schema.type === "multipart-exact"
            ? `data-expected-json="${escapeHtml(JSON.stringify(schema.expected.map((part) => part.aliases)))}"`
            : ""}
          ${schema.variable ? `data-answer-variable="${escapeHtml(schema.variable)}"` : ""}
        >
          <div class="senior-learning-answer-line">
            <span class="senior-learning-answer-prefix" aria-hidden="true">答：</span>
            <label class="senior-learning-expression-answer">
              <span class="sr-only">${escapeHtml(schema.input.placeholder)}</span>
              <textarea
                rows="${rows}"
                inputmode="${schema.type === "integer" ? "numeric" : "text"}"
                autocomplete="off"
                data-answer-field
                aria-label="${escapeHtml(schema.input.placeholder)}"
              ></textarea>
            </label>
            <button
              class="senior-learning-symbol-toggle"
              type="button"
              data-symbol-toggle
              aria-expanded="false"
              aria-label="打开数学符号面板"
              title="数学符号"
            >∑</button>
          </div>
          ${renderMathKeyboard(schema.input.keyboard)}
          <div class="senior-learning-answer-actions">
            <button class="senior-learning-submit" type="button" data-answer-submit>提交答案</button>
            <p class="senior-learning-answer-feedback" data-answer-feedback aria-live="polite"></p>
          </div>
        </div>
      `;
    }
    return "";
  }

  function renderInteractiveLearningExample(example, index) {
    const hintId = `learning-hint-${escapeHtml(example.lesson.id)}`;
    return `
      <article class="senior-learning-example" id="learning-example-${escapeHtml(example.lesson.id)}">
        <div class="senior-learning-example-title-row">
          <span class="senior-learning-example-index">${escapeHtml(example.numberLabel || `练习 ${index + 1}`)}</span>
          <div class="senior-learning-hint">
            <button
              class="senior-learning-hint-button"
              type="button"
              data-hint-toggle
              aria-expanded="false"
              aria-controls="${hintId}"
              aria-label="查看本题提示"
            >?</button>
            <div class="senior-learning-hint-popover" id="${hintId}" role="tooltip">
              ${example.hints.map((hint, hintIndex) => `
                <p><strong>提示 ${hintIndex + 1}</strong>${escapeHtml(hint)}</p>
              `).join("")}
            </div>
          </div>
        </div>
        <div class="senior-learning-example-problem">
          ${renderInteractiveProblem(example)}
        </div>
        ${renderAnswerInteraction(example)}
        <a
          class="senior-learning-solution-link"
          href="${publicAssetUrl(example.lesson.solutionPath)}"
          target="_blank"
          rel="noopener noreferrer"
        >查看解析&nbsp;↗</a>
      </article>
    `;
  }

  function groupLearningExamples(examples) {
    const groups = new Map();
    examples.forEach((example, index) => {
      const group = example.group || "例题";
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push({ example, index });
    });
    return [...groups.entries()];
  }

  function learningGroupSlug(group) {
    return ({
      "列举法": "enumeration",
      "描述法": "description",
      "区间表示法": "interval",
      "Venn 图法": "venn",
    })[group] || String(group).toLowerCase().replace(/\s+/g, "-");
  }

  function learningExampleCategory(example) {
    return example.knowledgeCategory || learningGroupSlug(example.group);
  }

  function mindMapChildLabel(child) {
    return typeof child === "string" ? child : child.label;
  }

  function mindMapChildLeaves(child) {
    return typeof child === "string" ? [] : (child.children || []);
  }

  function mindMapChildDescription(child) {
    const leaves = mindMapChildLeaves(child);
    return leaves.length > 0
      ? `${mindMapChildLabel(child)}，${leaves.join("、")}`
      : mindMapChildLabel(child);
  }

  function mindMapLabelLines(label, maxLength = 13) {
    const text = String(label || "");
    if (text.length <= maxLength) return [text];

    const preferredBreaks = ["与", "和", "及", "、"];
    const center = text.length / 2;
    const breakIndex = preferredBreaks
      .flatMap((separator) => [...text].map((character, index) => character === separator ? index : -1))
      .filter((index) => index > 0 && index < text.length - 1)
      .sort((left, right) => Math.abs(left - center) - Math.abs(right - center))[0];

    if (Number.isInteger(breakIndex)) {
      return [text.slice(0, breakIndex), text.slice(breakIndex)];
    }
    return [text.slice(0, maxLength), text.slice(maxLength)];
  }

  function renderSetMindMap(topic) {
    const href = (moduleId) => escapeHtml(topicHref(topic, moduleId));
    const colors = ["is-coral", "is-blue", "is-gold", "is-green"];
    const branchGap = topic.mapNodes.length > 1 ? 470 / (topic.mapNodes.length - 1) : 0;
    const mapRootLabel = topic.mapRootLabel || topic.title;
    const rootJoiner = mapRootLabel.includes("和") ? "和" : mapRootLabel.includes("与") ? "与" : "";
    const rootBreak = rootJoiner ? mapRootLabel.lastIndexOf(rootJoiner) : -1;
    const rootLines = rootBreak > 0
      ? [mapRootLabel.slice(0, rootBreak), mapRootLabel.slice(rootBreak)]
      : [mapRootLabel, ""];
    const branchMarkup = topic.mapNodes.map((node, index) => {
      const y = topic.mapNodes.length === 1
        ? 320
        : topic.mapNodes.length === 2
          ? 180 + 280 * index
          : 84 + branchGap * index;
      const children = node.children.slice(0, 6);
      const childMarkup = children.map((child, childIndex) => {
        const column = Math.floor(childIndex / 3);
        const row = childIndex % 3;
        const childX = 790 + column * 150;
        const childY = y + (row - Math.min(children.length - 1, 2) / 2) * 44;
        const leaves = mindMapChildLeaves(child);
        const labelLines = mindMapLabelLines(mindMapChildLabel(child));
        const labelStartY = childY + 6 - ((labelLines.length - 1) * 10);
        return `
          <text class="map-label" x="${childX}" y="${labelStartY}">
            ${labelLines.map((line, lineIndex) => `<tspan x="${childX}" dy="${lineIndex === 0 ? 0 : 20}">${escapeHtml(line)}</tspan>`).join("")}
          </text>
          ${leaves.length > 0 ? `
            <text class="map-note" x="${childX + 12}" y="${childY + 26}">${escapeHtml(leaves.join("、"))}</text>
          ` : ""}
        `;
      }).join("");
      return `
        <a href="${href(node.moduleId)}" data-learning-module="${escapeHtml(node.moduleId)}" class="map-branch-link" aria-label="进入${escapeHtml(node.label)}">
          <g class="map-tree ${colors[index % colors.length]}">
            <path class="map-line" d="M340 320 C420 320 414 ${y} 480 ${y}"></path>
            <g class="map-node map-node-primary">
              <rect x="480" y="${y - 30}" width="250" height="60" rx="13"></rect>
              <text x="605" y="${y + 8}" text-anchor="middle">${escapeHtml(node.label)}</text>
            </g>
            <path class="map-twig" d="M730 ${y} H770"></path>
            ${childMarkup}
          </g>
        </a>
      `;
    }).join("");
    return `
      <div class="senior-learning-map-shell">
        <svg class="senior-learning-map-svg" viewBox="0 0 1120 640" role="group" aria-labelledby="set-map-title-${escapeHtml(topic.id)} set-map-desc-${escapeHtml(topic.id)}">
          <title id="set-map-title-${escapeHtml(topic.id)}">${escapeHtml(topic.title)}知识导图</title>
          <desc id="set-map-desc-${escapeHtml(topic.id)}">${escapeHtml(topic.mapNodes.map((node) => `${node.label}包括${node.children.map(mindMapChildDescription).join("、")}`).join("；"))}</desc>
          <g class="map-root">
            <rect x="42" y="270" width="298" height="100" rx="20"></rect>
            <text x="191" y="313" text-anchor="middle">${escapeHtml(rootLines[0] || mapRootLabel)}</text>
            <text x="191" y="348" text-anchor="middle">${escapeHtml(rootLines[1])}</text>
          </g>
          ${branchMarkup}
        </svg>
        <div class="senior-learning-map-mobile" aria-label="知识导图移动端导航">
          ${topic.mapNodes.map((node) => `
            <a href="${escapeHtml(topicHref(topic, node.moduleId))}" data-learning-module="${escapeHtml(node.moduleId)}">
              <strong>${escapeHtml(node.label)}</strong>
              <span>${node.children.map((child) => escapeHtml(mindMapChildDescription(child))).join(" · ")}</span>
            </a>
          `).join("")}
        </div>
      </div>
    `;
  }

  function renderLearningOverview(topic) {
    return `
      <article class="senior-learning-topic">
        <header class="senior-learning-hero">
          <p class="senior-learning-kicker">${escapeHtml(topic.eyebrow || "知识专题")}</p>
          <h2>${escapeHtml(topic.title)}</h2>
          <div class="senior-learning-intro">
            ${topic.introductionHtml.map((line) => `<p>${line}</p>`).join("")}
          </div>
        </header>
        <section class="senior-learning-section" aria-labelledby="knowledge-map-heading">
          <div class="senior-learning-section-heading">
            <p>KNOWLEDGE MAP</p>
            <h2 id="knowledge-map-heading">知识导航</h2>
          </div>
          ${renderSetMindMap(topic)}
        </section>
        <section class="senior-learning-section" aria-labelledby="topic-modules-heading">
          <div class="senior-learning-section-heading">
            <p>LEARNING PATH</p>
            <h2 id="topic-modules-heading">按模块学习</h2>
          </div>
          <div class="senior-learning-module-grid">
            ${topic.modules.map((module, index) => `
              <a
                class="senior-learning-module-card${module.status === "pending" ? " is-pending" : ""}"
                href="${escapeHtml(topicHref(topic, module.id))}"
                data-learning-module="${escapeHtml(module.id)}"
              >
                <span class="senior-learning-module-index">${String(index + 1).padStart(2, "0")}</span>
                <div>
                  <h3>${escapeHtml(module.label)}</h3>
                  <p>${escapeHtml(module.description)}</p>
                </div>
                <span class="senior-learning-module-state">${module.status === "pending" ? "待补充" : "进入学习 →"}</span>
              </a>
            `).join("")}
          </div>
        </section>
      </article>
    `;
  }

  function renderKnowledgeModule(topic, module) {
    if (module.status === "pending") {
      return `
        <article class="senior-learning-topic">
          <header class="senior-learning-module-hero is-pending">
            <p class="senior-learning-kicker">知识模块 · 待补充</p>
            <h2>${escapeHtml(module.label)}</h2>
            <p>${escapeHtml(module.description)}</p>
          </header>
          <section class="senior-learning-pending-card">
            <h3>已确认的知识结构</h3>
            <div class="senior-learning-known-points">
              ${(module.knownPoints || []).map((point) => `<span>${escapeHtml(point)}</span>`).join("")}
            </div>
            <p>当前图片未包含这一模块的核心知识与对应例题。页面暂不自行补写内容，待教材资料补齐后发布。</p>
          </section>
          <a class="senior-learning-back-link" href="${escapeHtml(topicHref(topic, "overview"))}" data-learning-module="overview">← 返回知识导图</a>
        </article>
      `;
    }
    const circledKnowledgeNumber = (index) => ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"][index] || `${index + 1}.`;
    const renderKnowledgeBody = (block) => block.ordered
      ? `<ol class="senior-learning-knowledge-lines">${block.bodyHtml.map((line, index) => `
          <li><span class="senior-learning-knowledge-line-number" aria-hidden="true">${circledKnowledgeNumber(index)}</span><span>${line}</span></li>
        `).join("")}</ol>`
      : block.bodyHtml.map((line) => `<p>${line}</p>`).join("");
    const renderKnowledgeTable = (table) => table ? `
      <div class="senior-learning-knowledge-table-shell">
        <table class="senior-learning-knowledge-table">
          <tbody>${table.rowsHtml.map((row) => `<tr>${row.map((cell, index) => (
            index === 0 ? `<th scope="row">${cell}</th>` : `<td>${cell}</td>`
          )).join("")}</tr>`).join("")}</tbody>
        </table>
      </div>
    ` : "";
    const quadraticCaseMeta = {
      positive: { label: "Δ > 0", note: "两个交点" },
      zero: { label: "Δ = 0", note: "一个切点" },
      negative: { label: "Δ < 0", note: "没有交点" },
    };
    const renderQuadraticGraph = (opening, discriminant) => {
      const paths = {
        up: {
          positive: "M30 21 Q110 175 190 21",
          zero: "M30 20 Q110 132 190 20",
          negative: "M30 22 Q110 98 190 22",
        },
        down: {
          positive: "M30 111 Q110 13 190 111",
          zero: "M30 108 Q110 44 190 108",
          negative: "M30 112 Q110 70 190 112",
        },
      };
      const rootMarks = discriminant === "positive"
        ? `<circle cx="67" cy="76" r="3"></circle><circle cx="153" cy="76" r="3"></circle>
           <text x="58" y="94">x₁</text><text x="146" y="94">x₂</text>`
        : discriminant === "zero"
          ? `<circle cx="110" cy="76" r="3"></circle><text x="101" y="94">x₀</text>`
          : "";
      const meta = quadraticCaseMeta[discriminant];
      const openingLabel = opening === "up" ? "开口向上" : "开口向下";
      return `
        <svg class="quadratic-inequality-graph" viewBox="0 0 220 116" role="img" aria-label="${openingLabel}的抛物线，${meta.label}，${meta.note}">
          <line class="quadratic-graph-axis" x1="14" y1="76" x2="207" y2="76"></line>
          <path class="quadratic-graph-axis-arrow" d="M207 76l-7-4m7 4l-7 4"></path>
          <line class="quadratic-graph-axis" x1="110" y1="106" x2="110" y2="8"></line>
          <path class="quadratic-graph-axis-arrow" d="M110 8l-4 7m4-7l4 7"></path>
          <text class="quadratic-graph-axis-label" x="204" y="69">x</text>
          <text class="quadratic-graph-axis-label" x="117" y="15">y</text>
          <path class="quadratic-graph-curve" d="${paths[opening][discriminant]}"></path>
          <g class="quadratic-graph-roots">${rootMarks}</g>
        </svg>
      `;
    };
    const renderQuadraticInequalityTables = (tables) => tables ? `
      <div class="quadratic-inequality-tables" aria-label="一元二次不等式的图像与解集对照表">
        ${tables.map((quadraticTable) => `
          <div class="quadratic-inequality-table-shell is-${quadraticTable.opening}">
            <table class="quadratic-inequality-table">
              <caption>${quadraticTable.titleHtml}</caption>
              <thead>
                <tr>
                  <th scope="col"><span>判别式</span><strong>Δ = b² − 4ac</strong></th>
                  ${quadraticTable.cases.map((quadraticCase) => `<th scope="col">${quadraticCaseMeta[quadraticCase.discriminant].label}</th>`).join("")}
                </tr>
              </thead>
              <tbody>
                <tr class="quadratic-graph-row">
                  <th scope="row">函数图像<br><span>y = f(x)</span></th>
                  ${quadraticTable.cases.map((quadraticCase) => `<td>${renderQuadraticGraph(quadraticTable.opening, quadraticCase.discriminant)}</td>`).join("")}
                </tr>
                <tr>
                  <th scope="row">方程的根<br><span>f(x) = 0</span></th>
                  ${quadraticTable.cases.map((quadraticCase) => `<td>${quadraticCase.rootHtml}</td>`).join("")}
                </tr>
                <tr>
                  <th scope="row"><span class="quadratic-sign is-positive">f(x) &gt; 0</span></th>
                  ${quadraticTable.cases.map((quadraticCase) => `<td>${quadraticCase.positiveSolutionHtml}</td>`).join("")}
                </tr>
                <tr>
                  <th scope="row"><span class="quadratic-sign is-negative">f(x) &lt; 0</span></th>
                  ${quadraticTable.cases.map((quadraticCase) => `<td>${quadraticCase.negativeSolutionHtml}</td>`).join("")}
                </tr>
              </tbody>
            </table>
          </div>
        `).join("")}
        <p class="quadratic-inequality-reading"><strong>读图：</strong>图像在 x 轴上方取正，在 x 轴下方取负；若不等号含等号，再把相应实根并入解集。</p>
      </div>
    ` : "";
    const threadingLineMeta = {
      "simple-strict": {
        label: "基本穿法",
        note: "三个一次因式，经过每个根时符号交替。",
        curve: "M38 118 C76 118 98 96 120 72 C150 40 238 40 280 72 C322 104 398 106 440 72 C470 44 502 30 530 22",
        signs: ["−", "+", "−", "+"],
        inclusive: false,
        mixed: false,
      },
      "simple-inclusive": {
        label: "含等号",
        note: "穿法不变；因为含等号，三个根都用实心点。",
        curve: "M38 118 C76 118 98 96 120 72 C150 40 238 40 280 72 C322 104 398 106 440 72 C470 44 502 30 530 22",
        signs: ["−", "+", "−", "+"],
        inclusive: true,
        mixed: false,
      },
      "mixed-multiplicity": {
        label: "奇穿偶不穿",
        note: "奇数重根 0、2 处穿过数轴；偶数重根 −1、1 处接触数轴后返回。",
        curve: "M30 34 C55 28 78 32 92 50 C96 56 98 72 100 72 C102 72 106 56 112 50 C140 28 190 30 220 72 C250 110 310 108 332 94 C337 88 338 72 340 72 C342 72 345 88 350 94 C385 116 430 108 460 72 C485 42 510 30 535 24",
        signs: ["+", "+", "−", "−", "+"],
        inclusive: false,
        mixed: true,
      },
    };
    const renderThreadingLineGraph = (kind) => {
      const meta = threadingLineMeta[kind];
      const pointClass = meta.inclusive ? " is-closed" : " is-open";
      const highlights = meta.mixed
        ? `<line x1="220" y1="72" x2="333" y2="72"></line><line x1="347" y1="72" x2="460" y2="72"></line>`
        : `<line x1="120" y1="72" x2="280" y2="72"></line><line x1="440" y1="72" x2="532" y2="72"></line>`;
      const shades = meta.mixed
        ? `<path d="M220 72 C250 110 310 108 332 94 C337 88 338 72 340 72 L220 72 Z"></path>
           <path d="M340 72 C342 72 345 88 350 94 C385 116 430 108 460 72 L340 72 Z"></path>`
        : `<path d="M120 72 C150 40 238 40 280 72 L120 72 Z"></path>
           <path d="M440 72 C470 44 502 30 530 22 L530 72 L440 72 Z"></path>`;
      const rootPoints = meta.mixed
        ? `<circle cx="100" cy="72" r="5"></circle><circle cx="220" cy="72" r="5"></circle><circle cx="340" cy="72" r="5"></circle><circle cx="460" cy="72" r="5"></circle>`
        : `<circle cx="120" cy="72" r="5"></circle><circle cx="280" cy="72" r="5"></circle><circle cx="440" cy="72" r="5"></circle>`;
      const rootLabels = meta.mixed
        ? `<text x="92" y="92">−1</text><text x="216" y="92">0</text><text x="336" y="92">1</text><text x="456" y="92">2</text>
           <text class="threading-line-root-multiplicity" x="70" y="108">（4次·偶）</text>
           <text class="threading-line-root-multiplicity" x="190" y="108">（5次·奇）</text>
           <text class="threading-line-root-multiplicity" x="310" y="108">（2次·偶）</text>
           <text class="threading-line-root-multiplicity" x="430" y="108">（3次·奇）</text>`
        : `<text x="109" y="92">−2</text><text x="276" y="92">1</text><text x="436" y="92">3</text>`;
      const signXs = meta.mixed ? [48, 154, 274, 394, 504] : [72, 194, 354, 494];
      const directionPaths = meta.mixed
        ? `<path d="M525 29 C500 32 480 46 468 64"></path><path d="M468 64 L472 54 M468 64 L478 62"></path>`
        : `<path d="M520 27 C490 31 464 48 448 66"></path><path d="M448 66 L452 56 M448 66 L458 64"></path>`;
      return `
        <svg class="threading-line-graph" viewBox="0 0 560 148" role="img" aria-label="${meta.label}的穿针引线图">
          <g class="threading-line-shade">${shades}</g>
          <line class="threading-line-axis" x1="24" y1="72" x2="538" y2="72"></line>
          <path class="threading-line-arrow" d="M538 72l-8-5m8 5l-8 5"></path>
          <g class="threading-line-solution">${highlights}</g>
          <path class="threading-line-curve" d="${meta.curve}"></path>
          <g class="threading-line-direction" aria-hidden="true">
            <text x="438" y="14">从最右侧开始</text>
            ${directionPaths}
          </g>
          <g class="threading-line-points${pointClass}">${rootPoints}</g>
          ${meta.mixed ? `<circle class="threading-line-even-ring" cx="100" cy="72" r="9"></circle><circle class="threading-line-even-ring" cx="340" cy="72" r="9"></circle>` : ""}
          <g class="threading-line-root-labels">${rootLabels}</g>
          <g class="threading-line-signs">
            ${meta.signs.map((sign, index) => `<text x="${signXs[index]}" y="${sign === "+" ? 30 : 126}">${sign}</text>`).join("")}
          </g>
        </svg>
      `;
    };
    const renderThreadingLineTable = (table) => table ? `
      <div class="threading-line-table-shell">
        <table class="threading-line-table">
          <thead>
            <tr><th scope="col">不等式、图形与解集</th><th scope="col">这一行说明的原则</th></tr>
          </thead>
          <tbody>
            ${table.rows.map((row, index) => {
              const meta = threadingLineMeta[row.kind];
              return `<tr>
                <td>
                  <div class="threading-line-example-heading"><span>${String(index + 1).padStart(2, "0")}</span><strong>${meta.label}</strong>${row.inequalityHtml}</div>
                  ${renderThreadingLineGraph(row.kind)}
                  <div class="threading-line-result"><span>解集</span><strong>${row.solutionHtml}</strong></div>
                  <p>${meta.note}</p>
                </td>
                <td>
                  <ol>${row.principlesHtml.map((principle) => `<li>${principle}</li>`).join("")}</ol>
                </td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>
      </div>
    ` : "";
    const rationalThreadingMeta = {
      "direct-strict": {
        label: "直接判号",
        note: "两个临界点都不取，解集在数轴两端。",
        leftRoot: "−3",
        rightRoot: "1",
        numeratorClosed: false,
        solution: "outside",
      },
      "inclusive-endpoints": {
        label: "端点辨析",
        note: "分母零点仍空心，只有分子零点因含等号而变为实心。",
        leftRoot: "−1/3",
        rightRoot: "1/2",
        numeratorClosed: true,
        solution: "outside",
      },
      "move-to-zero": {
        label: "先移项通分",
        note: "化为右边是 0 的标准形式后，再读取阴影区间。",
        leftRoot: "−3",
        rightRoot: "−1/2",
        numeratorClosed: false,
        solution: "inside",
      },
    };
    const renderRationalThreadingGraph = (kind) => {
      const meta = rationalThreadingMeta[kind];
      const outside = meta.solution === "outside";
      const highlights = outside
        ? `<line x1="28" y1="72" x2="180" y2="72"></line><line x1="400" y1="72" x2="532" y2="72"></line>`
        : `<line x1="180" y1="72" x2="400" y2="72"></line>`;
      const shades = outside
        ? `<path d="M35 28 C100 30 150 45 180 72 L35 72 Z"></path><path d="M400 72 C440 38 490 27 530 24 L530 72 L400 72 Z"></path>`
        : `<path d="M180 72 C220 112 350 112 400 72 L180 72 Z"></path>`;
      return `
        <svg class="rational-threading-graph" viewBox="0 0 560 142" role="img" aria-label="${meta.label}的分式不等式穿针图">
          <g class="threading-line-shade">${shades}</g>
          <line class="threading-line-axis" x1="24" y1="72" x2="538" y2="72"></line>
          <path class="threading-line-arrow" d="M538 72l-8-5m8 5l-8 5"></path>
          <g class="threading-line-solution">${highlights}</g>
          <path class="threading-line-curve" d="M35 28 C100 30 150 45 180 72 C220 112 350 112 400 72 C440 38 490 27 530 24"></path>
          <g class="threading-line-direction" aria-hidden="true">
            <text x="438" y="14">从最右侧开始</text>
            <path d="M520 28 C478 31 438 47 408 66"></path>
            <path d="M408 66 L413 56 M408 66 L418 64"></path>
          </g>
          <circle class="rational-critical-point is-forbidden" cx="180" cy="72" r="6"></circle>
          <path class="rational-forbidden-slash" d="M174 79 L186 65"></path>
          <circle class="rational-critical-point${meta.numeratorClosed ? " is-closed" : " is-open"}" cx="400" cy="72" r="6"></circle>
          <g class="rational-root-labels">
            <text x="164" y="93">${meta.leftRoot}</text><text x="390" y="93">${meta.rightRoot}</text>
            <text class="rational-root-kind is-forbidden" x="139" y="109">（分母·禁值）</text>
            <text class="rational-root-kind" x="363" y="109">（分子·零点）</text>
          </g>
          <g class="threading-line-signs">
            <text x="91" y="30">+</text><text x="284" y="126">−</text><text x="478" y="30">+</text>
          </g>
        </svg>
      `;
    };
    const renderRationalThreadingTable = (table) => table ? `
      <div class="threading-line-table-shell rational-threading-table-shell">
        <table class="threading-line-table rational-threading-table">
          <thead><tr><th scope="col">分式、标准化与穿针图</th><th scope="col">这一行说明的原则</th></tr></thead>
          <tbody>
            ${table.rows.map((row, index) => {
              const meta = rationalThreadingMeta[row.kind];
              return `<tr>
                <td>
                  <div class="threading-line-example-heading"><span>${String(index + 1).padStart(2, "0")}</span><strong>${meta.label}</strong>${row.inequalityHtml}</div>
                  <div class="rational-equivalent"><span>化为</span><strong>${row.equivalentHtml}</strong></div>
                  ${renderRationalThreadingGraph(row.kind)}
                  <div class="threading-line-result"><span>解集</span><strong>${row.solutionHtml}</strong></div>
                  <p>${meta.note}</p>
                </td>
                <td><ol>${row.principlesHtml.map((principle) => `<li>${principle}</li>`).join("")}</ol></td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>
      </div>
    ` : "";
    const absoluteInequalityMeta = {
      direct: {
        label: "直接法",
        note: "单个绝对值小于正常数，解集是两个边界之间的区间。",
      },
      squaring: {
        label: "平方法（快捷）",
        note: "两个绝对值均非负，平方后转化为整式不等式，解集取两端。",
      },
      classification: {
        label: "分类讨论法",
        note: "在分界点 −2、1 处分段，图像在 x 轴上方的部分对应原不等式。",
      },
    };
    const renderAbsoluteInequalityGraph = (kind) => {
      if (kind === "direct") return `
        <svg class="absolute-method-graph" viewBox="0 0 560 118" role="img" aria-label="直接法得到负一到零之间的开区间">
          <rect class="absolute-solution-band" x="200" y="49" width="160" height="34" rx="17"></rect>
          <line class="threading-line-axis" x1="24" y1="66" x2="538" y2="66"></line>
          <path class="threading-line-arrow" d="M538 66l-8-5m8 5l-8 5"></path>
          <g class="threading-line-solution"><line x1="200" y1="66" x2="360" y2="66"></line></g>
          <g class="threading-line-points is-open"><circle cx="200" cy="66" r="6"></circle><circle cx="360" cy="66" r="6"></circle></g>
          <g class="absolute-root-labels"><text x="190" y="88">−1</text><text x="356" y="88">0</text></g>
          <text class="absolute-graph-caption" x="243" y="35">小于取中间</text>
        </svg>`;
      if (kind === "squaring") return `
        <svg class="absolute-method-graph" viewBox="0 0 560 130" role="img" aria-label="平方后整式不等式的符号图">
          <g class="threading-line-shade"><path d="M40 25 Q110 30 180 66 L40 66 Z"></path><path d="M380 66 Q450 30 520 25 L520 66 Z"></path></g>
          <line class="threading-line-axis" x1="24" y1="66" x2="538" y2="66"></line>
          <path class="threading-line-arrow" d="M538 66l-8-5m8 5l-8 5"></path>
          <g class="threading-line-solution"><line x1="28" y1="66" x2="180" y2="66"></line><line x1="380" y1="66" x2="532" y2="66"></line></g>
          <path class="threading-line-curve" d="M40 25 Q280 124 520 25"></path>
          <g class="threading-line-points is-open"><circle cx="180" cy="66" r="6"></circle><circle cx="380" cy="66" r="6"></circle></g>
          <g class="absolute-root-labels"><text x="170" y="88">−2</text><text x="376" y="88">0</text></g>
          <g class="threading-line-signs"><text x="96" y="28">+</text><text x="276" y="112">−</text><text x="464" y="28">+</text></g>
          <text class="absolute-graph-caption" x="208" y="124">平方后：x(x+2) &gt; 0</text>
        </svg>`;
      return `
        <svg class="absolute-method-graph is-classification" viewBox="0 0 560 146" role="img" aria-label="分类讨论所得分段函数图像">
          <g class="threading-line-shade"><path d="M50 20 L140 74 L50 74 Z"></path><path d="M408 74 L500 20 L500 74 Z"></path></g>
          <line class="threading-line-axis" x1="24" y1="74" x2="538" y2="74"></line>
          <path class="threading-line-arrow" d="M538 74l-8-5m8 5l-8 5"></path>
          <line class="absolute-y-axis" x1="280" y1="126" x2="280" y2="10"></line>
          <path class="absolute-y-axis-arrow" d="M280 10l-5 8m5-8l5 8"></path>
          <g class="threading-line-solution"><line x1="28" y1="74" x2="140" y2="74"></line><line x1="408" y1="74" x2="532" y2="74"></line></g>
          <path class="absolute-piecewise-curve" d="M50 20 L190 108 L350 108 L500 20"></path>
          <g class="absolute-break-lines"><line x1="190" y1="68" x2="190" y2="116"></line><line x1="350" y1="68" x2="350" y2="116"></line></g>
          <g class="threading-line-points is-closed"><circle cx="140" cy="74" r="6"></circle><circle cx="408" cy="74" r="6"></circle></g>
          <g class="absolute-root-labels"><text x="130" y="94">−3</text><text x="403" y="94">2</text><text class="is-break" x="181" y="127">−2</text><text class="is-break" x="346" y="127">1</text></g>
          <text class="absolute-axis-label" x="290" y="18">y</text><text class="absolute-axis-label" x="526" y="67">x</text>
        </svg>`;
    };
    const renderAbsoluteInequalityTable = (table) => table ? `
      <div class="threading-line-table-shell absolute-inequality-table-shell">
        <table class="threading-line-table absolute-inequality-table">
          <thead><tr><th scope="col">绝对值不等式、转化与图形</th><th scope="col">适用原则</th></tr></thead>
          <tbody>
            ${table.rows.map((row, index) => {
              const meta = absoluteInequalityMeta[row.kind];
              return `<tr>
                <td>
                  <div class="threading-line-example-heading"><span>${String(index + 1).padStart(2, "0")}</span><strong>${meta.label}</strong>${row.inequalityHtml}</div>
                  <div class="absolute-transformations"><span>转化</span><div>${row.transformationsHtml.map((transformation) => `<p>${transformation}</p>`).join("")}</div></div>
                  ${renderAbsoluteInequalityGraph(row.kind)}
                  <div class="threading-line-result"><span>解集</span><strong>${row.solutionHtml}</strong></div>
                  <p>${meta.note}</p>
                </td>
                <td><ol>${row.principlesHtml.map((principle) => `<li>${principle}</li>`).join("")}</ol></td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>
      </div>
    ` : "";
    const mathFraction = (numerator, denominator) => `<span class="math-fraction"><span class="math-numerator">${numerator}</span><span class="math-denominator">${denominator}</span></span>`;
    const mathRadical = (radicand) => `<span class="math-radical"><span class="math-radical-symbol">√</span><span class="math-radicand">${radicand}</span></span>`;
    const inlineMath = (content) => `<span class="inline-math">${content}</span>`;
    const renderBasicInequalityAreaFigure = () => `
      <svg class="basic-inequality-figure is-area" viewBox="0 0 450 286" role="img" aria-label="四个全等直角三角形拼成正方形，中间留下一个小正方形">
        <rect class="basic-area-outer" x="50" y="24" width="250" height="250"></rect>
        <polygon class="basic-area-triangle" points="50,24 300,24 210,144"></polygon>
        <polygon class="basic-area-triangle" points="300,24 300,274 180,184"></polygon>
        <polygon class="basic-area-triangle" points="300,274 50,274 140,154"></polygon>
        <polygon class="basic-area-triangle" points="50,274 50,24 170,114"></polygon>
        <polygon class="basic-area-center" points="210,144 180,184 140,154 170,114"></polygon>
        <path class="basic-area-right-angle" d="M197.2 134.4 L206.8 121.6 L219.6 131.2"></path>
        <text class="basic-area-point" x="38" y="19">A</text><text class="basic-area-point" x="304" y="19">B</text>
        <text class="basic-area-point" x="304" y="283">C</text><text class="basic-area-point" x="36" y="283">D</text>
        <text class="basic-area-point is-center" x="213" y="144">E</text><text class="basic-area-point is-center" x="183" y="199">F</text>
        <text class="basic-area-point is-center" x="124" y="157">G</text><text class="basic-area-point is-center" x="157" y="108">H</text>
        <g class="basic-area-leg-label"><text x="113" y="92">√a</text><text x="240" y="90">√b</text></g>
        <text class="basic-area-center-label" x="155" y="153">EFGH</text>
        <g class="basic-area-legend" transform="translate(322 72)">
          <rect class="is-triangle" width="18" height="18" rx="4"></rect><text x="27" y="14">全等直角三角形</text>
          <rect class="is-center" y="38" width="18" height="18" rx="4"></rect><text x="27" y="52">非负的面积</text>
        </g>
      </svg>`;
    const renderBasicInequalitySemicircleFigure = () => `
      <svg class="basic-inequality-figure is-semicircle" viewBox="0 0 520 260" role="img" aria-label="半圆中几何平均数是高，算术平均数是半径">
        <path class="basic-semicircle-arc" d="M80 192 A180 180 0 0 1 440 192"></path>
        <line class="basic-semicircle-diameter" x1="80" y1="192" x2="440" y2="192"></line>
        <polygon class="basic-semicircle-triangle is-left" points="80,192 205,192 205,21"></polygon>
        <polygon class="basic-semicircle-triangle is-right" points="205,192 440,192 205,21"></polygon>
        <line class="basic-semicircle-side" x1="80" y1="192" x2="205" y2="21"></line>
        <line class="basic-semicircle-side" x1="205" y1="21" x2="440" y2="192"></line>
        <line class="basic-semicircle-height" x1="205" y1="192" x2="205" y2="21"></line>
        <line class="basic-semicircle-radius" x1="260" y1="192" x2="205" y2="21"></line>
        <path class="basic-semicircle-right-angle" d="M205 178h14v14"></path>
        <circle class="basic-semicircle-point" cx="80" cy="192" r="4"></circle><circle class="basic-semicircle-point" cx="205" cy="192" r="4"></circle>
        <circle class="basic-semicircle-point" cx="260" cy="192" r="4"></circle><circle class="basic-semicircle-point" cx="440" cy="192" r="4"></circle>
        <circle class="basic-semicircle-point" cx="205" cy="21" r="4"></circle>
        <g class="basic-semicircle-labels"><text x="65" y="214">A</text><text x="196" y="214">C</text><text x="254" y="214">O</text><text x="443" y="214">B</text><text x="193" y="15">D</text>
          <text x="136" y="184">a</text><text x="326" y="184">b</text><text class="is-height" x="214" y="104">√ab</text>
          <text class="is-radius" x="238" y="91">(a+b)/2</text>
        </g>
      </svg>`;
    const renderBasicInequalityVisual = (block) => block?.basicInequalityVisual ? `
      <div class="basic-inequality-visual">
        <section class="basic-inequality-theorem" aria-label="基本不等式的结论与条件">
          <div class="basic-inequality-theorem-copy">
            <span class="basic-inequality-domain">a &gt; 0，b &gt; 0</span>
            <strong>两个正数的算术平均数不小于它们的几何平均数</strong>
          </div>
          <div class="basic-inequality-theorem-formula">
            <span class="basic-mean is-arithmetic"><small>算术平均数</small>${inlineMath(mathFraction("a+b", "2"))}</span>
            <span class="basic-inequality-relation">≥</span>
            <span class="basic-mean is-geometric"><small>几何平均数</small>${inlineMath(mathRadical("ab"))}</span>
          </div>
          <div class="basic-inequality-equivalents">
            <span>等价形式 ${inlineMath(`a+b≥2${mathRadical("ab")}`)}</span>
            <span>当且仅当 ${inlineMath("a=b")} 时取等号</span>
          </div>
        </section>
        <div class="basic-inequality-proof-table-shell">
          <table class="basic-inequality-proof-table">
            <thead><tr><th scope="col">三种推导，一眼看懂</th><th scope="col">关键关系</th></tr></thead>
            <tbody>
              <tr>
                <td>
                  <div class="basic-inequality-method-heading"><span>01</span><strong>面积几何证明</strong><em>面积不会是负数</em></div>
                  ${renderBasicInequalityAreaFigure()}
                </td>
                <td>
                  <div class="basic-inequality-reasoning">
                    <p><b>直角边：</b>${inlineMath(mathRadical("a"))} 与 ${inlineMath(mathRadical("b"))}</p>
                    <p><b>外正方形面积：</b>${inlineMath("S<sub>ABCD</sub>=a+b")}</p>
                    <p><b>四个三角形面积：</b>${inlineMath(`4×${mathFraction("1", "2")}×${mathRadical("a")}×${mathRadical("b")}=2${mathRadical("ab")}`)}</p>
                    <p class="is-conclusion"><b>中间正方形：</b>${inlineMath(`S<sub>EFGH</sub>=a+b−2${mathRadical("ab")}≥0`)}</p>
                  </div>
                </td>
              </tr>
              <tr>
                <td>
                  <div class="basic-inequality-method-heading"><span>02</span><strong>完全平方证明</strong><em>把两种平均数作差</em></div>
                  <div class="basic-inequality-algebra-flow" aria-label="算术平均数减几何平均数化成完全平方">
                    <span>${inlineMath(`${mathFraction("a+b", "2")}−${mathRadical("ab")}`)}</span><i>＝</i>
                    <span>${inlineMath(mathFraction(`a+b−2${mathRadical("ab")}`, "2"))}</span><i>＝</i>
                    <strong>${inlineMath(mathFraction(`(${mathRadical("a")}−${mathRadical("b")})<sup>2</sup>`, "2"))}</strong>
                  </div>
                </td>
                <td>
                  <div class="basic-inequality-reasoning is-algebra">
                    <p>对任意实数，完全平方都满足 ${inlineMath(`(${mathRadical("a")}−${mathRadical("b")})<sup>2</sup>≥0`)}。</p>
                    <p class="is-conclusion">因此 ${inlineMath(`${mathFraction("a+b", "2")}−${mathRadical("ab")}≥0`)}。</p>
                    <p>等号成立 ⇔ ${inlineMath(`${mathRadical("a")}=${mathRadical("b")}`)} ⇔ ${inlineMath("a=b")}。</p>
                  </div>
                </td>
              </tr>
              <tr>
                <td>
                  <div class="basic-inequality-method-heading"><span>03</span><strong>半圆几何证明</strong><em>直角三角形中斜边最长</em></div>
                  ${renderBasicInequalitySemicircleFigure()}
                </td>
                <td>
                  <div class="basic-inequality-reasoning">
                    <p>${inlineMath("△ACD∽△DCB")}，所以 ${inlineMath(`${mathFraction("AC", "CD")}=${mathFraction("CD", "CB")}`)}。</p>
                    <p>${inlineMath("CD<sup>2</sup>=AC·CB=ab")}，即 ${inlineMath(`CD=${mathRadical("ab")}`)}。</p>
                    <p>${inlineMath(`OD=${mathFraction("AB", "2")}=${mathFraction("a+b", "2")}`)}；在直角三角形 ${inlineMath("OCD")} 中，斜边 ${inlineMath("OD≥CD")}。</p>
                    <p class="is-conclusion">所以 ${inlineMath(`${mathFraction("a+b", "2")}≥${mathRadical("ab")}`)}。</p>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <section class="basic-inequality-forms-map" aria-label="基本不等式的等价形式">
          <header>
            <div><span>FORM MAP</span><strong>一个基本式，四种等价表达</strong></div>
            <p>移项、平方或展开，只改变公式的外形，不改变它表达的大小关系。</p>
          </header>
          <div class="basic-inequality-equivalent-track" aria-label="基本不等式的等价改写">
            <span>基本式</span>
            <strong>${inlineMath(`${mathFraction("a+b", "2")}≥${mathRadical("ab")}`)}</strong>
            <i aria-hidden="true">⇔</i>
            <strong>${inlineMath(`a+b≥2${mathRadical("ab")}`)}</strong>
            <i aria-hidden="true">⇔</i>
            <strong>${inlineMath("(a+b)<sup>2</sup>≥4ab")}</strong>
            <i aria-hidden="true">⇔</i>
            <strong>${inlineMath("a<sup>2</sup>+b<sup>2</sup>≥2ab")}</strong>
            <small>${inlineMath("a&gt;0，b&gt;0")}</small>
          </div>
          <p class="basic-inequality-forms-note"><span>同源关系</span>四种写法都可以化为同一个非负平方，因此等号条件始终是 ${inlineMath("a=b")}。</p>
        </section>
      </div>
    ` : "";
    const renderBasicInequalityConditions = (block) => {
      if (!block?.basicInequalityConditions) return "";
      const meta = [
        {
          number: "一",
          title: "一正",
          question: "选出的两个量都为正吗？",
          visual: `<div class="basic-condition-positive"><b>${inlineMath("a&gt;0")}</b><span>且</span><b>${inlineMath("b&gt;0")}</b><em>✓</em></div>`,
        },
        {
          number: "二",
          title: "二定",
          question: "和或积中有可确定的量吗？",
          visual: `<div class="basic-condition-fixed"><b>${inlineMath("ab=P")}</b><span>或</span><b>${inlineMath("a+b=S")}</b></div>`,
        },
        {
          number: "三",
          title: "三相等",
          question: "取等条件与原题条件相容吗？",
          visual: `<div class="basic-condition-equality"><b>${inlineMath("a=b")}</b><i aria-hidden="true">+</i><b>原题条件</b><i aria-hidden="true">→</i><em>有解 ✓</em></div>`,
        },
      ];
      return `<div class="basic-inequality-conditions-visual">
        <header>
          <div><span>CHECK FLOW</span><strong>从“能不能用”检查到“最值能不能取到”</strong></div>
          <p>使用条件和等号条件是一条完整判断链；“三相等”就是最后的取等验证。</p>
        </header>
        <div class="basic-inequality-conditions">
          ${meta.map((item, index) => `<article>
            <div class="basic-condition-heading"><span>${item.number}</span><div><strong>${item.title}</strong><p>${item.question}</p></div></div>
            ${item.visual}
            <small>${block.bodyHtml[index] || ""}</small>
          </article>${index < meta.length - 1 ? `<i class="basic-condition-arrow" aria-hidden="true">→</i>` : ""}`).join("")}
        </div>
        <div class="basic-condition-closure">
          <span>结论闭环</span>
          <p><b>一正、二定</b>保证不等式能给出一个界；<b>三相等</b>保证这个界确实能够取到，才能称为最大值或最小值。</p>
        </div>
      </div>`;
    };
    const renderBasicInequalityMethodRoute = (topic, moduleId, methodGroups) => {
      const groupById = Object.fromEntries(methodGroups.map((group) => [group.id, group]));
      const structureClues = [
        { id: "basic-application", probe: "定和 / 定积" },
        { id: "symmetric-structure", probe: "交换不变" },
        { id: "homogeneous-form", probe: "次数配成 0" },
        { id: "iterated-product", probe: "多轮配对" },
      ];
      const renderExpressionBars = () => `
        <div class="basic-method-route-expression" aria-hidden="true">
          <i></i><i></i><i class="is-short"></i>
        </div>`;
      const renderStructureGlyph = (id) => {
        if (id === "basic-application") return `
          <div class="basic-method-structure-glyph is-basic" aria-hidden="true">
            <div class="basic-method-paired-row">
              <span class="basic-method-mini-slot is-square"></span><i>＋</i><span class="basic-method-mini-slot is-circle"></span><b>定</b>
            </div>
            <em>⇅</em>
            <div class="basic-method-paired-row is-product">
              <span class="basic-method-mini-slot is-square"></span><i>·</i><span class="basic-method-mini-slot is-circle"></span><b>最值</b>
            </div>
          </div>`;
        if (id === "symmetric-structure") return `
          <div class="basic-method-structure-glyph is-symmetric" aria-hidden="true">
            <div class="basic-method-swap-symbol"><b>x</b><i>↔</i><b>y</b></div>
            <div class="basic-method-swap-equation">
              <span><small>原式</small></span><b>＝</b><span class="is-swapped"><small>交换后</small></span>
            </div>
          </div>`;
        if (id === "homogeneous-form") return `
          <div class="basic-method-structure-glyph is-homogeneous" aria-hidden="true">
            <div class="basic-method-degree-sources">
              <span class="basic-method-degree-box"><sup>m</sup></span>
              <b>×</b>
              <span class="basic-method-degree-box is-condition"><sup>n</sup></span>
              <b class="is-arrow">→</b>
              <span class="basic-method-degree-box is-zero"><sup>0</sup></span>
            </div>
            <p class="basic-method-round-probe"><b>m+n=0</b></p>
          </div>`;
        return `
          <div class="basic-method-structure-glyph is-repeated" aria-hidden="true">
            <div class="basic-method-count-glyph">
              <span><small>变量数</small><b>n</b></span><i>−</i>
              <span><small>已有取等</small><b>k</b></span><i>＝</i>
              <strong><small>预计</small><b>n−k 次</b></strong>
            </div>
            <p class="basic-method-round-probe"><b>n−k&gt;1</b></p>
          </div>`;
      };
      const renderClueLink = ({ id, probe }) => {
        const group = groupById[id];
        if (!group) return "";
        return `
          <a class="basic-method-route-clue is-${escapeHtml(id)}" href="${escapeHtml(learningMethodGuideHref(topic, moduleId, id))}" data-learning-method="${escapeHtml(id)}" aria-label="${escapeHtml(`${probe}：${group.title}`)}">
            ${renderStructureGlyph(id)}
            <small class="basic-method-route-probe">${probe}</small>
            <strong>${escapeHtml(group.title)}</strong>
          </a>`;
      };
      const renderSecondaryGlyph = (id) => {
        if (id === "substitution-method") return `
          <div class="basic-method-secondary-glyph is-substitution" aria-hidden="true">
            <span class="is-fraction"><sup>1</sup><i>/</i><b></b></span>
            <i>或</i>
            <span class="is-radical"><b>√</b><em></em></span>
            <i>→</i>
            <strong>u</strong>
          </div>`;
        return `
          <div class="basic-method-secondary-glyph is-elimination" aria-hidden="true">
            <span>y<i>=</i><b></b></span>
            <i>→</i>
            <strong>一元式</strong>
          </div>`;
      };
      const renderSecondaryLink = (id, { question, note, isFallback = false }) => {
        const group = groupById[id];
        if (!group) return "";
        return `
          <a class="basic-method-route-secondary-link${isFallback ? " is-fallback" : ""}" href="${escapeHtml(learningMethodGuideHref(topic, moduleId, id))}" data-learning-method="${escapeHtml(id)}">
            ${renderSecondaryGlyph(id)}
            <strong>${escapeHtml(group.title)}</strong>
            <span>${question}</span>
            ${note ? `<small>${note}</small>` : ""}
          </a>`;
      };
      return `
        <div class="basic-inequality-method-route" aria-label="基本不等式方法判题路由">
          <header class="method-intro basic-method-route-intro">
            <span>核心意义</span>
            <strong>选方法的关键，是先观察条件整式与目标整式的结构</strong>
          </header>
          <section class="basic-method-route-core method-core" aria-label="观察结构决定第一入口">
            <div class="basic-method-route-focus">
              <article class="basic-method-route-target">
                <span>条件整式</span>
                ${renderExpressionBars()}
              </article>
              <div class="basic-method-route-lens">
                <span>观察</span>
                <strong>结构</strong>
              </div>
              <article class="basic-method-route-target">
                <span>目标整式</span>
                ${renderExpressionBars()}
              </article>
            </div>
            <i class="basic-method-route-core-arrow" aria-hidden="true">↓</i>
            <div class="basic-method-route-clues" aria-label="四条结构线索">
              ${structureClues.map((clue) => renderClueLink(clue)).join("")}
            </div>
            <p class="basic-method-route-zero-meaning">
              <strong>观察结构</strong><b>→</b><span>题目中的式子能放进哪张结构图？</span>
            </p>
          </section>
          <section class="basic-method-route-secondary" aria-label="改写与兜底">
            <article class="basic-method-route-secondary-card is-rewrite">
              <header><span>结构被挡住</span><strong>换元改写后再观察</strong></header>
              ${renderSecondaryLink("substitution-method", {
                question: "令 u 换元，同步改写条件整式与目标整式",
                note: "完整分母 / 根号整体",
              })}
            </article>
            <article class="basic-method-route-secondary-card is-fallback">
              <header><span>仍不顺</span><strong>条件消元兜底</strong></header>
              ${renderSecondaryLink("conditional-elimination", {
                question: "条件能表出一个变量？",
                note: "代入目标整式降成一元式",
                isFallback: true,
              })}
            </article>
          </section>
          <p class="basic-method-route-closure"><span>落地</span><strong>选定方法后，仍要验证取等</strong><small>（对应「三相等」）</small></p>
        </div>`;
    };
    const basicSlot = (kind, label = "") => `<span class="basic-positive-slot is-${kind}"${label ? ` aria-label="${escapeHtml(label)}"` : ""}></span>`;
    const renderBasicSlotRouteProblem = (label, problem) => `
      <div class="basic-slot-route-problem"><span>${label}</span><p>${problem}</p></div>`;
    const renderBasicSlotRouteStep = (label, content) => `
      <div class="basic-slot-route-step"><small>${label}</small><div>${content}</div></div>`;
    const renderBasicInequalitySlotVisual = (block) => block?.basicInequalitySlotVisual ? `
      <div class="basic-inequality-slot-method">
        <header class="method-intro">
          <span>核心意义</span>
          <strong>比较的不是两个特定字母，而是两个完整的正项表达式</strong>
        </header>
        <div class="basic-slot-template method-core" aria-label="两个完整正项的基本不等式图示">
          <div class="basic-positive-kinds" aria-label="可作为正项的四种形式">
            <article><span>正变量</span><strong>${inlineMath("m&gt;0")}</strong></article>
            <article><span>正常数</span><strong>${inlineMath("3&gt;0")}</strong></article>
            <article><span>完整表达式</span><strong>${inlineMath("x+1&gt;0")}</strong></article>
            <article><span>函数值</span><strong>${inlineMath("f(x)&gt;0")}</strong></article>
          </div>
          <p class="basic-positive-bridge"><span>均可作为</span><strong>完整正项</strong><span>代入方框</span></p>
          <div class="basic-slot-formula">
            <div class="basic-slot-formula-lhs">
              ${basicSlot("square", "第一个正项")}<i>＋</i>${basicSlot("circle", "第二个正项")}
            </div>
            <b>≥</b>
            <strong>2${mathRadical(`${basicSlot("square")}<em>·</em>${basicSlot("circle")}`)}</strong>
          </div>
          <div class="basic-slot-equality">
            <strong>取等</strong><b>⇔</b>${basicSlot("square", "第一个正项")}<i>=</i>${basicSlot("circle", "第二个正项")}
          </div>
        </div>
        <section class="basic-slot-how method-how">
          <header><span>HOW</span><strong>先识别正项，再代入槽位验证取等</strong></header>
          <div class="basic-slot-pipeline" aria-label="直接应用基本不等式操作步骤">
            <article><span>①</span><strong>识别正项</strong><small>正变量、正常数、完整表达式或函数值，整体 &gt; 0</small></article>
            <i aria-hidden="true">→</i>
            <article><span>②</span><strong>代入槽位</strong><small>□ 与 ○ 同步替换</small></article>
            <i aria-hidden="true">→</i>
            <article><span>③</span><strong>验证取等</strong><small>□=○ 能否成立</small></article>
          </div>
          <div class="basic-slot-routes" aria-label="直接应用基本不等式的两条路径">
            <article class="basic-slot-route-card is-direct">
              <header><span>直接代入</span><strong>目标已露出两个正项</strong></header>
              ${renderBasicSlotRouteProblem("练习 8·1", `正实数 ${inlineMath("m，n")} 满足 ${inlineMath("m+n=2")}，求 ${inlineMath("mn")} 的最大值。`)}
              ${renderBasicSlotRouteStep("识别正项", `${inlineMath("m&gt;0")}，${inlineMath("n&gt;0")}`)}
              ${renderBasicSlotRouteStep("代入槽位", `${basicSlot("square")}<i>←</i>${inlineMath("m")}<i>，</i>${basicSlot("circle")}<i>←</i>${inlineMath("n")}<i> → </i>${inlineMath(`${mathFraction("m+n", "2")}≥${mathRadical("mn")}`)}`)}
              ${renderBasicSlotRouteStep("代入定和", `${inlineMath("m+n=2")}<i> → </i>${inlineMath(`1≥${mathRadical("mn")}`)}<i> → </i>${inlineMath("mn≤1")}`)}
              <p class="basic-slot-route-result"><span>验证取等</span><strong>${inlineMath("m=n=1")} 时取等，最大值为 ${inlineMath("1")}</strong></p>
              <small class="basic-slot-route-lessons">同类：练习 8·2</small>
            </article>
            <article class="basic-slot-route-card is-rearranged">
              <header><span>整理后代入</span><strong>先改写目标，让正项显形</strong></header>
              ${renderBasicSlotRouteProblem("练习 8·7", `已知 ${inlineMath("x&gt;-1")}，求 ${inlineMath(`x+${mathFraction("4", "x+1")}`)} 的最小值。`)}
              ${renderBasicSlotRouteStep("整理目标", `${inlineMath("x=(x+1)−1")}<i> → </i>${inlineMath(`x+${mathFraction("4", "x+1")}=[(x+1)+${mathFraction("4", "x+1")}]−1`)}`)}
              ${renderBasicSlotRouteStep("代入槽位", `${basicSlot("square")}<i>←</i>${inlineMath("x+1")}<i>，</i>${basicSlot("circle")}<i>←</i>${inlineMath(mathFraction("4", "x+1"))}`)}
              ${renderBasicSlotRouteStep("括号内定积", `${inlineMath(`(x+1)·${mathFraction("4", "x+1")}=4`)}<i> → </i>${inlineMath(`(x+1)+${mathFraction("4", "x+1")}≥4`)}<i> → </i>${inlineMath(`x+${mathFraction("4", "x+1")}≥3`)}`)}
              <p class="basic-slot-route-result"><span>验证取等</span><strong>${inlineMath("x+1=2")} 即 ${inlineMath("x=1")} 时取等，最小值为 ${inlineMath("3")}</strong></p>
              <small class="basic-slot-route-lessons">同类：练习 8·5 · 8·8</small>
            </article>
          </div>
        </section>
      </div>` : "";
    const renderFixedProductMatrix = ({
      label,
      title,
      target,
      condition,
      columns,
      rows,
      cells,
      product,
      productLabel = "交叉项定积",
      targetCaption = "目标",
      conditionCaption = "条件",
    }) => `
      <article class="fixed-product-route">
        <header><span>${label}</span><strong>${title}</strong></header>
        <div class="fixed-product-inputs"><p><small>${targetCaption}</small>${target}</p><i aria-hidden="true">×</i><p><small>${conditionCaption}</small>${condition}</p></div>
        <div class="fixed-product-matrix" aria-label="乘法展开表">
          <span></span><b>${columns[0]}</b><b>${columns[1]}</b>
          <b>${rows[0]}</b><span class="is-constant">${cells[0][0]}</span><span class="is-cross">${cells[0][1]}</span>
          <b>${rows[1]}</b><span class="is-cross">${cells[1][0]}</span><span class="is-constant">${cells[1][1]}</span>
        </div>
        <p class="fixed-product-found"><span>${productLabel}</span><strong>${product}</strong></p>
      </article>`;
    const homogeneousRatioTerm = (kind, value) => `<mark class="homogeneous-ratio-term is-${kind}">${value}</mark>`;
    const homogeneousCompletionTerm = (value) => `<mark class="homogeneous-completion-term">${value}</mark>`;
    const renderBasicInequalityHomogenizationVisual = (block) => block?.basicInequalityHomogenizationVisual ? `
      <div class="basic-homogeneous-method">
        <header class="homogeneous-method-intro method-intro">
          <span>核心意义</span>
          <strong>配齐次式的核心，是把目标整式总次数配成 0</strong>
        </header>
        <section class="homogeneous-slot-template method-core" aria-label="原有整式与定值式的次数相加为零，得到只含变量比值的零次齐次式">
          <div class="homogeneous-slot-equation">
            <article class="homogeneous-degree-source is-original">
              <div class="homogeneous-source-expression"><span>原有整式</span><strong>${inlineMath("x+y")}</strong></div>
              <i class="homogeneous-source-arrow" aria-hidden="true"></i>
              <div class="homogeneous-degree-slot" aria-label="m 次式"><sup>m</sup></div>
            </article>
            <b class="homogeneous-slot-operator is-product" aria-hidden="true">·</b>
            <article class="homogeneous-degree-source is-condition">
              <div class="homogeneous-source-expression"><span>乘入定值</span><strong>${inlineMath(`${mathFraction("1", "x")}+${mathFraction("1", "y")}=1`)}</strong></div>
              <i class="homogeneous-source-arrow" aria-hidden="true"></i>
              <div class="homogeneous-degree-slot" aria-label="n 次式"><sup>n</sup></div>
            </article>
            <b class="homogeneous-slot-operator is-equals" aria-hidden="true">＝</b>
            <article class="homogeneous-degree-result">
              <div class="homogeneous-degree-slot" aria-label="0 次式"><sup>0</sup></div>
            </article>
            <i class="homogeneous-output-arrow" aria-hidden="true">→</i>
            <article class="homogeneous-ratio-result">
              <span>0 次式</span>
              <strong>${inlineMath(`${mathFraction("x", "y")}+${mathFraction("y", "x")}+2`)}</strong>
            </article>
            <div class="homogeneous-general-balance">${inlineMath("m+n=0")}</div>
          </div>
          <p class="homogeneous-zero-meaning">
            <strong>0 次齐次式</strong><b>⇔</b>
            <span class="homogeneous-zero-meaning-detail">
              <span>简化为只研究变量之间的比值</span>
              ${homogeneousRatioTerm("first", inlineMath(mathFraction("x", "y")))}
              ${homogeneousRatioTerm("second", inlineMath(mathFraction("y", "x")))}
              <span class="homogeneous-zero-meaning-sep">，</span>
              <span>变量比值乘积是定值</span>
              <mark class="homogeneous-ratio-product">${inlineMath(`${mathFraction("x", "y")}·${mathFraction("y", "x")}=1`)}</mark>
            </span>
          </p>
        </section>
        <section class="homogeneous-method-how method-how basic-slot-how">
          <header><span>HOW</span><strong>先配次数，再展开找定积</strong></header>
          <div class="homogeneous-route-pipeline" aria-label="配齐次式操作步骤">
            <article><span>①</span><strong>配次数</strong><small>m+n=0</small></article>
            <i aria-hidden="true">→</i>
            <article><span>②</span><strong>展开圈出正项</strong><small>两个比值项</small></article>
            <i aria-hidden="true">→</i>
            <article><span>③</span><strong>检查乘积定值</strong><small>定积出现</small></article>
          </div>
          <div class="homogeneous-routes" aria-label="配齐次式的两类方法">
            <article class="homogeneous-route-card is-global">
              ${renderFixedProductMatrix({
                label: "整体配齐",
                title: "目标(+1) × 条件(-1)",
                target: inlineMath("x+4y"),
                condition: inlineMath(`${mathFraction("1", "x")}+${mathFraction("1", "y")}=1`),
                columns: [inlineMath(mathFraction("1", "x")), inlineMath(mathFraction("1", "y"))],
                rows: [inlineMath("x"), inlineMath("4y")],
                cells: [[inlineMath("1"), inlineMath(mathFraction("x", "y"))], [inlineMath(mathFraction("4y", "x")), inlineMath("4")]],
                product: inlineMath(`${mathFraction("x", "y")}·${mathFraction("4y", "x")}=4`),
                productLabel: "比值定积",
                targetCaption: "目标整式",
                conditionCaption: "条件整式",
              })}
              <small class="homogeneous-route-lessons">练习 8-3 · 8-4 · 8-14</small>
            </article>
            <article class="homogeneous-route-card is-local">
              <header><span>局部配齐</span><strong>修补破坏齐次的项</strong></header>
              <p class="homogeneous-local-condition"><span>题设</span><strong>${inlineMath("a+b=2")}</strong></p>
              <div class="homogeneous-local-chain" aria-label="局部配齐变形链">
                <section><small>原式</small><strong>${inlineMath(mathFraction("a²+2b", "ab"))}</strong></section>
                <i aria-hidden="true">→</i>
                <section><small>由 a+b=2 补齐 2b</small><strong>${inlineMath(mathFraction(`a²+${homogeneousCompletionTerm("b(a+b)")}`, "ab"))}</strong></section>
                <i aria-hidden="true">→</i>
                <section class="is-result"><small>约分</small><strong>${inlineMath(`1+${mathFraction("a", "b")}+${mathFraction("b", "a")}`)}</strong></section>
              </div>
              <p class="homogeneous-local-product"><span>比值定积</span><strong>${inlineMath(`${mathFraction("a", "b")}·${mathFraction("b", "a")}=1`)}</strong></p>
              <small class="homogeneous-route-lessons">练习 8-15 · 8-16</small>
            </article>
          </div>
        </section>
      </div>` : "";
    const renderBasicInequalitySymmetryVisual = (block) => block?.basicInequalitySymmetryVisual ? `
      <div class="basic-symmetric-method">
        <header class="symmetric-method-intro method-intro">
          <span>核心意义</span>
          <strong>交换 ${inlineMath("x，y")} 后原式不变，就是对称结构</strong>
        </header>
        <section class="symmetric-swap-test method-core" aria-label="交换变量理解表达式的对称结构">
          <div class="symmetric-memory-flow">
            <div class="symmetric-swap-action"><small>交换变量</small><strong><em>x</em><i>↔</i><em>y</em></strong></div>
            <i aria-hidden="true">↓</i>
            <div class="symmetric-identity-test">
              <article><span>原式</span></article>
              <b aria-label="等于">＝</b>
              <article class="is-swapped"><span>交换后的式子</span></article>
            </div>
            <i aria-hidden="true">↓</i>
            <strong class="symmetric-structure-result">对称结构</strong>
          </div>
          <p class="symmetric-zero-meaning">
            <strong>对称结构</strong><b>⇔</b>
            <span>只需研究和</span>
            <mark class="symmetric-structure-term is-sum">${inlineMath("s=x+y")}</mark>
            <span>与积</span>
            <mark class="symmetric-structure-term is-product">${inlineMath("p=xy")}</mark>
          </p>
        </section>
        <section class="symmetric-why" aria-label="为什么可以用和与积换元">
          <header>
            <span>WHY</span>
            <strong>为什么要找对称结构</strong>
          </header>
          <div class="symmetric-why-path">
            <article class="symmetric-why-stage is-invariants">
              <header><span>①</span><strong>和与积是最基本的对称结构</strong></header>
              <div class="symmetric-invariant-exchange"><small>交换变量</small><strong><em>x</em><i>↔</i><em>y</em></strong></div>
              <div class="symmetric-invariant-cards">
                <section class="is-sum">
                  <small>和不变</small>
                  <strong>${inlineMath("x+y=y+x")}</strong>
                  <mark class="symmetric-structure-term is-sum">${inlineMath("s=x+y")}</mark>
                </section>
                <section class="is-product">
                  <small>积不变</small>
                  <strong>${inlineMath("xy=yx")}</strong>
                  <mark class="symmetric-structure-term is-product">${inlineMath("p=xy")}</mark>
                </section>
              </div>
            </article>
            <i class="symmetric-why-path-arrow" aria-hidden="true">↓</i>
            <article class="symmetric-why-stage is-elimination">
              <header><span>②</span><strong>和与积可以应用基本不等式消元</strong></header>
              <div class="symmetric-sum-product-relation">
                <small>基本不等式的变式</small>
                <strong>${inlineMath("s²−4p=(x−y)²≥0")}</strong>
                <i aria-hidden="true">⇒</i>
                <mark>${inlineMath("s²≥4p")}</mark>
              </div>
              <div class="symmetric-elimination-inputs">
                <section>
                  <small>改写后的题目条件</small>
                  <strong>${inlineMath("…s…p…=…")}</strong>
                </section>
                <b aria-label="加上">＋</b>
                <section class="is-relation">
                  <small>和积关系</small>
                  <strong>${inlineMath("s²≥4p")}</strong>
                </section>
              </div>
              <div class="symmetric-elimination-outcome">
                <strong>消去 ${inlineMath("p")} 或 ${inlineMath("s")}</strong>
                <i aria-hidden="true">→</i>
                <mark>只剩一个变量</mark>
              </div>
            </article>
          </div>
          <p class="symmetric-why-meaning">
            <strong>对称结构</strong><b>→</b>
            <span>和积换元</span><b>→</b>
            <span>基本不等式消元</span>
          </p>
        </section>
        <section class="symmetric-method-how method-how basic-slot-how">
          <header><span>HOW</span><strong>先交换检验，再用和与积改写</strong></header>
          <div class="basic-slot-pipeline" aria-label="找对称结构操作步骤">
            <article><span>①</span><strong>交换检验</strong><small>目标整式、条件整式分别交换</small></article>
            <i aria-hidden="true">→</i>
            <article><span>②</span><strong>和与积换元</strong><small>用 s=x+y，p=xy 改写</small></article>
            <i aria-hidden="true">→</i>
            <article><span>③</span><strong>验证取等</strong><small>取等时 x=y 能否成立</small></article>
          </div>
          <div class="basic-slot-routes" aria-label="找对称结构的两条路径">
            <article class="basic-slot-route-card is-direct">
              <header><span>直接对称</span><strong>目标与条件已对称</strong></header>
              ${renderBasicSlotRouteProblem("练习 8·17", `若 ${inlineMath("x，y")} 满足 ${inlineMath("x²+y²−xy=1")}，求 ${inlineMath("x+y")} 的取值范围。`)}
              ${renderBasicSlotRouteStep("交换检验", `目标 ${inlineMath("x+y")} 不变；条件 ${inlineMath("x²+y²−xy=1")} 不变`)}
              ${renderBasicSlotRouteStep("和与积换元", `${inlineMath("s=x+y")}，${inlineMath("p=xy")}<i> → </i>${inlineMath("s²−3p=1")}<i> → </i>${inlineMath(`p=${mathFraction("s²−1", "3")}`)}`)}
              ${renderBasicSlotRouteStep("基本不等式消元", `${inlineMath("s²≥4p")}<i> → </i>${inlineMath("s²≤4")}`)}
              <p class="basic-slot-route-result"><span>验证取等</span><strong>${inlineMath("s=±2")} 时 ${inlineMath("x=y")} 可取，范围为 ${inlineMath("[-2,2]")}</strong></p>
              <small class="basic-slot-route-lessons">同类：对称结构·变式 · 变式 2</small>
            </article>
            <article class="basic-slot-route-card is-rearranged">
              <header><span>整理后对称</span><strong>先整理，再交换检验</strong></header>
              <p class="symmetric-route-hint"><span>提示</span>暂时不对称？先整理，再校验</p>
              ${renderBasicSlotRouteProblem("对称结构·变式", `若 ${inlineMath("x，y")} 满足 ${inlineMath("x²+4y²−2xy=1")}，求 ${inlineMath(`x/2+y`)} 的取值范围。`)}
              ${renderBasicSlotRouteStep("整理变形", `${inlineMath("u=x/2")}<i> → </i>目标 ${inlineMath("u+y")}，条件 ${inlineMath(`u²+y²−uy=${mathFraction("1", "4")}`)}`)}
              ${renderBasicSlotRouteStep("交换检验", `目标 ${inlineMath("u+y")} 不变；条件交换 ${inlineMath("u，y")} 后不变`)}
              ${renderBasicSlotRouteStep("和与积换元", `${inlineMath("s=u+y")}，${inlineMath("p=uy")}<i> → </i>${inlineMath(`p=${mathFraction("4s²−1", "12")}`)}<i> → </i>${inlineMath("s²≥4p")}<i> → </i>${inlineMath("s²≤1")}`)}
              <p class="basic-slot-route-result"><span>验证取等</span><strong>${inlineMath("s=±1")} 时 ${inlineMath("u=y")}，还原 ${inlineMath("x=±1")}，范围为 ${inlineMath("[-1,1]")}</strong></p>
              <small class="basic-slot-route-lessons">同类：对称结构·变式 2</small>
            </article>
          </div>
        </section>
      </div>` : "";
    const renderBasicInequalityRepeatedVisual = (block) => block?.basicInequalityRepeatedVisual ? `
      <div class="basic-repeated-method">
        <header class="basic-repeated-intro method-intro">
          <span>核心意义</span>
          <strong>缺几条取等关系，就大约要配几轮基本不等式</strong>
        </header>
        <section class="basic-repeated-core method-core" aria-label="判断预计应用基本不等式的次数">
          <div class="basic-repeated-count-formula">
            <article class="is-variable"><small>变量数</small><strong>n</strong></article>
            <i aria-hidden="true">−</i>
            <article class="is-condition"><small>已有取等条件数</small><strong>k</strong></article>
            <i aria-hidden="true">＝</i>
            <article class="is-result"><small>待补取等关系数</small><strong>n−k</strong></article>
          </div>
          <i class="basic-repeated-down" aria-hidden="true">↓</i>
          <strong class="basic-repeated-estimate">预计应用 <em>n−k</em> 次基本不等式</strong>
        </section>
        <section class="basic-repeated-method-how method-how basic-slot-how">
          <header><span>HOW</span><strong>先判次数，再逐轮配对消元</strong></header>
          <div class="basic-slot-pipeline" aria-label="多次应用基本不等式操作步骤">
            <article><span>①</span><strong>判断次数</strong><small>数变量 n、已有条件 k</small></article>
            <i aria-hidden="true">→</i>
            <article><span>②</span><strong>整理配对</strong><small>选正项、应用基本不等式多次消元</small></article>
            <i aria-hidden="true">→</i>
            <article><span>③</span><strong>验证取等</strong><small>联立各轮取等条件</small></article>
          </div>
          <div class="basic-slot-routes" aria-label="多次应用基本不等式的两条路径">
            <article class="basic-slot-route-card is-direct">
              <header><span>直接配对</span><strong>目标已露出可配正项</strong></header>
              ${renderBasicSlotRouteProblem("练习 8·9", `若 ${inlineMath("a&gt;0，b&gt;0")}，求 ${inlineMath(`${mathFraction("1", "a")}+${mathFraction("a", "b²")}+b`)} 的最小值。`)}
              ${renderBasicSlotRouteStep("判断次数", `${inlineMath("n=2")}，${inlineMath("k=0")}<i> → </i>预计应用 ${inlineMath("2")} 次`)}
              ${renderBasicSlotRouteStep("第 1 轮配对", `${inlineMath(`${mathFraction("1", "a")}+${mathFraction("a", "b²")}≥${mathFraction("2", "b")}`)}<i> → </i>消去 ${inlineMath("a")}`)}
              ${renderBasicSlotRouteStep("第 2 轮配对", `${inlineMath(`${mathFraction("2", "b")}+b≥2√2`)}`)}
              <p class="basic-slot-route-result"><span>验证取等</span><strong>${inlineMath("a=b")} 且 ${inlineMath("b=√2")}，最小值为 ${inlineMath("2√2")}</strong></p>
              <small class="basic-slot-route-lessons">同类：练习 8·10</small>
            </article>
            <article class="basic-slot-route-card is-rearranged">
              <header><span>整理后配对</span><strong>先整理，再逐轮消元</strong></header>
              ${renderBasicSlotRouteProblem("多次应用·变式 1", `若 ${inlineMath("a&gt;b&gt;c&gt;0")}，求 ${inlineMath(`2a²+${mathFraction("1", "ab")}+${mathFraction("1", "a(a−b)")}−10ac+25c²`)} 的最小值。`)}
              ${renderBasicSlotRouteStep("整理变形", `${inlineMath(`${mathFraction("1", "ab")}+${mathFraction("1", "a(a−b)")}=${mathFraction("1", "b(a−b)")}`)}`)}
              ${renderBasicSlotRouteStep("判断次数", `${inlineMath("n=3")}，${inlineMath("k=0")}<i> → </i>预计 ${inlineMath("3")} 条取等<small class="basic-repeated-relation-note">（${inlineMath("2")} 次基本不等式 + 平方非负）</small>`)}
              ${renderBasicSlotRouteStep("第 1 轮配对", `${inlineMath(`b+(a−b)=a`)}<i> → </i>${inlineMath(`${mathFraction("1", "b(a−b)")}≥${mathFraction("4", "a²")}`)}<i> → </i>消去 ${inlineMath("b")}`)}
              ${renderBasicSlotRouteStep("配平方后第 2 轮", `${inlineMath(`(a−5c)²+a²+${mathFraction("4", "a²")}`)}<i> → </i>${inlineMath(`a²+${mathFraction("4", "a²")}≥4`)}`)}
              <p class="basic-slot-route-result"><span>验证取等</span><strong>联立 ${inlineMath("b=a−b")}、${inlineMath("a=5c")}、${inlineMath("a=√2")}，最小值为 ${inlineMath("4")}</strong></p>
              <small class="basic-slot-route-lessons">同类：多次应用·变式 2</small>
            </article>
          </div>
        </section>
      </div>` : "";
    const renderBasicInequalitySubstitutionVisual = (block) => block?.basicInequalitySubstitutionVisual ? `
      <div class="basic-substitution-method">
        <header class="substitution-method-intro method-intro">
          <span>核心意义</span>
          <strong>完整分母或根号整体，可令 u 整体换元改写</strong>
        </header>
        <section class="substitution-core-template method-core" aria-label="识别完整分母或根号整体，令 u 换元并同步改写">
          <div class="substitution-trigger-pair">
            <article class="substitution-trigger-example is-denominator">
              <span>完整分母</span>
              <strong class="substitution-structure-display is-fraction">
                <sup>1</sup><i>/</i><i class="substitution-structure-slot is-denominator" aria-label="完整分母"></i>
              </strong>
            </article>
            <b aria-hidden="true">或</b>
            <article class="substitution-trigger-example is-radical">
              <span>根号整体</span>
              <strong class="substitution-structure-display is-radical">
                <i class="substitution-structure-slot is-radical" aria-label="根号整体">
                  <span class="substitution-radical-glyph" aria-hidden="true">√</span>
                  <span class="substitution-radical-body" aria-hidden="true"></span>
                </i>
              </strong>
            </article>
          </div>
          <i class="substitution-core-arrow" aria-hidden="true">↓</i>
          <div class="substitution-core-assign">
            <span>令</span>${inlineMath("u")}<b>＝</b><i class="substitution-empty-slot is-compact" aria-label="放入完整结构的方框"></i>
          </div>
          <p class="substitution-zero-meaning">
            <strong>分母/根式结构</strong><b>⇔</b><span>令 ${inlineMath("u")} 改写条件整式与目标整式</span>
          </p>
        </section>
        <section class="substitution-method-how method-how basic-slot-how">
          <header><span>HOW</span><strong>先换元改写，再观察结构</strong></header>
          <div class="basic-slot-pipeline" aria-label="换元法操作步骤">
            <article><span>①</span><strong>识别结构</strong><small>完整分母 / 根号整体</small></article>
            <i aria-hidden="true">→</i>
            <article><span>②</span><strong>同步改写</strong><small>定义域、条件整式、目标整式一起换</small></article>
            <i aria-hidden="true">→</i>
            <article><span>③</span><strong>验证取等</strong><small>回到定和/对称/齐次后再回代检验</small></article>
          </div>
          <div class="basic-slot-routes" aria-label="换元法的两条路径">
            <article class="basic-slot-route-card is-direct">
              <header><span>完整分母</span><strong>分母整体换元</strong></header>
              ${renderBasicSlotRouteProblem("换元法·例 1", `已知 ${inlineMath("x，y∈ℝ")}，${inlineMath("x+y=2")}，且 ${inlineMath("x&gt;−1，y&gt;−2")}，求 ${inlineMath(`${mathFraction("1", "x+1")}+${mathFraction("1", "y+2")}`)} 的最小值。`)}
              ${renderBasicSlotRouteStep("令 u 换元", `${inlineMath("u=x+1&gt;0")}，${inlineMath("v=y+2&gt;0")}`)}
              ${renderBasicSlotRouteStep("同步改写", `${inlineMath("x+y=2")}<i> → </i>${inlineMath("u+v=5")}；目标 ${inlineMath(`${mathFraction("1", "u")}+${mathFraction("1", "v")}`)}`)}
              ${renderBasicSlotRouteStep("乘入定和配齐次", `${inlineMath(`5\\left(${mathFraction("1", "u")}+${mathFraction("1", "v")}\\right)=2+${mathFraction("u", "v")}+${mathFraction("v", "u")}`)}<i> → </i>${inlineMath(`${mathFraction("1", "u")}+${mathFraction("1", "v")}≥${mathFraction("4", "5")}`)}`)}
              <p class="basic-slot-route-result"><span>验证取等</span><strong>${inlineMath("u=v=5/2")}，还原 ${inlineMath("x=3/2，y=1/2")}，最小值为 ${inlineMath("4/5")}</strong></p>
              <small class="basic-slot-route-lessons">同类：换元法·例 2 · 变式 3–4</small>
            </article>
            <article class="basic-slot-route-card is-rearranged">
              <header><span>根号整体</span><strong>根号整体换元</strong></header>
              ${renderBasicSlotRouteProblem("换元法·变式 5", `正实数 ${inlineMath("x，y")} 满足 ${inlineMath(`x²+${mathFraction("y²", "16")}=1`)}，求 ${inlineMath(`x${mathRadical("2+y²")}`)} 的最大值。`)}
              ${renderBasicSlotRouteStep("令 t 换元", `${inlineMath(`t=${mathRadical("2+y²")}&gt;√2`)}`)}
              ${renderBasicSlotRouteStep("同步改写", `${inlineMath(`(4x)²+t²=18`)}；目标 ${inlineMath("xt")}`)}
              ${renderBasicSlotRouteStep("应用基本不等式", `${inlineMath(`(4x)²+t²≥8xt`)}<i> → </i>${inlineMath(`xt≤${mathFraction("9", "4")}`)}`)}
              <p class="basic-slot-route-result"><span>验证取等</span><strong>${inlineMath("4x=t")}，还原 ${inlineMath("x=3/4，y=√7")}，最大值为 ${inlineMath("9/4")}</strong></p>
            </article>
          </div>
        </section>
      </div>` : "";
    const renderBasicInequalityEliminationVisual = (block) => block?.basicInequalityEliminationVisual ? `
      <div class="basic-elimination-method">
        <header class="elimination-method-intro method-intro">
          <span>核心意义</span>
          <strong>条件整式能表示一个变量时，代入目标整式消去一个变量</strong>
        </header>
        <section class="elimination-core-template method-core" aria-label="由条件整式表示变量并代入目标整式完成消元">
          <article class="elimination-isolate-card">
            <span>由条件整式表示</span>
            <strong class="elimination-isolate-formula">${inlineMath("y")}<b>＝</b><i class="elimination-structure-slot" aria-label="只含 x 的式子"></i></strong>
            <small>只含 ${inlineMath("x")} 的式子</small>
          </article>
          <i class="elimination-core-arrow" aria-hidden="true">↓</i>
          <div class="elimination-target-flow">
            <article class="elimination-target-chip is-before">
              <span>目标整式</span>
              <strong><em>…</em><mark class="elimination-y-mark">${inlineMath("y")}</mark><em>…</em></strong>
            </article>
            <i class="elimination-target-arrow" aria-hidden="true">→</i>
            <article class="elimination-target-chip is-after">
              <span>一元式</span>
              <strong><em>…</em><i class="elimination-structure-slot is-compact" aria-hidden="true"></i><em>…</em></strong>
            </article>
          </div>
          <p class="elimination-zero-meaning">
            <strong>消元</strong><b>⇔</b><span>目标整式降成一元式</span>
          </p>
        </section>
        <section class="elimination-method-how method-how basic-slot-how">
          <header><span>HOW</span><strong>先整理条件整式，再表示代入</strong></header>
          <div class="basic-slot-pipeline" aria-label="条件消元法操作步骤">
            <article><span>①</span><strong>整理条件整式</strong><small>通分、因式分解</small></article>
            <i aria-hidden="true">→</i>
            <article><span>②</span><strong>表示代入</strong><small>用一个变量表示另一个</small></article>
            <i aria-hidden="true">→</i>
            <article><span>③</span><strong>验证取等</strong><small>回代另一变量检验</small></article>
          </div>
          <div class="basic-slot-routes" aria-label="条件消元法的两条路径">
            <article class="basic-slot-route-card is-direct">
              <header><span>整理后消元</span><strong>先整理条件整式，再表示变量</strong></header>
              ${renderBasicSlotRouteProblem("条件消元法·例 1", `若 ${inlineMath("x&gt;0，y&gt;0")}，且 ${inlineMath(`${mathFraction("1", "x+1")}+${mathFraction("1", "x+2y")}=1`)}，求 ${inlineMath("2x+y")} 的最小值。`)}
              ${renderBasicSlotRouteStep("整理条件整式", `${inlineMath(`${mathFraction("1", "x+1")}+${mathFraction("1", "x+2y")}=1`)}<i> → </i>${inlineMath("x(x+2y−1)=1")}`)}
              ${renderBasicSlotRouteStep("表示代入", `${inlineMath(`y=${mathFraction("1", "2")}(1+${mathFraction("1", "x")}-x)`)}<i> → </i>${inlineMath(`2x+y=${mathFraction("1", "2")}(3x+${mathFraction("1", "x")}+1)`)}`)}
              ${renderBasicSlotRouteStep("应用基本不等式", `${inlineMath(`3x+${mathFraction("1", "x")}≥2√3`)}<i> → </i>最小值 ${inlineMath(`√3+${mathFraction("1", "2")}`)}`)}
              <p class="basic-slot-route-result"><span>验证取等</span><strong>${inlineMath("3x=1/x")}，还原 ${inlineMath("x=1/√3，y=1/2+1/√3")}</strong></p>
              <small class="basic-slot-route-lessons">同类：条件消元法·例 2</small>
            </article>
            <article class="basic-slot-route-card is-rearranged">
              <header><span>定和直接消元</span><strong>条件整式已可直接表示变量</strong></header>
              ${renderBasicSlotRouteProblem("条件消元法·例 2", `若 ${inlineMath("a，b∈ℝ⁺")}，且 ${inlineMath("a+b=1")}，求 ${inlineMath(`${mathFraction("2a", "a²+b")}+${mathFraction("b", "a+b²")}`)} 的最大值。`)}
              ${renderBasicSlotRouteStep("表示代入", `${inlineMath("b=1−a")}<i> → </i>目标整式 ${inlineMath(`${mathFraction("a+1", "a²−a+1")}`)}`)}
              ${renderBasicSlotRouteStep("整理倒数", `目标整式 ${inlineMath(`${mathFraction("a+1", "a²−a+1")}&gt;0`)}<i> → </i>倒数 ${inlineMath(`(a+1)+${mathFraction("3", "a+1")}-3`)}`)}
              ${renderBasicSlotRouteStep("应用基本不等式", `${inlineMath(`(a+1)+${mathFraction("3", "a+1")}≥2√3`)}<i> → </i>最大值 ${inlineMath(`${mathFraction("3+2√3", "3")}`)}`)}
              <p class="basic-slot-route-result"><span>验证取等</span><strong>${inlineMath("a+1=3/(a+1)")}，还原 ${inlineMath("a=√3−1，b=2−√3")}</strong></p>
              <small class="basic-slot-route-lessons">同类：条件消元法·例 1</small>
            </article>
          </div>
        </section>
      </div>` : "";
    const renderKnowledgeItems = (blocks) => blocks.map((block) => `
      <article class="senior-learning-knowledge-item${block.table || block.quadraticInequalityTables || block.threadingLineTable || block.rationalThreadingTable || block.absoluteInequalityTable || block.basicInequalityVisual || block.basicInequalityConditions || block.basicInequalitySlotVisual || block.basicInequalityHomogenizationVisual || block.basicInequalitySymmetryVisual || block.basicInequalityRepeatedVisual || block.basicInequalitySubstitutionVisual || block.basicInequalityEliminationVisual ? " has-table" : ""}${block.basicInequalityVisual ? " is-basic-inequality-visual" : ""}${block.basicInequalityConditions ? " is-basic-inequality-conditions" : ""}${block.basicInequalitySlotVisual ? " is-basic-inequality-slot-method" : ""}${block.basicInequalityHomogenizationVisual ? " is-basic-homogeneous-method" : ""}${block.basicInequalitySymmetryVisual ? " is-basic-symmetry-method" : ""}${block.basicInequalityRepeatedVisual ? " is-basic-repeated-method" : ""}${block.basicInequalitySubstitutionVisual ? " is-basic-substitution-method" : ""}${block.basicInequalityEliminationVisual ? " is-basic-elimination-method" : ""}">
        <h4>${escapeHtml(block.title)}</h4>
        ${block.basicInequalityVisual || block.basicInequalityConditions || block.basicInequalitySlotVisual || block.basicInequalityHomogenizationVisual || block.basicInequalitySymmetryVisual || block.basicInequalityRepeatedVisual || block.basicInequalitySubstitutionVisual || block.basicInequalityEliminationVisual ? "" : renderKnowledgeBody(block)}
        ${renderKnowledgeTable(block.table)}
        ${renderQuadraticInequalityTables(block.quadraticInequalityTables)}
        ${renderThreadingLineTable(block.threadingLineTable)}
        ${renderRationalThreadingTable(block.rationalThreadingTable)}
        ${renderAbsoluteInequalityTable(block.absoluteInequalityTable)}
        ${renderBasicInequalityVisual(block)}
        ${renderBasicInequalityConditions(block)}
        ${renderBasicInequalitySlotVisual(block)}
        ${renderBasicInequalityHomogenizationVisual(block)}
        ${renderBasicInequalitySymmetryVisual(block)}
        ${renderBasicInequalityRepeatedVisual(block)}
        ${renderBasicInequalitySubstitutionVisual(block)}
        ${renderBasicInequalityEliminationVisual(block)}
      </article>
    `).join("");
    const renderKnowledgeVisual = (group) => {
      if (group.visual === "venn-intersection") return `
        <figure class="senior-learning-knowledge-visual set-figure">
          <svg viewBox="0 0 480 250" role="img" aria-label="A 与 B 的交集是两个集合重叠的区域">
            <path class="set-figure-shade" d="M240 49A76 76 0 0 1 240 191A76 76 0 0 1 240 49Z"></path>
            <circle class="set-figure-set" cx="213" cy="120" r="76"></circle><circle class="set-figure-set" cx="267" cy="120" r="76"></circle>
            <text x="178" y="205">A</text><text x="285" y="205">B</text>
          </svg><figcaption>阴影表示 A ∩ B：同时属于 A 和 B 的元素。</figcaption>
        </figure>`;
      if (group.visual === "venn-union") return `
        <figure class="senior-learning-knowledge-visual set-figure">
          <svg viewBox="0 0 480 250" role="img" aria-label="A 与 B 的并集是两个集合覆盖的全部区域">
            <circle class="set-figure-shade" cx="213" cy="120" r="76"></circle><circle class="set-figure-shade" cx="267" cy="120" r="76"></circle>
            <circle class="set-figure-set" cx="213" cy="120" r="76"></circle><circle class="set-figure-set" cx="267" cy="120" r="76"></circle>
            <text x="178" y="205">A</text><text x="285" y="205">B</text>
          </svg><figcaption>阴影表示 A ∪ B：属于 A 或属于 B 的元素。</figcaption>
        </figure>`;
      if (group.visual === "venn-complement") return `
        <figure class="senior-learning-knowledge-visual set-figure">
          <svg viewBox="0 0 480 250" role="img" aria-label="集合 A 相对于全集 U 的补集是 A 外部的区域">
            <defs><mask id="learning-complement-a"><rect width="480" height="250" fill="white"></rect><circle cx="240" cy="122" r="76" fill="black"></circle></mask></defs>
            <rect class="set-figure-universe" x="34" y="22" width="412" height="202" rx="4"></rect>
            <rect class="set-figure-shade" x="34" y="22" width="412" height="202" mask="url(#learning-complement-a)"></rect>
            <circle class="set-figure-set" cx="240" cy="122" r="76"></circle>
            <text x="234" y="128">A</text><text x="414" y="48">U</text>
            <text x="82" y="76">C<tspan dy="5" font-size="13">U</tspan><tspan dy="-5" font-size="18">A</tspan></text>
          </svg><figcaption>阴影表示 C<sub>U</sub>A：全集 U 中不属于 A 的元素。</figcaption>
        </figure>`;
      if (group.visual === "venn-subset") return `
        <figure class="senior-learning-knowledge-visual set-figure is-subset">
          <svg viewBox="0 0 480 250" role="img" aria-label="集合 A 包含在集合 B 中">
            <ellipse class="set-figure-set" cx="240" cy="125" rx="178" ry="94"></ellipse>
            <ellipse class="set-figure-set" cx="265" cy="125" rx="82" ry="52"></ellipse>
            <text x="100" y="126">B</text>
            <text x="258" y="132">A</text>
          </svg>
          <figcaption>若 A ⊆ B，Venn 图中集合 A 位于集合 B 的内部。</figcaption>
        </figure>
      `;
      if (group.visual === "venn-classification") return `
        <figure class="senior-learning-knowledge-visual set-figure is-classification">
          <svg viewBox="0 0 600 330" role="img" aria-label="Venn 图表示四边形的简单分类">
            <rect class="set-figure-universe" x="34" y="24" width="532" height="270" rx="4"></rect>
            <ellipse class="set-figure-set" cx="300" cy="150" rx="190" ry="112"></ellipse>
            <ellipse class="set-figure-set" cx="250" cy="142" rx="92" ry="72"></ellipse>
            <ellipse class="set-figure-set" cx="350" cy="142" rx="92" ry="72"></ellipse>
            <text x="48" y="278">四边形</text>
            <text x="214" y="251">平行四边形</text>
            <text x="190" y="148">菱形</text>
            <text x="378" y="148">矩形</text>
            <text x="270" y="148">正方形</text>
          </svg>
          <figcaption>Venn 图表示四边形的简单分类</figcaption>
        </figure>
      `;
      return "";
    };
    const methodKnowledgeGroups = (module.knowledgeGroups || []).filter((group) => group.section === "method");
    const selectedMethodGroup = methodKnowledgeGroups.find((group) => group.id === state.method) || null;
    const isMethodCollection = methodKnowledgeGroups.length > 0;
    const visibleExamples = selectedMethodGroup
      ? module.examples.filter((example) => example.group === (selectedMethodGroup.exampleGroup || selectedMethodGroup.title))
      : module.examples;
    const groupedExamples = groupLearningExamples(visibleExamples);
    const examplesForCategory = (category) => module.examples.filter(
      (example) => learningExampleCategory(example) === category,
    );
    const examplesForKnowledgeGroup = (group) => {
      if (group.showExercises === false) return [];
      const expectedGroup = group.exampleGroup || group.title;
      const exactGroupExamples = module.examples.filter((example) => example.group === expectedGroup);
      return exactGroupExamples.length ? exactGroupExamples : examplesForCategory(group.category);
    };
    const exerciseHrefForKnowledgeGroup = (group) => {
      const firstExample = examplesForKnowledgeGroup(group)[0];
      return firstExample
        ? `#exercises-${learningGroupSlug(firstExample.group)}`
        : "#worked-examples-heading";
    };
    const showExercisesSection = !isMethodCollection || selectedMethodGroup;
    const knowledgeBlocksForGroup = (group) => {
      const explicitlyGrouped = module.knowledgeBlocks.filter((block) => block.groupId === group.id);
      return explicitlyGrouped.length
        ? explicitlyGrouped
        : module.knowledgeBlocks.filter((block) => !block.groupId && block.category === group.category);
    };
    const knowledgeAnchorId = (group) => `knowledge-${group.id || group.category}`;
    const knowledgeGroupForExample = (example) => (
      (module.knowledgeGroups || []).find((group) => (group.exampleGroup || group.title) === example.group)
      || (module.knowledgeGroups || []).find((group) => group.category === learningExampleCategory(example))
    );
    const renderKnowledgeGroup = (group) => `
      <article id="${escapeHtml(knowledgeAnchorId(group))}" class="senior-learning-knowledge-group is-${escapeHtml(group.category)} has-${knowledgeBlocksForGroup(group).length}-items${knowledgeBlocksForGroup(group).some((block) => block.table || block.quadraticInequalityTables || block.threadingLineTable || block.rationalThreadingTable || block.absoluteInequalityTable || block.basicInequalityVisual || block.basicInequalityConditions || block.basicInequalitySlotVisual || block.basicInequalityHomogenizationVisual || block.basicInequalitySymmetryVisual || block.basicInequalityRepeatedVisual || block.basicInequalitySubstitutionVisual || block.basicInequalityEliminationVisual) ? " has-table" : ""}">
        <div class="senior-learning-knowledge-group-heading">
          <span>${escapeHtml(group.number)}</span>
          <div>
            <p>${escapeHtml(group.eyebrow)}</p>
            <h3>${escapeHtml(group.title)}</h3>
            ${examplesForKnowledgeGroup(group).length ? `<a class="senior-learning-exercise-anchor" href="${escapeHtml(exerciseHrefForKnowledgeGroup(group))}">
              <span>对应练习</span>
              <strong>${group.lessonCount || examplesForKnowledgeGroup(group).length} 题</strong>
              <span aria-hidden="true">↓</span>
            </a>` : ""}
          </div>
        </div>
        <div class="senior-learning-knowledge-items">
          ${renderKnowledgeItems(knowledgeBlocksForGroup(group))}
        </div>
        ${renderKnowledgeVisual(group)}
      </article>`;
    const coreKnowledgeGroups = (module.knowledgeGroups || []).filter((group) => group.section !== "method");
    const renderMethodNavigation = () => methodKnowledgeGroups.length ? `
      <nav class="senior-learning-method-navigation" aria-label="基本不等式方法导航">
        <a href="${escapeHtml(learningMethodHref(topic, module.id, "all"))}" data-learning-method="all" class="${selectedMethodGroup ? "" : "is-active"}">方法总览</a>
        ${methodKnowledgeGroups.map((group) => `
          <a href="${escapeHtml(learningMethodGuideHref(topic, module.id, group.id))}" data-learning-method="${escapeHtml(group.id)}" class="${selectedMethodGroup?.id === group.id ? "is-active" : ""}">${escapeHtml(group.title)}</a>
        `).join("")}
      </nav>` : "";
    const showMethodOverview = isMethodCollection && !selectedMethodGroup;
    const groupsToRender = selectedMethodGroup ? [selectedMethodGroup] : methodKnowledgeGroups;
    return `
      <article class="senior-learning-topic">
        <header class="senior-learning-module-hero">
          <p class="senior-learning-kicker">${selectedMethodGroup ? "解题方法" : "知识模块"}</p>
          <h2>${escapeHtml(selectedMethodGroup?.title || module.label)}</h2>
          <p>${escapeHtml(selectedMethodGroup
            ? (knowledgeBlocksForGroup(selectedMethodGroup)[0]?.body?.[0] || module.description)
            : module.description)}</p>
        </header>
        ${renderMethodNavigation()}
        ${!selectedMethodGroup ? `<section class="senior-learning-section" aria-labelledby="core-knowledge-heading">
          <div class="senior-learning-section-heading">
            <p>CORE KNOWLEDGE</p>
            <h2 id="core-knowledge-heading">核心知识</h2>
          </div>
          <div class="senior-learning-knowledge-groups">
            ${coreKnowledgeGroups.map(renderKnowledgeGroup).join("")}
          </div>
        </section>` : ""}
        ${showMethodOverview ? `<section class="senior-learning-section senior-learning-method-index-section" aria-labelledby="solving-methods-heading">
          <div class="senior-learning-section-heading">
            <p>METHODS</p>
            <h2 id="solving-methods-heading">选择方法的核心是观察结构</h2>
          </div>
          ${renderBasicInequalityMethodRoute(topic, module.id, methodKnowledgeGroups)}
        </section>` : selectedMethodGroup ? `<section class="senior-learning-section senior-learning-method-detail" aria-labelledby="selected-method-heading">
          <div class="senior-learning-section-heading">
            <p>METHOD GUIDE</p>
            <h2 id="selected-method-heading">识别方法与解题步骤</h2>
          </div>
          <div class="senior-learning-knowledge-groups">
            ${groupsToRender.map(renderKnowledgeGroup).join("")}
          </div>
        </section>` : methodKnowledgeGroups.length ? `<section class="senior-learning-section senior-learning-methods-section" aria-labelledby="solving-methods-heading">
          <div class="senior-learning-section-heading"><p>METHODS</p><h2 id="solving-methods-heading">解题方法</h2></div>
          <div class="senior-learning-knowledge-groups">${groupsToRender.map(renderKnowledgeGroup).join("")}</div>
        </section>` : ""}
        ${showExercisesSection ? `<section class="senior-learning-section" aria-labelledby="worked-examples-heading">
          <div class="senior-learning-section-heading">
            <p>EXERCISES</p>
            <h2 id="worked-examples-heading">${selectedMethodGroup ? `${escapeHtml(selectedMethodGroup.title)} · 对应题目` : "例题精讲"}</h2>
          </div>
          <div class="senior-learning-exercise-sheet">
            ${groupedExamples.map(([group, entries]) => `
              <section id="exercises-${escapeHtml(learningGroupSlug(group))}" class="senior-learning-example-group" aria-labelledby="learning-example-group-${escapeHtml(group)}">
                <h3 id="learning-example-group-${escapeHtml(group)}">${escapeHtml(group)}</h3>
                <div class="senior-learning-example-list">
                  ${entries.map(({ example, index }) => renderInteractiveLearningExample(example, index)).join("")}
                </div>
                <a class="senior-learning-return-anchor" href="#${escapeHtml(knowledgeAnchorId(knowledgeGroupForExample(entries[0].example) || { category: learningExampleCategory(entries[0].example) }))}">↑ 返回对应知识点</a>
              </section>
            `).join("")}
          </div>
        </section>` : ""}
        ${!selectedMethodGroup ? `<section class="senior-learning-summary">
          <p>归纳总结</p>
          <div>${module.summaryHtml}</div>
        </section>` : `<a class="senior-learning-method-back" href="${escapeHtml(learningMethodHref(topic, module.id, "all"))}" data-learning-method="all">← 返回基本不等式方法总览</a>`}
      </article>
    `;
  }

  function renderAssessmentModule(topic, module) {
    return `
      <article class="senior-learning-topic">
        <header class="senior-learning-module-hero is-assessment">
          <p class="senior-learning-kicker">综合检测</p>
          <h2>${escapeHtml(module.label)}</h2>
          <p>${escapeHtml(module.description)}</p>
        </header>
        <div class="senior-learning-example-list is-assessment">
          ${module.items.map((item) => {
            if (item.status === "pending") {
              return `
                <article class="senior-learning-example-card is-pending">
                  <div class="senior-learning-example-heading">
                    <div>
                      <p>第 ${item.number} 题</p>
                      <h3>${escapeHtml(item.title)}</h3>
                    </div>
                    <span class="senior-learning-question-number">${item.number}</span>
                  </div>
                  <p class="senior-learning-pending-note">${escapeHtml(item.note)}</p>
                </article>
              `;
            }
            return renderInteractiveLearningExample(item, item.number - 1);
          }).join("")}
        </div>
      </article>
    `;
  }

  function renderLearningTopic(topic) {
    const module = topic.modules.find((item) => item.id === state.module);
    if (state.module === "overview" || !module) {
      elements.learning.innerHTML = renderLearningOverview(topic);
      return;
    }
    elements.learning.innerHTML = module.type === "assessment"
      ? renderAssessmentModule(topic, module)
      : renderKnowledgeModule(topic, module);
  }

  function renderEmpty() {
    return `
      <div class="senior-library-empty">
        <h2>这一章节正在整理</h2>
        <p>新的可视化题目会在完成校验后出现在这里。</p>
      </div>
    `;
  }

  function renderPagination(pageInfo) {
    if (pageInfo.pageCount <= 1) {
      elements.pagination.hidden = true;
      elements.pagination.innerHTML = "";
      return;
    }
    elements.pagination.hidden = false;
    const pages = Array.from({ length: pageInfo.pageCount }, (_, index) => index + 1);
    elements.pagination.innerHTML = [
      `<button class="senior-library-page-button" type="button" data-page="${pageInfo.page - 1}" ${pageInfo.page === 1 ? "disabled" : ""} aria-label="上一页">←</button>`,
      ...pages.map((page) => (
        `<button class="senior-library-page-button${page === pageInfo.page ? " is-active" : ""}" type="button" data-page="${page}" ${page === pageInfo.page ? 'aria-current="page"' : ""}>${page}</button>`
      )),
      `<button class="senior-library-page-button" type="button" data-page="${pageInfo.page + 1}" ${pageInfo.page === pageInfo.pageCount ? "disabled" : ""} aria-label="下一页">→</button>`,
    ].join("");
  }

  function replaceCurrentUrl() {
    const url = new URL(window.location.href);
    url.search = model.stateToSearch(state);
    window.history.replaceState({}, "", url);
  }

  function render() {
    state = model.normalizeState(catalog, state);
    if (state.chapter !== "all") {
      expandedChapters.add(state.chapter);
    }
    const worksheetCollection = model.collectionForState(catalog, state);
    const learningTopic = model.learningTopicForState(catalog, state);
    renderChapters();

    if (learningTopic) {
      const activeModule = learningTopic.modules.find((item) => item.id === state.module);
      const activeMethod = activeModule?.knowledgeGroups?.find((group) => group.id === state.method);
      elements.title.textContent = activeMethod?.title || (state.module === "overview"
        ? learningTopic.title
        : activeModule?.label || learningTopic.title);
      elements.count.textContent = activeMethod
        ? `${activeMethod.lessonCount || activeModule.examples.filter((example) => example.group === (activeMethod.exampleGroup || activeMethod.title)).length} 道例题`
        : activeModule?.knowledgeGroups?.some((group) => group.section === "method")
          ? `${activeModule.knowledgeGroups.filter((group) => group.section === "method").length} 种方法`
        : state.module === "overview"
        ? "知识专题"
        : activeModule?.status === "pending"
          ? "待补充"
          : activeModule?.type === "assessment"
            ? `${activeModule.items.length} 题`
            : `${activeModule.examples.length} 道例题`;
      elements.filters.hidden = true;
      elements.sectionTabs.hidden = true;
      elements.sectionTabs.innerHTML = "";
      elements.collectionTabs.hidden = true;
      elements.collectionTabs.innerHTML = "";
      elements.grid.hidden = true;
      elements.grid.innerHTML = "";
      elements.worksheet.hidden = true;
      elements.worksheet.innerHTML = "";
      elements.pagination.hidden = true;
      elements.pagination.innerHTML = "";
      elements.learning.hidden = false;
      renderLearningTopic(learningTopic);
      return;
    }

    if (worksheetCollection) {
      elements.title.textContent = worksheetCollection.title;
      elements.count.textContent = `共 ${model.collectionProblemCount(worksheetCollection)} 题`;
      elements.filters.hidden = true;
      elements.sectionTabs.hidden = true;
      elements.sectionTabs.innerHTML = "";
      renderCollectionTabs(worksheetCollection);
      elements.grid.hidden = true;
      elements.grid.innerHTML = "";
      elements.pagination.hidden = true;
      elements.pagination.innerHTML = "";
      elements.worksheet.hidden = false;
      elements.learning.hidden = true;
      elements.learning.innerHTML = "";
      renderWorksheet(worksheetCollection);
      return;
    }

    const results = model.filterProblems(catalog, state);
    const pageInfo = model.paginate(results, state.page);
    if (pageInfo.page !== state.page) {
      state = { ...state, page: pageInfo.page };
      replaceCurrentUrl();
    }

    const chapter = getChapter(state.chapter);
    const overviewCollections = (catalog.collections || []).filter((collection) => (
      state.section === "all"
      && state.difficulty === "all"
      && state.source === "all"
      && (state.chapter === "all" || collection.chapterId === state.chapter)
    ));
    const overviewTopics = (catalog.learningTopics || []).filter((topic) => (
      state.section === "all"
      && state.difficulty === "all"
      && state.source === "all"
      && (state.chapter === "all" || topic.chapterId === state.chapter)
    ));
    const collectionProblemCount = overviewCollections.reduce(
      (total, collection) => total + model.collectionProblemCount(collection),
      0,
    );
    const learningProblemCount = overviewTopics.reduce(
      (total, topic) => total + topicProblemCount(topic),
      0,
    );
    elements.title.textContent = chapter?.label || "全部题目";
    elements.count.textContent = `${results.length + collectionProblemCount + learningProblemCount} 道`;
    elements.filters.hidden = false;
    elements.collectionTabs.hidden = true;
    elements.collectionTabs.innerHTML = "";
    elements.difficulty.value = state.difficulty;
    elements.sort.value = state.sort;
    renderSourceOptions();
    renderSections();
    elements.worksheet.hidden = true;
    elements.worksheet.innerHTML = "";
    elements.learning.hidden = true;
    elements.learning.innerHTML = "";
    elements.grid.hidden = false;
    const overviewMarkup = [
      ...overviewTopics.map(renderLearningTopicEntry),
      ...overviewCollections.map(renderCollectionEntry),
    ];
    const problemMarkup = pageInfo.items.map(renderProblem);
    elements.grid.innerHTML = overviewMarkup.length || problemMarkup.length
      ? [...overviewMarkup, ...problemMarkup].join("")
      : renderEmpty();
    renderPagination(pageInfo);
  }

  function answerPreviewMarkup(rawValue) {
    const escaped = escapeHtml(String(rawValue ?? "").trim());
    if (!escaped) return "";
    return escaped.replace(/(-?\d+)\/(-?\d+)/g, (
      _match,
      numerator,
      denominator,
    ) => `
      <span class="math-fraction">
        <span class="math-numerator">${numerator}</span>
        <span class="math-denominator">${denominator}</span>
      </span>
    `);
  }

  function setAnswerFeedback(root, message, status) {
    const feedback = root.querySelector("[data-answer-feedback]");
    feedback.textContent = message;
    root.classList.remove("is-correct", "is-incorrect");
    root.classList.add(status === "correct" ? "is-correct" : "is-incorrect");
  }

  function evaluateLearningAnswer(root) {
    const answerType = root.dataset.answerType;
    if (answerType === "single-choice") {
      const selected = root.querySelector("[data-answer-choice].is-selected");
      if (!selected) {
        setAnswerFeedback(root, "请先选择一个答案。", "incorrect");
        return;
      }
      const correct = selected.dataset.answerChoice === root.dataset.expected;
      setAnswerFeedback(
        root,
        correct ? "回答正确。你可以继续查看解析，确认判断依据。" : "暂时不对。可以检查对象的归属标准是否明确。",
        correct ? "correct" : "incorrect",
      );
      return;
    }

    if (answerType === "multipart-choice") {
      const rows = [...root.querySelectorAll("[data-answer-part]")];
      const selected = rows.map((row) => row.querySelector("[data-part-choice].is-selected"));
      const missing = selected
        .map((choice, index) => (choice ? null : index + 1))
        .filter(Boolean);
      if (missing.length > 0) {
        rows.forEach((row, index) => {
          row.classList.toggle("is-incomplete", missing.includes(index + 1));
          row.classList.remove("is-correct", "is-incorrect");
          row.querySelector("[data-answer-part-feedback]").textContent = "";
        });
        setAnswerFeedback(root, `还有（${missing.join("）（")}）未选择。`, "incorrect");
        return;
      }
      let expected = [];
      try {
        expected = JSON.parse(root.dataset.expectedJson || "[]");
      } catch {
        expected = [];
      }
      const results = selected.map((choice, index) => choice.dataset.partChoice === expected[index]);
      rows.forEach((row, index) => {
        row.classList.remove("is-incomplete");
        row.classList.toggle("is-correct", results[index]);
        row.classList.toggle("is-incorrect", !results[index]);
        row.querySelector("[data-answer-part-feedback]").textContent = results[index] ? "正确" : "需要修改";
      });
      const correctCount = results.filter(Boolean).length;
      const allCorrect = correctCount === results.length;
      setAnswerFeedback(
        root,
        allCorrect ? `${results.length} 个判断全部正确。` : `已答对 ${correctCount} 项，请修改标记出的判断。`,
        allCorrect ? "correct" : "incorrect",
      );
      return;
    }

    const fields = [...root.querySelectorAll("[data-answer-field]")];
    const rawValues = fields.map((field) => field.value.trim());
    if (
      answerType !== "relation-sequence"
      && root.dataset.answerLayout !== "per-part"
      && rawValues.some((value) => value === "")
    ) {
      setAnswerFeedback(root, "请填写完整后再提交。", "incorrect");
      return;
    }

    if (answerType === "variable-domain" || answerType === "finite-set-values") {
      const values = answerType === "variable-domain"
        ? parseVariableDomainExclusions(rawValues[0], root.dataset.answerVariable || "x")
        : parseFiniteSetValues(rawValues[0]);
      if (!values) {
        setAnswerFeedback(
          root,
          answerType === "variable-domain"
            ? "暂时无法识别这个条件。可以使用 x、≠、∈、ℝ 和集合符号书写。"
            : "暂时无法识别这个集合。请用逗号分隔元素，必要时加上大括号。",
          "incorrect",
        );
        return;
      }
      const uniqueValues = new Set(values);
      if (uniqueValues.size !== values.length) {
        setAnswerFeedback(root, "表达式中出现了重复的值，请检查后再提交。", "incorrect");
        return;
      }
      const expected = root.dataset.expected.split("|").map(canonicalRational);
      const correct = values.length === expected.length
        && expected.every((value) => uniqueValues.has(value));
      setAnswerFeedback(
        root,
        correct
          ? "回答正确。这个表达式与标准答案表示同一个结果。"
          : answerType === "variable-domain"
            ? "答案尚不完整或包含多余限制，请重新检查哪些参数会使元素相同。"
            : "答案尚不完整或包含多余元素，请重新检查各种参数情形。",
        correct ? "correct" : "incorrect",
      );
      return;
    }

    if (answerType === "relation-sequence") {
      const slots = relationSlotsFor(root);
      const emptyCount = slots.filter((slot) => !slot.dataset.relationValue).length;
      if (emptyCount > 0) {
        setAnswerFeedback(root, `还有 ${emptyCount} 个空没有填写。`, "incorrect");
        return;
      }
      const values = parseRelationSequence(rawValues[0]);
      if (!values) {
        setAnswerFeedback(
          root,
          "暂时无法识别这些关系符号。请使用题目提供的符号，符号之间可用逗号分隔。",
          "incorrect",
        );
        return;
      }
      const expected = root.dataset.expected.split("|");
      const correct = values.length === expected.length
        && expected.every((value, index) => values[index] === value);
      setAnswerFeedback(
        root,
        correct
          ? `回答正确。${expected.length} 个关系符号及顺序都正确。`
          : "暂时不对。请按题号顺序重新检查每个对象之间的关系。",
        correct ? "correct" : "incorrect",
      );
      return;
    }

    if (answerType === "exact-expression" || answerType === "multipart-exact") {
      if (answerType === "multipart-exact") {
        let expectedParts = [];
        try {
          expectedParts = JSON.parse(root.dataset.expectedJson || "[]")
            .map((aliases) => aliases.map(normalizeExactMathExpression));
        } catch {
          expectedParts = [];
        }
        if (root.dataset.answerLayout === "per-part") {
          const missing = rawValues
            .map((value, index) => (value ? null : index + 1))
            .filter(Boolean);
          if (missing.length > 0) {
            root.querySelectorAll("[data-answer-part]").forEach((row, index) => {
              row.classList.toggle("is-incomplete", missing.includes(index + 1));
              row.classList.remove("is-correct", "is-incorrect");
              row.querySelector("[data-answer-part-feedback]").textContent = "";
            });
            setAnswerFeedback(root, `还有（${missing.join("）（")}）未作答。`, "incorrect");
            return;
          }
          const partResults = rawValues.map((value, index) => (
            expectedParts[index]?.includes(normalizeExactMathExpression(value)) || false
          ));
          root.querySelectorAll("[data-answer-part]").forEach((row, index) => {
            row.classList.remove("is-incomplete");
            row.classList.toggle("is-correct", partResults[index]);
            row.classList.toggle("is-incorrect", !partResults[index]);
            row.querySelector("[data-answer-part-feedback]").textContent = partResults[index]
              ? "正确"
              : "需要修改";
          });
          const correctCount = partResults.filter(Boolean).length;
          const allCorrect = correctCount === partResults.length;
          setAnswerFeedback(
            root,
            allCorrect ? `${partResults.length} 个小题全部回答正确。` : `已答对 ${correctCount} 项，请修改标记出的答案。`,
            allCorrect ? "correct" : "incorrect",
          );
          return;
        }
        const actual = normalizeExactMathExpression(rawValues[0]);
        const actualParts = actual.split(";");
        const correct = actualParts.length === expectedParts.length
          && actualParts.every((value, index) => expectedParts[index].includes(value));
        setAnswerFeedback(
          root,
          correct ? "回答正确。" : "暂时不对。请按小题顺序用分号分隔各个答案。",
          correct ? "correct" : "incorrect",
        );
        return;
      }
      const actual = normalizeExactMathExpression(rawValues[0]);
      const expected = root.dataset.expected
        .split("|")
        .map(normalizeExactMathExpression);
      const correct = expected.includes(actual);
      setAnswerFeedback(
        root,
        correct ? "回答正确。" : "暂时不对。请检查集合符号、元素顺序或端点是否正确。",
        correct ? "correct" : "incorrect",
      );
      return;
    }

    const values = rawValues.map(canonicalRational);
    if (values.some((value) => value == null)) {
      setAnswerFeedback(root, "有一个值无法识别。分数可以写成 1/4 这样的形式。", "incorrect");
      return;
    }

    if (answerType === "integer") {
      const correct = values[0] === canonicalRational(root.dataset.expected);
      setAnswerFeedback(
        root,
        correct ? "回答正确。" : "暂时不对。注意先化简相同的对象，再计算不同元素的个数。",
        correct ? "correct" : "incorrect",
      );
      return;
    }

  }

  function insertMathKey(input, key, cursorBack = 0) {
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? input.value.length;
    if (key === "clear") {
      input.value = "";
    } else if (key === "backspace") {
      if (start !== end) {
        input.setRangeText("", start, end, "end");
      } else if (start > 0) {
        input.setRangeText("", start - 1, start, "end");
      }
    } else {
      input.setRangeText(key, start, end, "end");
      if (cursorBack > 0) {
        const cursor = Math.max(0, input.selectionStart - cursorBack);
        input.setSelectionRange(cursor, cursor);
      }
    }
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.focus();
  }

  function relationSlotsFor(element) {
    return [...(element.closest(".senior-learning-example")
      ?.querySelectorAll("[data-relation-slot]") || [])];
  }

  function activateRelationSlot(slot) {
    const article = slot.closest(".senior-learning-example");
    const slots = relationSlotsFor(slot);
    slots.forEach((item) => item.classList.toggle("is-active", item === slot));
    const status = article?.querySelector("[data-relation-status]");
    if (status) status.textContent = `正在填写第 ${Number(slot.dataset.relationIndex) + 1} 空`;
    slot.focus();
  }

  function syncRelationAnswer(article) {
    const slots = [...article.querySelectorAll("[data-relation-slot]")];
    const root = article.querySelector('[data-answer-type="relation-sequence"]');
    const field = root?.querySelector("[data-answer-field]");
    if (field) field.value = slots.map((slot) => slot.dataset.relationValue || "").join(",");
    root?.classList.remove("is-correct", "is-incorrect");
    const feedback = root?.querySelector("[data-answer-feedback]");
    if (feedback) feedback.textContent = "";
  }

  function fillRelationSlot(slot, relation) {
    const article = slot.closest(".senior-learning-example");
    const slots = relationSlotsFor(slot);
    const currentIndex = slots.indexOf(slot);
    slot.dataset.relationValue = relation;
    slot.innerHTML = `<span aria-hidden="true">${escapeHtml(relation)}</span>`;
    slot.setAttribute(
      "aria-label",
      `第 ${currentIndex + 1} 空，已填${relation}`,
    );
    syncRelationAnswer(article);
    const next = slots.slice(currentIndex + 1).find((item) => !item.dataset.relationValue)
      || slots.find((item) => !item.dataset.relationValue);
    if (next) {
      activateRelationSlot(next);
    } else {
      slots.forEach((item) => item.classList.remove("is-active"));
      const status = article.querySelector("[data-relation-status]");
      if (status) status.textContent = `${slots.length} 个空已填写，可逐空点击修改`;
      slot.focus();
    }
  }

  function setState(patch, options = {}) {
    state = model.normalizeState(catalog, { ...state, ...patch });
    const url = new URL(window.location.href);
    url.search = model.stateToSearch(state);
    const method = options.replace ? "replaceState" : "pushState";
    window.history[method]({}, "", url);
    render();
  }

  document.addEventListener("click", (event) => {
    const hintButton = event.target.closest("[data-hint-toggle]");
    const answerChoice = event.target.closest("[data-answer-choice]");
    const partChoice = event.target.closest("[data-part-choice]");
    const answerSubmit = event.target.closest("[data-answer-submit]");
    const mathKey = event.target.closest("[data-math-key]");
    const symbolToggle = event.target.closest("[data-symbol-toggle]");
    const relationSlot = event.target.closest("[data-relation-slot]");
    const relationKey = event.target.closest("[data-relation-key]");
    if (!hintButton) {
      elements.learning.querySelectorAll(".senior-learning-hint.is-open").forEach((hint) => {
        hint.classList.remove("is-open");
        hint.querySelector("[data-hint-toggle]")?.setAttribute("aria-expanded", "false");
      });
    }
    if (!symbolToggle && !mathKey) {
      elements.learning.querySelectorAll(".senior-learning-math-keyboard.is-visible").forEach((keyboard) => {
        if (keyboard.closest("[data-answer-root]")?.contains(event.target)) return;
        keyboard.classList.remove("is-visible");
        keyboard.closest("[data-answer-root]")
          ?.querySelector("[data-symbol-toggle]")
          ?.setAttribute("aria-expanded", "false");
      });
    }
    if (hintButton) {
      const expanded = hintButton.getAttribute("aria-expanded") === "true";
      hintButton.setAttribute("aria-expanded", String(!expanded));
      hintButton.closest(".senior-learning-hint")?.classList.toggle("is-open", !expanded);
      return;
    }
    if (partChoice) {
      const row = partChoice.closest("[data-answer-part]");
      const root = partChoice.closest("[data-answer-root]");
      row.querySelectorAll("[data-part-choice]").forEach((choice) => {
        const selected = choice === partChoice;
        choice.classList.toggle("is-selected", selected);
        choice.setAttribute("aria-pressed", String(selected));
      });
      row.classList.remove("is-incomplete", "is-correct", "is-incorrect");
      row.querySelector("[data-answer-part-feedback]").textContent = "";
      root.classList.remove("is-correct", "is-incorrect");
      root.querySelector("[data-answer-feedback]").textContent = "";
      return;
    }
    if (answerChoice) {
      const root = answerChoice.closest("[data-answer-root]");
      root.querySelectorAll("[data-answer-choice]").forEach((choice) => {
        const selected = choice === answerChoice;
        choice.classList.toggle("is-selected", selected);
        choice.setAttribute("aria-pressed", String(selected));
      });
      root.classList.remove("is-correct", "is-incorrect");
      root.querySelector("[data-answer-feedback]").textContent = "";
      return;
    }
    if (relationSlot) {
      activateRelationSlot(relationSlot);
      return;
    }
    if (relationKey) {
      const slots = relationSlotsFor(relationKey);
      const activeSlot = slots.find((slot) => slot.classList.contains("is-active"))
        || slots.find((slot) => !slot.dataset.relationValue);
      if (activeSlot) fillRelationSlot(activeSlot, relationKey.dataset.relationKey);
      return;
    }
    if (symbolToggle) {
      const root = symbolToggle.closest("[data-answer-root]");
      const keyboard = root.querySelector(".senior-learning-math-keyboard");
      const expanded = symbolToggle.getAttribute("aria-expanded") === "true";
      symbolToggle.setAttribute("aria-expanded", String(!expanded));
      keyboard?.classList.toggle("is-visible", !expanded);
      if (!expanded) {
        (root.querySelector("[data-answer-field].is-active")
          || root.querySelector("[data-answer-field]"))?.focus();
      }
      return;
    }
    if (answerSubmit) {
      const root = answerSubmit.closest("[data-answer-root]");
      root.querySelector(".senior-learning-math-keyboard")?.classList.remove("is-visible");
      root.querySelector("[data-symbol-toggle]")?.setAttribute("aria-expanded", "false");
      evaluateLearningAnswer(root);
      return;
    }
    if (mathKey) {
      const root = mathKey.closest("[data-answer-root]");
      const input = root.querySelector("[data-answer-field].is-active")
        || root.querySelector("[data-answer-field]");
      if (input) {
        insertMathKey(
          input,
          mathKey.dataset.mathAction || mathKey.dataset.mathInsert || "",
          Number.parseInt(mathKey.dataset.cursorBack || "0", 10),
        );
      }
      return;
    }
    const chapterButton = event.target.closest("[data-chapter]");
    const subchapterButton = event.target.closest("[data-subchapter]");
    const collectionLink = event.target.closest("[data-collection]");
    const worksheetCollectionButton = event.target.closest("[data-worksheet-collection]");
    const learningMethodLink = event.target.closest("[data-learning-method]");
    const learningModuleLink = event.target.closest("[data-learning-module]");
    const learningTopicEntry = event.target.closest("[data-learning-topic-entry]");
    const chapterToggle = event.target.closest("[data-chapter-toggle]");
    const sectionButton = event.target.closest("[data-section]");
    const pageButton = event.target.closest("[data-page]");
    if (worksheetCollectionButton) {
      setState({ collection: worksheetCollectionButton.dataset.worksheetCollection, page: 1 });
    } else if (learningTopicEntry) {
      event.preventDefault();
      const topic = getLearningTopic(learningTopicEntry.dataset.learningTopicEntry);
      if (topic) {
        expandedChapters.add(topic.chapterId);
        collapsedChapters.delete(topic.chapterId);
        setState({
          chapter: topic.chapterId,
          section: topic.sectionId,
          collection: "all",
          module: "overview",
          page: 1,
        });
      }
    } else if (learningMethodLink) {
      event.preventDefault();
      const methodId = learningMethodLink.dataset.learningMethod;
      setState({
        method: methodId,
        page: 1,
      });
      const url = new URL(window.location.href);
      url.hash = methodId === "all" ? "" : "selected-method-heading";
      window.history.replaceState({}, "", url);
      requestAnimationFrame(() => {
        const targetId = methodId === "all" ? "solving-methods-heading" : "selected-method-heading";
        document.getElementById(targetId)?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    } else if (learningModuleLink) {
      event.preventDefault();
      setState({
        module: learningModuleLink.dataset.learningModule,
        method: "all",
        collection: "all",
        page: 1,
      });
    } else if (collectionLink) {
      event.preventDefault();
      const collection = getCollection(collectionLink.dataset.collection);
      if (collection) {
        expandedChapters.add(collection.chapterId);
        collapsedChapters.delete(collection.chapterId);
        setState({
          chapter: collection.chapterId,
          section: collection.sectionId,
          collection: collection.id,
          page: 1,
        });
      }
    } else if (subchapterButton) {
      expandedChapters.add(subchapterButton.dataset.parentChapter);
      collapsedChapters.delete(subchapterButton.dataset.parentChapter);
      setState({
        chapter: subchapterButton.dataset.parentChapter,
        section: subchapterButton.dataset.subchapter,
        collection: "all",
        module: "overview",
        page: 1,
      });
    } else if (chapterToggle) {
      const chapterId = chapterToggle.dataset.chapterToggle;
      if (chapterToggle.getAttribute("aria-expanded") === "true") {
        expandedChapters.delete(chapterId);
        collapsedChapters.add(chapterId);
      } else {
        collapsedChapters.delete(chapterId);
        expandedChapters.add(chapterId);
      }
      renderChapters();
    } else if (chapterButton) {
      const chapterId = chapterButton.dataset.chapter;
      if (chapterId !== "all" && getChapter(chapterId)?.sections.some(
        (section) => section.presentation === "worksheet" || section.presentation === "learning",
      )) {
        expandedChapters.add(chapterId);
        collapsedChapters.delete(chapterId);
      }
      setState({
        chapter: chapterId,
        section: "all",
        collection: "all",
        module: "all",
        page: 1,
      });
    } else if (sectionButton) {
      setState({
        section: sectionButton.dataset.section,
        collection: "all",
        module: "all",
        page: 1,
      });
    } else if (pageButton && !pageButton.disabled) {
      setState({ page: Number.parseInt(pageButton.dataset.page, 10) });
    }
  });

  elements.learning.addEventListener("focusin", (event) => {
    const field = event.target.closest("[data-answer-field]");
    if (!field) return;
    const root = field.closest("[data-answer-root]");
    root.querySelectorAll("[data-answer-field]").forEach((input) => {
      input.classList.toggle("is-active", input === field);
    });
    const keyboard = root.querySelector(".senior-learning-math-keyboard");
    if (keyboard) {
      keyboard.classList.add("is-visible");
      root.querySelector("[data-symbol-toggle]")?.setAttribute("aria-expanded", "true");
    }
  });
  elements.learning.addEventListener("input", (event) => {
    const field = event.target.closest("[data-answer-field]");
    if (!field) return;
    const root = field.closest("[data-answer-root]");
    const preview = root.querySelector("[data-answer-preview]");
    if (preview) preview.innerHTML = answerPreviewMarkup(field.value);
    root.classList.remove("is-correct", "is-incorrect");
    root.querySelector("[data-answer-feedback]").textContent = "";
  });
  elements.learning.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const hint = event.target.closest(".senior-learning-hint");
    if (hint) {
      hint.classList.remove("is-open");
      const button = hint.querySelector("[data-hint-toggle]");
      button?.setAttribute("aria-expanded", "false");
      button?.focus();
      return;
    }
    const root = event.target.closest("[data-answer-root]");
    const keyboard = root?.querySelector(".senior-learning-math-keyboard.is-visible");
    if (!keyboard) return;
    keyboard.classList.remove("is-visible");
    const button = root.querySelector("[data-symbol-toggle]");
    button?.setAttribute("aria-expanded", "false");
    button?.focus();
  });

  elements.difficulty.addEventListener("change", () => {
    setState({ difficulty: elements.difficulty.value, page: 1 });
  });
  elements.source.addEventListener("change", () => {
    setState({ source: elements.source.value, page: 1 });
  });
  elements.sort.addEventListener("change", () => {
    setState({ sort: elements.sort.value, page: 1 });
  });
  window.addEventListener("popstate", () => {
    state = model.parseSearch(catalog, window.location.search);
    render();
  });

  loadCatalog().then((loadedCatalog) => {
    catalog = loadedCatalog;
    state = model.parseSearch(catalog, window.location.search);
    replaceCurrentUrl();
    render();
  });
})();
