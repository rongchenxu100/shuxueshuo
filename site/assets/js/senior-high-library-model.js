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
    module: "all",
    method: "all",
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

  function learningTopicForState(catalog, inputState) {
    const state = normalizeState(catalog, inputState);
    if (state.chapter === "all" || state.section === "all") return null;
    const chapter = (catalog?.chapters || []).find((item) => item.id === state.chapter);
    const section = chapter?.sections.find((item) => item.id === state.section);
    if (section?.presentation !== "learning") return null;
    return (catalog?.learningTopics || []).find((item) => item.id === section.topicId) ?? null;
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
    const learningTopic = selectedSection?.presentation === "learning"
      ? (catalog?.learningTopics || []).find((item) => item.id === selectedSection.topicId)
      : null;
    const moduleIds = new Set(["overview", ...(learningTopic?.modules || []).map((item) => item.id)]);
    const module = learningTopic
      ? (moduleIds.has(input.module) ? input.module : "overview")
      : "all";
    const selectedModule = learningTopic?.modules?.find((item) => item.id === module);
    const methodIds = new Set(
      (selectedModule?.knowledgeGroups || [])
        .filter((group) => group.section === "method")
        .map((group) => group.id),
    );
    const method = methodIds.has(input.method) ? input.method : "all";
    const difficulty = /^[1-5]$/.test(String(input.difficulty || ""))
      ? String(input.difficulty)
      : "all";
    const source = sourceValues(catalog).has(input.source) ? input.source : "all";
    const sort = SORTS.has(input.sort) ? input.sort : DEFAULT_STATE.sort;
    const parsedPage = Number.parseInt(input.page, 10);
    const page = Number.isInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1;
    return { chapter, section, collection, module, method, difficulty, source, sort, page };
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
    for (const key of ["chapter", "section", "collection", "module", "method", "difficulty", "source", "sort"]) {
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

  function splitOrdinalOptions(html) {
    const source = String(html || "");
    const matches = Array.from(source.matchAll(/[①②③④]/g));
    if (matches.length < 2 || matches[0][0] !== "①") return null;

    const options = matches.map((match, index) => {
      const start = match.index + match[0].length;
      const end = index + 1 < matches.length ? matches[index + 1].index : source.length;
      return {
        label: match[0],
        html: source.slice(start, end).trim().replace(/^[；;]\s*|[；;。]\s*$/g, ""),
      };
    });
    const lengths = options.map((option) => worksheetPlainText(option.html).length);

    return {
      stemHtml: source.slice(0, matches[0].index).trim(),
      options,
      stacked: Math.max(...lengths) > 12 || lengths.reduce((sum, length) => sum + length, 0) > 48,
    };
  }

  function canonicalRational(rawValue) {
    const value = String(rawValue ?? "")
      .trim()
      .replace(/−/g, "-")
      .replace(/\s+/g, "");
    const match = value.match(/^([+-]?\d+)(?:\/([+-]?\d+))?$/);
    if (!match) return null;
    let numerator = Number.parseInt(match[1], 10);
    let denominator = match[2] == null ? 1 : Number.parseInt(match[2], 10);
    if (denominator === 0) return null;
    if (denominator < 0) {
      numerator *= -1;
      denominator *= -1;
    }
    let left = Math.abs(numerator);
    let right = Math.abs(denominator);
    while (right !== 0) {
      [left, right] = [right, left % right];
    }
    const divisor = left || 1;
    numerator /= divisor;
    denominator /= divisor;
    return denominator === 1 ? String(numerator) : `${numerator}/${denominator}`;
  }

  function normalizeMathExpression(rawValue) {
    return String(rawValue ?? "")
      .trim()
      .replace(/[，；;]/g, ",")
      .replace(/−/g, "-")
      .replace(/!=/g, "≠")
      .replace(/\\mathbb\{R\}/g, "ℝ")
      .replace(/\\setminus/g, "∖")
      .replace(/\s+/g, "");
  }

  function normalizeExactMathExpression(rawValue) {
    const semicolonToken = "__SEMICOLON__";
    return normalizeMathExpression(String(rawValue ?? "").replace(/[；;]/g, semicolonToken))
      .replace(/[｛]/g, "{")
      .replace(/[｝]/g, "}")
      .replace(/[（]/g, "(")
      .replace(/[）]/g, ")")
      .replace(/[【［]/g, "[")
      .replace(/[】］]/g, "]")
      .replaceAll(semicolonToken, ";")
      .replace(/\+?∞/g, "∞");
  }

  function parseFiniteSetValues(rawValue) {
    let value = normalizeMathExpression(rawValue);
    if (
      (value.startsWith("{") && value.endsWith("}"))
      || (value.startsWith("｛") && value.endsWith("｝"))
    ) {
      value = value.slice(1, -1);
    }
    if (!value) return null;
    const parts = value.split(",").filter(Boolean);
    if (parts.length === 0) return null;
    const values = parts.map(canonicalRational);
    return values.some((item) => item == null) ? null : values;
  }

  function parseVariableDomainExclusions(rawValue, variable = "x") {
    let value = normalizeMathExpression(rawValue);
    const escapedVariable = String(variable).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const setDifference = value.match(
      new RegExp(`^${escapedVariable}(?:∈|in)(?:ℝ|R)(?:\\\\|∖)\\{(.+)\\}$`),
    );
    if (setDifference) return parseFiniteSetValues(`{${setDifference[1]}}`);
    const notIn = value.match(
      new RegExp(`^${escapedVariable}(?:∉|notin)\\{(.+)\\}$`),
    );
    if (notIn) return parseFiniteSetValues(`{${notIn[1]}}`);

    value = value.replace(
      new RegExp(`^${escapedVariable}(?:∈|in)(?:ℝ|R)(?:且|,)?`),
      "",
    );
    const parts = value.split(/,|且/).filter(Boolean);
    if (parts.length === 0) return null;
    const values = parts.map((part, index) => {
      const leftRelation = part.match(new RegExp(`^${escapedVariable}≠(.+)$`));
      if (leftRelation) return canonicalRational(leftRelation[1]);
      const rightRelation = part.match(new RegExp(`^(.+)≠${escapedVariable}$`));
      if (rightRelation) return canonicalRational(rightRelation[1]);
      if (index > 0) return canonicalRational(part);
      return null;
    });
    return values.some((item) => item == null) ? null : values;
  }

  function parseRelationSequence(rawValue) {
    const value = String(rawValue ?? "")
      .trim()
      .replace(/\\nsubseteq|nsubseteq/g, "⊄")
      .replace(/\\subsetneq|subsetneq/g, "⊊")
      .replace(/\\supsetneq|supsetneq/g, "⊋")
      .replace(/\\subseteq|subseteq/g, "⊆")
      .replace(/\\supseteq|supseteq/g, "⊇")
      .replace(/\\ne|!=/g, "≠")
      .replace(/\\notin|notin/g, "∉")
      .replace(/\\in|\bin\b/g, "∈");
    const relations = value.match(/[∈∉=≠⊆⊄⊊⊋⊇]/g) || [];
    const remainder = value
      .replace(/[∈∉=≠⊆⊄⊊⊋⊇]/g, "")
      .replace(/[\s,，、;；]/g, "");
    return relations.length > 0 && remainder === "" ? relations : null;
  }

  return {
    DEFAULT_STATE,
    canonicalRational,
    collectionForState,
    collectionProblemCount,
    filterProblems,
    learningTopicForState,
    normalizeState,
    normalizeExactMathExpression,
    parseFiniteSetValues,
    parseRelationSequence,
    paginate,
    parseSearch,
    parseVariableDomainExclusions,
    publishedProblems,
    splitOrdinalOptions,
    splitWorksheetOptions,
    stateToSearch,
  };
});
