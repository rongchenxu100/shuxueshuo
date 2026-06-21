import { describe, expect, it } from "vitest";

import { GET, POST } from "./route";

function createContext(problemId: string) {
  return {
    params: Promise.resolve({ problemId }),
  };
}

function createPostRequest(content: string, annotationIds?: string[]) {
  return new Request("http://localhost/api/problems/problem/messages", {
    body: JSON.stringify({ annotationIds, content }),
    headers: {
      "Content-Type": "application/json",
    },
    method: "POST",
  });
}

describe("problem messages route", () => {
  it("returns fixture messages for existing fixtures", async () => {
    const response = await GET(
      new Request("http://localhost/api/problems/problem_hongqiao_25/messages"),
      createContext("problem_hongqiao_25"),
    );
    const payload = await response.json();

    expect(payload.messages.length).toBeGreaterThan(0);
    expect(payload.messages[0]).toMatchObject({
      problemId: "problem_hongqiao_25",
      role: "user",
    });
  });

  it("marks published problems as published_dirty", async () => {
    const response = await POST(
      createPostRequest("把第4步图形填充更明显"),
      createContext("problem_heping_24"),
    );
    const payload = await response.json();

    expect(payload.problem.status).toBe("published_dirty");
    expect(payload.messages).toHaveLength(2);
    expect(payload.messages[1]).toMatchObject({
      content: "已按要求更新网页预览。",
      role: "assistant",
    });
  });

  it("keeps draft problems as draft", async () => {
    const response = await POST(
      createPostRequest("调整讲解语气"),
      createContext("problem_heping_25"),
    );
    const payload = await response.json();

    expect(payload.problem.status).toBe("draft");
  });

  it("changes previewVersion on each edit", async () => {
    const firstResponse = await POST(
      createPostRequest("第一次修改"),
      createContext("problem_heping_24"),
    );
    const secondResponse = await POST(
      createPostRequest("第二次修改"),
      createContext("problem_heping_24"),
    );
    const firstPayload = await firstResponse.json();
    const secondPayload = await secondResponse.json();

    expect(firstPayload.preview.previewUrl).toBe(secondPayload.preview.previewUrl);
    expect(firstPayload.preview.previewVersion).not.toBe(
      secondPayload.preview.previewVersion,
    );
  });

  it("attaches annotation context to edit messages", async () => {
    const response = await POST(
      createPostRequest("按这条注释调整", ["ann_1"]),
      createContext("problem_hongqiao_25"),
    );
    const payload = await response.json();

    expect(payload.messages[0].annotations).toHaveLength(1);
    expect(payload.messages[0].annotations[0]).toMatchObject({
      id: "ann_1",
      targetId: "step.q2s4.figure",
    });
    expect(payload.messages[1]).toMatchObject({
      content: "已按 1 条注释更新网页预览。",
      role: "assistant",
    });
  });
});
