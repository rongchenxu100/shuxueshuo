import { describe, expect, it } from "vitest";

import {
  GET as getTutorSessions,
  POST as createTutorSession,
} from "../problems/[problemId]/tutor-sessions/route";
import {
  GET as getTutorMessages,
  POST as createTutorMessage,
} from "./[sessionId]/messages/route";

function context<T extends Record<string, string>>(params: T) {
  return {
    params: Promise.resolve(params),
  };
}

function createPostRequest(body: unknown) {
  return new Request("http://localhost/api/tutor-sessions/session/messages", {
    body: JSON.stringify(body),
    headers: {
      "Content-Type": "application/json",
    },
    method: "POST",
  });
}

describe("tutor session routes", () => {
  it("creates and lists a tutor session for a problem", async () => {
    const createResponse = await createTutorSession(
      new Request(
        "http://localhost/api/problems/problem_hongqiao_25/tutor-sessions",
      ),
      context({ problemId: "problem_hongqiao_25" }),
    );
    const createPayload = await createResponse.json();

    expect(createPayload.session).toMatchObject({
      problemId: "problem_hongqiao_25",
      userId: "user_haorong",
    });

    const listResponse = await getTutorSessions(
      new Request(
        "http://localhost/api/problems/problem_hongqiao_25/tutor-sessions",
      ),
      context({ problemId: "problem_hongqiao_25" }),
    );
    const listPayload = await listResponse.json();

    expect(listPayload.sessions).toEqual([createPayload.session]);
  });

  it("appends tutor messages with contextual actions", async () => {
    const { session } = await (
      await createTutorSession(
        new Request(
          "http://localhost/api/problems/problem_hongqiao_25/tutor-sessions",
        ),
        context({ problemId: "problem_hongqiao_25" }),
      )
    ).json();

    const response = await createTutorMessage(
      createPostRequest({
        content: "为什么这里要构造 B₁？",
        currentStepId: "q2s4",
        selectedTargetId: "step.q2s4.figure",
      }),
      context({ sessionId: session.id }),
    );
    const payload = await response.json();

    expect(payload).not.toHaveProperty("problem");
    expect(payload).not.toHaveProperty("preview");
    expect(payload.messages).toHaveLength(2);
    expect(payload.messages[0]).toMatchObject({
      content: "为什么这里要构造 B₁？",
      role: "user",
      selectedTargetId: "step.q2s4.figure",
    });
    expect(payload.messages[1].actions).toEqual(
      expect.arrayContaining([
        { stepId: "q2s4", type: "scroll_to_step" },
        { targetId: "step.q2s4.figure", type: "highlight_target" },
        expect.objectContaining({ type: "show_hint" }),
      ]),
    );

    const historyResponse = await getTutorMessages(
      new Request(
        `http://localhost/api/tutor-sessions/${session.id}/messages`,
      ),
      context({ sessionId: session.id }),
    );
    const historyPayload = await historyResponse.json();

    expect(historyPayload.messages.length).toBeGreaterThanOrEqual(2);
  });

  it("rejects empty tutor message content", async () => {
    const { session } = await (
      await createTutorSession(
        new Request(
          "http://localhost/api/problems/problem_heping_24/tutor-sessions",
        ),
        context({ problemId: "problem_heping_24" }),
      )
    ).json();

    await expect(() =>
      createTutorMessage(
        createPostRequest({ content: "" }),
        context({ sessionId: session.id }),
      ),
    ).rejects.toThrow();
  });
});
