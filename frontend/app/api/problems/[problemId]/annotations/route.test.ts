import { beforeEach, describe, expect, it } from "vitest";

import { resetMockAnnotationStore } from "@/lib/mock/annotation-store";
import { GET, POST } from "./route";

function createContext(problemId: string) {
  return {
    params: Promise.resolve({ problemId }),
  };
}

function createPostRequest() {
  return new Request("http://localhost/api/problems/problem/annotations", {
    body: JSON.stringify({
      comment: "把这里的填充加深",
      label: "第4步 · 图形",
      stepId: "q2s4",
      targetId: "step.q2s4.figure",
      targetType: "step_figure",
    }),
    headers: {
      "Content-Type": "application/json",
    },
    method: "POST",
  });
}

describe("problem annotations route", () => {
  beforeEach(() => {
    resetMockAnnotationStore();
  });

  it("returns fixture annotations for existing fixtures", async () => {
    const response = await GET(
      new Request(
        "http://localhost/api/problems/problem_hongqiao_25/annotations",
      ),
      createContext("problem_hongqiao_25"),
    );
    const payload = await response.json();

    expect(payload.annotations.length).toBeGreaterThan(0);
    expect(payload.annotations[0]).toMatchObject({
      problemId: "problem_hongqiao_25",
      targetId: "step.q2s4.figure",
    });
  });

  it("returns an empty list for unknown problems", async () => {
    const response = await GET(
      new Request("http://localhost/api/problems/problem_new/annotations"),
      createContext("problem_new"),
    );
    const payload = await response.json();

    expect(payload.annotations).toEqual([]);
  });

  it("creates annotations in the runtime mock store", async () => {
    const postResponse = await POST(
      createPostRequest(),
      createContext("problem_new"),
    );
    const postPayload = await postResponse.json();
    const getResponse = await GET(
      new Request("http://localhost/api/problems/problem_new/annotations"),
      createContext("problem_new"),
    );
    const getPayload = await getResponse.json();

    expect(postPayload.annotation).toMatchObject({
      comment: "把这里的填充加深",
      problemId: "problem_new",
      targetId: "step.q2s4.figure",
    });
    expect(getPayload.annotations).toEqual([postPayload.annotation]);
  });
});
