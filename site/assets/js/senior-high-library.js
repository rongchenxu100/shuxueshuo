(function initializeSeniorHighLibrary() {
  const model = window.SeniorHighLibraryModel;
  if (!model) {
    return;
  }

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
      const response = await fetch("../data/senior-high-catalog.json?v=3");
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

  function countChapter(chapterId) {
    const standaloneCount = model.publishedProblems(catalog).filter((problem) => (
      chapterId === "all" || problem.chapterId === chapterId
    )).length;
    return standaloneCount + collectionCountForChapter(chapterId);
  }

  function countSection(chapterId, sectionId) {
    return model.publishedProblems(catalog).filter((problem) => (
      problem.chapterId === chapterId && (sectionId === "all" || problem.sectionId === sectionId)
    )).length;
  }

  function renderChapters() {
    const chapters = [
      { id: "all", label: "全部题目" },
      ...catalog.chapters,
    ];
    elements.chapterNav.innerHTML = chapters.map((chapter) => {
      const sections = chapter.sections || [];
      const worksheetSections = sections.filter((section) => section.presentation === "worksheet");
      const hasChildren = worksheetSections.length > 0;
      const active = state.chapter === chapter.id && state.section === "all";
      const parentActive = state.chapter === chapter.id && state.section !== "all";
      const expanded = hasChildren
        && !collapsedChapters.has(chapter.id)
        && (expandedChapters.has(chapter.id) || state.chapter === chapter.id);
      return `
        <div class="senior-library-chapter-group">
          <button
            class="senior-library-chapter${active ? " is-active" : ""}${parentActive ? " is-parent-active" : ""}"
            type="button"
            data-chapter="${escapeHtml(chapter.id)}"
            ${active ? 'aria-current="page"' : ""}
            ${hasChildren ? `aria-expanded="${expanded}"` : ""}
          >
            <span
              class="senior-library-chapter-chevron${hasChildren ? "" : " is-empty"}"
              ${hasChildren ? "data-chapter-toggle" : ""}
              aria-hidden="true"
            >${expanded ? "⌄" : "›"}</span>
            <span class="senior-library-chapter-name">${escapeHtml(chapter.label)}</span>
            <span class="senior-library-chapter-count">${countChapter(chapter.id)}</span>
          </button>
          ${hasChildren && expanded ? `
            <div class="senior-library-subchapters">
              ${worksheetSections.map((section) => {
                const collections = getCollectionsForSection(section);
                const selected = state.chapter === chapter.id && state.section === section.id;
                return `
                  <button
                    class="senior-library-subchapter${selected ? " is-active" : ""}"
                    type="button"
                    data-subchapter="${escapeHtml(section.id)}"
                    data-parent-chapter="${escapeHtml(chapter.id)}"
                    ${selected ? 'aria-current="page"' : ""}
                  >
                    <span>${escapeHtml(section.label)}</span>
                    <span>${collections.reduce((sum, item) => sum + model.collectionProblemCount(item), 0)}</span>
                  </button>
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
    renderChapters();

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
    const collectionProblemCount = overviewCollections.reduce(
      (total, collection) => total + model.collectionProblemCount(collection),
      0,
    );
    elements.title.textContent = chapter?.label || "全部题目";
    elements.count.textContent = `${results.length + collectionProblemCount} 道`;
    elements.filters.hidden = false;
    elements.collectionTabs.hidden = true;
    elements.collectionTabs.innerHTML = "";
    elements.difficulty.value = state.difficulty;
    elements.sort.value = state.sort;
    renderSourceOptions();
    renderSections();
    elements.worksheet.hidden = true;
    elements.worksheet.innerHTML = "";
    elements.grid.hidden = false;
    const overviewMarkup = overviewCollections.map(renderCollectionEntry);
    const problemMarkup = pageInfo.items.map(renderProblem);
    elements.grid.innerHTML = overviewMarkup.length || problemMarkup.length
      ? [...overviewMarkup, ...problemMarkup].join("")
      : renderEmpty();
    renderPagination(pageInfo);
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
    const chapterButton = event.target.closest("[data-chapter]");
    const subchapterButton = event.target.closest("[data-subchapter]");
    const collectionLink = event.target.closest("[data-collection]");
    const worksheetCollectionButton = event.target.closest("[data-worksheet-collection]");
    const chapterToggle = event.target.closest("[data-chapter-toggle]");
    const sectionButton = event.target.closest("[data-section]");
    const pageButton = event.target.closest("[data-page]");
    if (worksheetCollectionButton) {
      setState({ collection: worksheetCollectionButton.dataset.worksheetCollection, page: 1 });
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
        page: 1,
      });
    } else if (chapterToggle) {
      const chapterId = chapterButton.dataset.chapter;
      if (chapterButton.getAttribute("aria-expanded") === "true") {
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
        (section) => section.presentation === "worksheet",
      )) {
        expandedChapters.add(chapterId);
        collapsedChapters.delete(chapterId);
      }
      setState({ chapter: chapterId, section: "all", collection: "all", page: 1 });
    } else if (sectionButton) {
      setState({ section: sectionButton.dataset.section, collection: "all", page: 1 });
    } else if (pageButton && !pageButton.disabled) {
      setState({ page: Number.parseInt(pageButton.dataset.page, 10) });
    }
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
