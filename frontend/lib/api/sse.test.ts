import { describe, expect, it } from "vitest";

import problemFixture from "../../fixtures/problems/hongqiao-25.json";
import messageFixture from "../../fixtures/messages/hongqiao-25.json";
import { formatSseEvent, parseUploadJobEvent } from "./sse";

describe("upload job SSE helpers", () => {
  it("parses progress events by injecting the SSE event name", () => {
    expect(
      parseUploadJobEvent(
        "progress",
        JSON.stringify({ stage: "stored", message: "图片已上传" }),
      ),
    ).toEqual({
      type: "progress",
      stage: "stored",
      message: "图片已上传",
    });
  });

  it("parses terminal done events", () => {
    const event = parseUploadJobEvent(
      "done",
      JSON.stringify({
        result: "created",
        problem: problemFixture,
        initialMessage: messageFixture[0],
      }),
    );

    expect(event.type).toBe("done");
  });

  it("parses rejected and failed events", () => {
    expect(
      parseUploadJobEvent(
        "rejected",
        JSON.stringify({ message: "没有识别到完整题目" }),
      ),
    ).toEqual({
      type: "rejected",
      message: "没有识别到完整题目",
    });
    expect(
      parseUploadJobEvent(
        "failed",
        JSON.stringify({
          error: {
            code: "mock_generation_failed",
            message: "生成失败",
            retryable: true,
          },
        }),
      ),
    ).toEqual({
      type: "failed",
      error: {
        code: "mock_generation_failed",
        message: "生成失败",
        retryable: true,
      },
    });
  });

  it("formats SSE events", () => {
    expect(formatSseEvent("progress", { message: "ok" })).toBe(
      'event: progress\ndata: {"message":"ok"}\n\n',
    );
  });
});
