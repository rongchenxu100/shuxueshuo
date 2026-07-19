(function initializeSeniorHighLibrary() {
  const model = window.SeniorHighLibraryModel;
  if (!model) {
    return;
  }

  const elements = {
    chapterNav: document.querySelector("#chapter-nav"),
    title: document.querySelector("#catalog-title"),
    count: document.querySelector("#catalog-count"),
    sectionTabs: document.querySelector("#section-tabs"),
    difficulty: document.querySelector("#difficulty-filter"),
    source: document.querySelector("#source-filter"),
    sort: document.querySelector("#sort-filter"),
    grid: document.querySelector("#problem-grid"),
    pagination: document.querySelector("#pagination"),
  };

  let catalog = null;
  let state = { ...model.DEFAULT_STATE };

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
      const response = await fetch("../data/senior-high-catalog.json");
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

  function countChapter(chapterId) {
    return model.publishedProblems(catalog).filter((problem) => (
      chapterId === "all" || problem.chapterId === chapterId
    )).length;
  }

  function countSection(chapterId, sectionId) {
    return model.publishedProblems(catalog).filter((problem) => (
      problem.chapterId === chapterId && (sectionId === "all" || problem.sectionId === sectionId)
    )).length;
  }

  function renderChapters() {
    const chapters = [
      { id: "all", label: "全部题目", symbol: "∴" },
      ...catalog.chapters,
    ];
    elements.chapterNav.innerHTML = chapters.map((chapter) => {
      const active = state.chapter === chapter.id;
      return `
        <button
          class="senior-library-chapter${active ? " is-active" : ""}"
          type="button"
          data-chapter="${escapeHtml(chapter.id)}"
          ${active ? 'aria-current="page"' : ""}
        >
          <span class="senior-library-chapter-symbol" aria-hidden="true">${escapeHtml(chapter.symbol || "·")}</span>
          <span class="senior-library-chapter-name">${escapeHtml(chapter.label)}</span>
          <span class="senior-library-chapter-count">${countChapter(chapter.id)}</span>
        </button>
      `;
    }).join("");
  }

  function renderSections() {
    const chapter = getChapter(state.chapter);
    if (!chapter || chapter.sections.length === 0) {
      elements.sectionTabs.hidden = true;
      elements.sectionTabs.innerHTML = "";
      return;
    }

    const sections = chapter.sections;
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
      model.publishedProblems(catalog).map((problem) => problem.source.region),
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
    const results = model.filterProblems(catalog, state);
    const pageInfo = model.paginate(results, state.page);
    if (pageInfo.page !== state.page) {
      state = { ...state, page: pageInfo.page };
      replaceCurrentUrl();
    }

    const chapter = getChapter(state.chapter);
    elements.title.textContent = chapter?.label || "全部题目";
    elements.count.textContent = `${results.length} 道`;
    elements.difficulty.value = state.difficulty;
    elements.sort.value = state.sort;
    renderSourceOptions();
    renderChapters();
    renderSections();
    elements.grid.innerHTML = pageInfo.items.length
      ? pageInfo.items.map(renderProblem).join("")
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
    const sectionButton = event.target.closest("[data-section]");
    const pageButton = event.target.closest("[data-page]");
    if (chapterButton) {
      setState({ chapter: chapterButton.dataset.chapter, section: "all", page: 1 });
    } else if (sectionButton) {
      setState({ section: sectionButton.dataset.section, page: 1 });
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
