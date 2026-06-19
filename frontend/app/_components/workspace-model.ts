import type {
  NavResponse,
  Problem,
  PublishStatus,
  SiteHome,
  Topic,
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
