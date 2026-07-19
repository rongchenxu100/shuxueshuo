(function registerSeniorHighLibraryModel(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.SeniorHighLibraryModel = api;
})(typeof globalThis === "object" ? globalThis : this, function createModel() {
  const DEFAULT_STATE = Object.freeze({
    chapter: "all",
    section: "all",
    difficulty: "all",
    source: "all",
    sort: "updated-desc",
    page: 1,
  });
  const SORTS = new Set(["updated-desc", "difficulty-desc", "year-desc"]);

  function publishedProblems(catalog) {
    return (catalog?.problems || []).filter((problem) => problem.status === "published");
  }

  function sourceValues(catalog) {
    return new Set(publishedProblems(catalog).map((problem) => problem.source.region));
  }

  function normalizeState(catalog, input = {}) {
    const chapterIds = new Set((catalog?.chapters || []).map((chapter) => chapter.id));
    const chapter = chapterIds.has(input.chapter) ? input.chapter : "all";
    const selectedChapter = (catalog?.chapters || []).find((item) => item.id === chapter);
    const sectionIds = new Set((selectedChapter?.sections || []).map((section) => section.id));
    const section = chapter !== "all" && sectionIds.has(input.section) ? input.section : "all";
    const difficulty = /^[1-5]$/.test(String(input.difficulty || ""))
      ? String(input.difficulty)
      : "all";
    const source = sourceValues(catalog).has(input.source) ? input.source : "all";
    const sort = SORTS.has(input.sort) ? input.sort : DEFAULT_STATE.sort;
    const parsedPage = Number.parseInt(input.page, 10);
    const page = Number.isInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1;
    return { chapter, section, difficulty, source, sort, page };
  }

  function parseSearch(catalog, search) {
    const params = search instanceof URLSearchParams
      ? search
      : new URLSearchParams(String(search || "").replace(/^\?/, ""));
    return normalizeState(catalog, Object.fromEntries(params.entries()));
  }

  function filterProblems(catalog, inputState) {
    const state = normalizeState(catalog, inputState);
    const problems = publishedProblems(catalog)
      .filter((problem) => state.chapter === "all" || problem.chapterId === state.chapter)
      .filter((problem) => state.section === "all" || problem.sectionId === state.section)
      .filter((problem) => state.difficulty === "all" || String(problem.difficulty) === state.difficulty)
      .filter((problem) => state.source === "all" || problem.source.region === state.source);

    return problems.sort((left, right) => {
      if (state.sort === "difficulty-desc") {
        return right.difficulty - left.difficulty || Date.parse(right.updatedAt) - Date.parse(left.updatedAt);
      }
      if (state.sort === "year-desc") {
        return right.source.year - left.source.year || Date.parse(right.updatedAt) - Date.parse(left.updatedAt);
      }
      return Date.parse(right.updatedAt) - Date.parse(left.updatedAt);
    });
  }

  function paginate(items, requestedPage, pageSize = 8) {
    const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
    const page = Math.min(Math.max(1, Number.parseInt(requestedPage, 10) || 1), pageCount);
    return {
      items: items.slice((page - 1) * pageSize, page * pageSize),
      page,
      pageCount,
      total: items.length,
    };
  }

  function stateToSearch(inputState) {
    const state = { ...DEFAULT_STATE, ...inputState };
    const params = new URLSearchParams();
    for (const key of ["chapter", "section", "difficulty", "source", "sort"]) {
      if (state[key] !== DEFAULT_STATE[key]) {
        params.set(key, state[key]);
      }
    }
    if (state.page > 1) {
      params.set("page", String(state.page));
    }
    const value = params.toString();
    return value ? `?${value}` : "";
  }

  return {
    DEFAULT_STATE,
    filterProblems,
    normalizeState,
    paginate,
    parseSearch,
    publishedProblems,
    stateToSearch,
  };
});
