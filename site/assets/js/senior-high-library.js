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
      const response = await fetch("../data/senior-high-catalog.json?v=14");
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
      negative: { label: "−", insert: "-" },
      fraction: { label: "分数", insert: "/" },
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

  function renderSetMindMap(topic) {
    const href = (moduleId) => escapeHtml(topicHref(topic, moduleId));
    const colors = ["is-coral", "is-blue", "is-gold", "is-green"];
    const branchGap = topic.mapNodes.length > 1 ? 470 / (topic.mapNodes.length - 1) : 0;
    const rootJoiner = topic.title.includes("和") ? "和" : topic.title.includes("与") ? "与" : "";
    const rootBreak = rootJoiner ? topic.title.lastIndexOf(rootJoiner) : -1;
    const rootLines = rootBreak > 0
      ? [topic.title.slice(0, rootBreak), topic.title.slice(rootBreak)]
      : [topic.title, ""];
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
        return `
          <text class="map-label" x="${childX}" y="${childY + 6}">${escapeHtml(mindMapChildLabel(child))}</text>
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
            <text x="191" y="313" text-anchor="middle">${escapeHtml(rootLines[0] || topic.title)}</text>
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
    const renderKnowledgeItems = (blocks) => blocks.map((block) => `
      <article class="senior-learning-knowledge-item">
        <h4>${escapeHtml(block.title)}</h4>
        ${block.bodyHtml.map((line) => `<p>${line}</p>`).join("")}
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
    const groupedExamples = groupLearningExamples(module.examples);
    const examplesForCategory = (category) => module.examples.filter(
      (example) => learningExampleCategory(example) === category,
    );
    const exerciseHrefForCategory = (category) => {
      const firstExample = examplesForCategory(category)[0];
      return firstExample
        ? `#exercises-${learningGroupSlug(firstExample.group)}`
        : "#worked-examples-heading";
    };
    return `
      <article class="senior-learning-topic">
        <header class="senior-learning-module-hero">
          <p class="senior-learning-kicker">知识模块</p>
          <h2>${escapeHtml(module.label)}</h2>
          <p>${escapeHtml(module.description)}</p>
        </header>
        <section class="senior-learning-section" aria-labelledby="core-knowledge-heading">
          <div class="senior-learning-section-heading">
            <p>CORE KNOWLEDGE</p>
            <h2 id="core-knowledge-heading">核心知识</h2>
          </div>
          <div class="senior-learning-knowledge-groups">
            ${(module.knowledgeGroups || []).map((group) => `
              <article id="knowledge-${escapeHtml(group.category)}" class="senior-learning-knowledge-group is-${escapeHtml(group.category)} has-${module.knowledgeBlocks.filter(
                (block) => block.category === group.category,
              ).length}-items">
                <div class="senior-learning-knowledge-group-heading">
                  <span>${escapeHtml(group.number)}</span>
                  <div>
                    <p>${escapeHtml(group.eyebrow)}</p>
                    <h3>${escapeHtml(group.title)}</h3>
                    <a class="senior-learning-exercise-anchor" href="${escapeHtml(exerciseHrefForCategory(group.category))}">
                      <span>对应练习</span>
                      <strong>${examplesForCategory(group.category).length} 题</strong>
                      <span aria-hidden="true">↓</span>
                    </a>
                  </div>
                </div>
                <div class="senior-learning-knowledge-items">
                  ${renderKnowledgeItems(module.knowledgeBlocks.filter(
                    (block) => block.category === group.category,
                  ))}
                </div>
                ${renderKnowledgeVisual(group)}
              </article>
            `).join("")}
          </div>
        </section>
        <section class="senior-learning-section" aria-labelledby="worked-examples-heading">
          <div class="senior-learning-section-heading">
            <h2 id="worked-examples-heading">例题精讲</h2>
          </div>
          <div class="senior-learning-exercise-sheet">
            ${groupedExamples.map(([group, entries]) => `
              <section id="exercises-${escapeHtml(learningGroupSlug(group))}" class="senior-learning-example-group" aria-labelledby="learning-example-group-${escapeHtml(group)}">
                <h3 id="learning-example-group-${escapeHtml(group)}">${escapeHtml(group)}</h3>
                <div class="senior-learning-example-list">
                  ${entries.map(({ example, index }) => renderInteractiveLearningExample(example, index)).join("")}
                </div>
                <a class="senior-learning-return-anchor" href="#knowledge-${escapeHtml(learningExampleCategory(entries[0].example))}">↑ 返回对应知识点</a>
              </section>
            `).join("")}
          </div>
        </section>
        <section class="senior-learning-summary">
          <p>归纳总结</p>
          <div>${module.summaryHtml}</div>
        </section>
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
      elements.title.textContent = state.module === "overview"
        ? learningTopic.title
        : activeModule?.label || learningTopic.title;
      elements.count.textContent = state.module === "overview"
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
    } else if (learningModuleLink) {
      event.preventDefault();
      setState({
        module: learningModuleLink.dataset.learningModule,
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
