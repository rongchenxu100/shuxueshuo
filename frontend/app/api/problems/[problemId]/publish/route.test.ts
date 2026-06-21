import { describe, expect, it } from "vitest";

import { POST } from "./route";

function createContext(problemId: string) {
  return {
    params: Promise.resolve({ problemId }),
  };
}

describe("problem publish route", () => {
  it("publishes a draft problem and creates a public URL", async () => {
    const response = await POST(
      new Request("http://localhost/api/problems/problem_heping_25/publish", {
        method: "POST",
      }),
      createContext("problem_heping_25"),
    );
    const payload = await response.json();

    expect(payload.problem.status).toBe("published");
    expect(payload.problem.publicUrl).toBe(
      "/users/haorong/problems/heping-25/",
    );
    expect(payload.publicUrl).toBe(payload.problem.publicUrl);
  });

  it("publishes dirty changes without changing an existing public URL", async () => {
    const response = await POST(
      new Request("http://localhost/api/problems/problem_hongqiao_25/publish", {
        method: "POST",
      }),
      createContext("problem_hongqiao_25"),
    );
    const payload = await response.json();

    expect(payload.problem.status).toBe("published");
    expect(payload.problem.publicUrl).toBe(
      "/users/haorong/problems/tj-2026-hongqiao-sanmo-25/",
    );
  });

  it("keeps an already published problem idempotent", async () => {
    const response = await POST(
      new Request("http://localhost/api/problems/problem_heping_24/publish", {
        method: "POST",
      }),
      createContext("problem_heping_24"),
    );
    const payload = await response.json();

    expect(payload.problem.status).toBe("published");
    expect(payload.problem.updatedAt).toBe("2026-06-15T10:00:00.000Z");
  });

  it("publishes a session-created mock problem", async () => {
    const response = await POST(
      new Request("http://localhost/api/problems/problem_text_123/publish", {
        method: "POST",
      }),
      createContext("problem_text_123"),
    );
    const payload = await response.json();

    expect(payload.problem.status).toBe("published");
    expect(payload.publicUrl).toBe("/users/haorong/problems/text-123/");
  });
});
