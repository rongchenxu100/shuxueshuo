import type {
  NavResponse,
  Problem,
  SuggestedProblem,
  PublishStatus,
  SiteHome,
  Topic,
  TopicItem,
} from "@/lib/contracts";

export type WorkspaceSelection =
  | { kind: "new_problem" }
  | { kind: "problem"; id: string }
  | { kind: "site_home" }
  | { kind: "topic"; id: string };

export type AutosaveState = "saving" | "saved" | "error";

export type SelectedWorkspaceObject =
  | { kind: "new_problem" }
  | { kind: "problem"; item: Problem }
  | { kind: "site_home"; item: SiteHome }
  | { kind: "topic"; item: Topic };

export function getInitialSelection(nav: NavResponse): WorkspaceSelection {
  const [firstProblem] = nav.problems;
  if (firstProblem) {
    return { kind: "problem", id: firstProblem.id };
  }

  if (nav.siteHome) {
    return { kind: "site_home" };
  }

  const [firstTopic] = nav.topics;
  if (firstTopic) {
    return { kind: "topic", id: firstTopic.id };
  }

  return { kind: "new_problem" };
}

export function resolveSelection(
  nav: NavResponse,
  selection: WorkspaceSelection,
): SelectedWorkspaceObject {
  if (selection.kind === "problem") {
    const item = nav.problems.find((problem) => problem.id === selection.id);
    if (item) {
      return { kind: "problem", item };
    }
  }

  if (selection.kind === "topic") {
    const item = nav.topics.find((topic) => topic.id === selection.id);
    if (item) {
      return { kind: "topic", item };
    }
  }

  if (selection.kind === "site_home") {
    return { kind: "site_home", item: nav.siteHome };
  }

  if (selection.kind === "new_problem") {
    return { kind: "new_problem" };
  }

  return { kind: "new_problem" };
}

export function publishStatusLabel(status: PublishStatus): string {
  const labels: Record<PublishStatus, string> = {
    draft: "草稿",
    published: "已发布",
    published_dirty: "已发布 · 有改动",
  };

  return labels[status];
}

export function publishActionLabel(
  status: PublishStatus,
  publicUrl: string | null,
): string {
  if (status === "published" && publicUrl) {
    return "打开页面";
  }

  if (status === "published_dirty") {
    return "发布更新";
  }

  return "发布";
}

export function autosaveStateLabel(state: AutosaveState): string {
  const labels: Record<AutosaveState, string> = {
    saving: "正在保存",
    saved: "刚刚已保存",
    error: "保存失败",
  };

  return labels[state];
}

export function previewUrlWithVersion(
  previewUrl: string,
  previewVersion?: string,
): string {
  if (!previewVersion) {
    return previewUrl;
  }

  const hashIndex = previewUrl.indexOf("#");
  const withoutHash =
    hashIndex >= 0 ? previewUrl.slice(0, hashIndex) : previewUrl;
  const hash = hashIndex >= 0 ? previewUrl.slice(hashIndex) : "";
  const queryIndex = withoutHash.indexOf("?");
  const path =
    queryIndex >= 0 ? withoutHash.slice(0, queryIndex) : withoutHash;
  const query = queryIndex >= 0 ? withoutHash.slice(queryIndex + 1) : "";
  const params = new URLSearchParams(query);
  params.set("v", previewVersion);

  return `${path}?${params.toString()}${hash}`;
}

export function insertProblem(nav: NavResponse, problem: Problem): NavResponse {
  return {
    ...nav,
    problems: [problem, ...nav.problems.filter((item) => item.id !== problem.id)],
  };
}

export function updateProblem(nav: NavResponse, problem: Problem): NavResponse {
  return {
    ...nav,
    problems: nav.problems.map((item) =>
      item.id === problem.id ? problem : item,
    ),
  };
}

export function mergePublishedProblem(
  currentProblem: Problem,
  publishedProblem: Problem,
): Problem {
  return {
    ...currentProblem,
    autosavedAt: publishedProblem.autosavedAt,
    publicUrl: publishedProblem.publicUrl,
    status: publishedProblem.status,
    updatedAt: publishedProblem.updatedAt,
  };
}

export function updateTopic(nav: NavResponse, topic: Topic): NavResponse {
  return {
    ...nav,
    topics: nav.topics.map((item) => (item.id === topic.id ? topic : item)),
  };
}

export function insertTopic(nav: NavResponse, topic: Topic): NavResponse {
  return {
    ...nav,
    topics: [topic, ...nav.topics.filter((item) => item.id !== topic.id)],
  };
}

export function removeTopic(nav: NavResponse, topicId: string): NavResponse {
  return {
    ...nav,
    topics: nav.topics.filter((topic) => topic.id !== topicId),
  };
}

export function removeProblem(nav: NavResponse, problemId: string): NavResponse {
  return {
    ...nav,
    problems: nav.problems.filter((problem) => problem.id !== problemId),
  };
}

export function updateSiteHome(
  nav: NavResponse,
  siteHome: SiteHome,
): NavResponse {
  return {
    ...nav,
    siteHome,
  };
}

export function getSelectionAfterRemoval(
  nav: NavResponse,
  removedSelection: WorkspaceSelection,
): WorkspaceSelection {
  const nextNav =
    removedSelection.kind === "problem"
      ? removeProblem(nav, removedSelection.id)
      : removedSelection.kind === "topic"
        ? removeTopic(nav, removedSelection.id)
        : nav;

  return getInitialSelection(nextNav);
}

export function paginateItems<T>(
  items: T[],
  page: number,
  pageSize: number,
): { items: T[]; page: number; pageCount: number; total: number } {
  const total = items.length;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(Math.max(page, 1), pageCount);
  const start = (safePage - 1) * pageSize;

  return {
    items: items.slice(start, start + pageSize),
    page: safePage,
    pageCount,
    total,
  };
}

export function moveTopicItem(
  items: TopicItem[],
  itemId: string,
  direction: "down" | "up",
): TopicItem[] {
  const index = items.findIndex((item) => item.id === itemId);
  const nextIndex = direction === "up" ? index - 1 : index + 1;

  if (index < 0 || nextIndex < 0 || nextIndex >= items.length) {
    return items;
  }

  const nextItems = [...items];
  const [item] = nextItems.splice(index, 1);
  nextItems.splice(nextIndex, 0, item);

  return normalizeTopicItemOrder(nextItems);
}

export function mergeAcceptedSuggestion(
  topic: Topic,
  item: TopicItem,
  suggestedProblemId: string,
): Topic {
  return {
    ...topic,
    items: normalizeTopicItemOrder([...topic.items, item]),
    suggestedProblems: removeSuggestedProblem(
      topic.suggestedProblems,
      suggestedProblemId,
    ),
  };
}

export function removeSuggestedProblem(
  suggestions: SuggestedProblem[],
  suggestedProblemId: string,
): SuggestedProblem[] {
  return suggestions.filter((item) => item.id !== suggestedProblemId);
}

function normalizeTopicItemOrder(items: TopicItem[]): TopicItem[] {
  return items.map((item, index) => ({
    ...item,
    order: index + 1,
  }));
}
