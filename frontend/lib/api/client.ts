import {
  NavResponseSchema,
  type NavResponse,
  type Problem,
  type SiteHome,
  type Topic,
} from "@/lib/contracts";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  (typeof window === "undefined"
    ? process.env.VERCEL_URL
      ? `https://${process.env.VERCEL_URL}`
      : `http://localhost:${process.env.PORT ?? "3000"}`
    : "");

async function fetchJson(path: string): Promise<unknown> {
  const response = await fetch(`${BASE_URL}${path}`);

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

export async function getNav(): Promise<NavResponse> {
  return NavResponseSchema.parse(await fetchJson("/api/nav"));
}

export async function getProblem(problemId: string): Promise<Problem> {
  void problemId;
  throw new Error("getProblem is not implemented in Phase 0");
}

export async function getTopic(topicId: string): Promise<Topic> {
  void topicId;
  throw new Error("getTopic is not implemented in Phase 0");
}

export async function getSiteHome(): Promise<SiteHome> {
  throw new Error("getSiteHome is not implemented in Phase 0");
}
