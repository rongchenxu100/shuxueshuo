import type { Problem, SiteHome, Topic } from "@/lib/contracts";
import { getCurrentUser } from "@/lib/user/current-user";

export function publishMockProblem(problem: Problem, now = new Date()) {
  if (problem.status === "published" && problem.publicUrl) {
    return problem;
  }

  const publicUrl =
    problem.publicUrl ?? makeUserPath("problems", slugFromId(problem.id));

  return {
    ...problem,
    autosavedAt: now.toISOString(),
    publicUrl,
    status: "published" as const,
    updatedAt: now.toISOString(),
  };
}

export function publishMockTopic(topic: Topic, now = new Date()) {
  if (topic.status === "published" && topic.publicUrl) {
    return topic;
  }

  const publicUrl =
    topic.publicUrl ?? makeUserPath("topics", slugFromId(topic.id));

  return {
    ...topic,
    autosavedAt: now.toISOString(),
    publicUrl,
    status: "published" as const,
    updatedAt: now.toISOString(),
  };
}

export function publishMockSiteHome(siteHome: SiteHome, now = new Date()) {
  if (siteHome.status === "published" && siteHome.publicUrl) {
    return siteHome;
  }

  const publicUrl = siteHome.publicUrl ?? makeUserHomePath();

  return {
    ...siteHome,
    autosavedAt: now.toISOString(),
    publicUrl,
    status: "published" as const,
  };
}

export function makeUserHomePath() {
  return `/users/${getCurrentUser().slug}/`;
}

export function makeUserPath(kind: "problems" | "topics", slug: string) {
  return `/users/${getCurrentUser().slug}/${kind}/${slug}/`;
}

export function slugFromId(id: string) {
  return id
    .replace(/^problem_/, "")
    .replace(/^topic_/, "")
    .replace(/_/g, "-")
    .toLowerCase();
}
