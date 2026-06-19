import {
  CreateProblemResponseSchema,
  NavResponseSchema,
  PatchProblemResponseSchema,
  StartProblemUploadResponseSchema,
  type NavResponse,
  type PatchProblemRequest,
} from "@/lib/contracts";

type MockProblemScenario = "success" | "rejected" | "failed" | "disconnect";

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

async function fetchJsonWithInit(
  path: string,
  init: RequestInit,
): Promise<unknown> {
  const response = await fetch(`${BASE_URL}${path}`, init);

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const message =
      typeof payload === "object" &&
      payload !== null &&
      "error" in payload &&
      typeof payload.error === "object" &&
      payload.error !== null &&
      "message" in payload.error
        ? String(payload.error.message)
        : `Request failed: ${response.status} ${response.statusText}`;
    const error = new Error(message);
    error.name = response.status === 409 ? "AutosaveConflictError" : "ApiError";
    throw error;
  }

  return response.json();
}

export async function getNav(): Promise<NavResponse> {
  return NavResponseSchema.parse(await fetchJson("/api/nav"));
}

export async function createProblemFromText(input: {
  text: string;
}, options?: { mockScenario?: MockProblemScenario }) {
  const headers = new Headers({
    "Content-Type": "application/json",
  });

  if (options?.mockScenario) {
    headers.set("x-mock-scenario", options.mockScenario);
  }

  return CreateProblemResponseSchema.parse(
    await fetchJsonWithInit("/api/problems", {
      body: JSON.stringify(input),
      headers,
      method: "POST",
    }),
  );
}

export async function startProblemUpload(formData: FormData) {
  return StartProblemUploadResponseSchema.parse(
    await fetchJsonWithInit("/api/problems/from-upload", {
      body: formData,
      method: "POST",
    }),
  );
}

export async function patchProblem(
  problemId: string,
  request: PatchProblemRequest,
) {
  return PatchProblemResponseSchema.parse(
    await fetchJsonWithInit(`/api/problems/${problemId}`, {
      body: JSON.stringify(request),
      headers: {
        "Content-Type": "application/json",
      },
      method: "PATCH",
    }),
  );
}
