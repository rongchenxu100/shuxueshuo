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
    collection: "all",
    difficulty: "all",
    source: "all",
    sort: "updated-desc",
    page: 1,
  });
  const SORTS = new Set(["updated-desc", "difficulty-desc", "year-desc"]);

  function publishedProblems(catalog) {
    return (catalog?.problems || []).filter((problem) => problem.status === "published");
  }

  function collectionForState(catalog, inputState) {
    const state = normalizeState(catalog, inputState);
    if (state.chapter === "all" || state.section === "all") return null;
    const chapter = (catalog?.chapters || []).find((item) => item.id === state.chapter);
    const section = chapter?.sections.find((item) => item.id === state.section);
    if (section?.presentation !== "worksheet" || state.collection === "all") return null;
    return (catalog?.collections || []).find((item) => item.id === state.collection) ?? null;
  }

  function collectionProblemCount(collection) {
    return (collection?.groups || []).reduce(
      (total, group) => total + (group.problems || []).length,
      0,
    );
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
    const selectedSection = selectedChapter?.sections.find((item) => item.id === section);
    const collectionIds = new Set(selectedSection?.collectionIds || []);
    const collection = selectedSection?.presentation === "worksheet"
      ? (collectionIds.has(input.collection)
        ? input.collection
        : selectedSection.defaultCollectionId || selectedSection.collectionIds?.[0] || "all")
      : "all";
    const difficulty = /^[1-5]$/.test(String(input.difficulty || ""))
      ? String(input.difficulty)
      : "all";
    const source = sourceValues(catalog).has(input.source) ? input.source : "all";
    const sort = SORTS.has(input.sort) ? input.sort : DEFAULT_STATE.sort;
    const parsedPage = Number.parseInt(input.page, 10);
    const page = Number.isInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1;
    return { chapter, section, collection, difficulty, source, sort, page };
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
    for (const key of ["chapter", "section", "collection", "difficulty", "source", "sort"]) {
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

  function worksheetPlainText(html) {
    return String(html || "")
      .replace(/<[^>]*>/g, "")
      .replace(/&nbsp;/g, " ")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&amp;/g, "&")
      .replace(/\s+/g, " ")
      .trim();
  }

  function splitWorksheetOptions(html) {
    const source = String(html || "");
    const optionPattern = /(?:^|[\s　])([A-D])\.\s*/g;
    const matches = Array.from(source.matchAll(optionPattern));
    if (matches.length < 2 || matches[0][1] !== "A") return null;

    const options = matches.map((match, index) => {
      const start = match.index + match[0].length;
      const end = index + 1 < matches.length ? matches[index + 1].index : source.length;
      return {
        label: match[1],
        html: source.slice(start, end).trim(),
      };
    });
    const lengths = options.map((option) => worksheetPlainText(option.html).length);

    return {
      stemHtml: source.slice(0, matches[0].index).trim(),
      options,
      stacked: Math.max(...lengths) > 12 || lengths.reduce((sum, length) => sum + length, 0) > 48,
    };
  }

  return {
    DEFAULT_STATE,
    collectionForState,
    collectionProblemCount,
    filterProblems,
    normalizeState,
    paginate,
    parseSearch,
    publishedProblems,
    splitWorksheetOptions,
    stateToSearch,
  };
});
