import { describe, expect, it } from "vitest";
import { z } from "zod";

import {
  CreateWebAnnotationRequestSchema,
  CreateWebAnnotationResponseSchema,
  CreateProblemRequestSchema,
  CreateProblemResponseSchema,
  CreateProblemMessageRequestSchema,
  CreateProblemMessageResponseSchema,
  NavResponseSchema,
  PatchProblemRequestSchema,
  PatchProblemResponseSchema,
  ProblemSchema,
  ProblemAnnotationsResponseSchema,
  ProblemMessageSchema,
  ProblemMessagesResponseSchema,
  SiteHomeSchema,
  StartProblemUploadResponseSchema,
  TopicSchema,
  WebAnnotationSchema,
} from "./index";
import annotationsFixture from "../../fixtures/annotations/hongqiao-25.json";
import messagesFixture from "../../fixtures/messages/hongqiao-25.json";
import navFixture from "../../fixtures/nav.json";
import hepingProblemFixture from "../../fixtures/problems/heping-24.json";
import problemFixture from "../../fixtures/problems/hongqiao-25.json";
import siteHomeFixture from "../../fixtures/site-home.json";
import topicFixture from "../../fixtures/topics/tianjin-sanmo-25.json";

describe("contract fixtures", () => {
  it("validates nav fixture", () => {
    expect(() => NavResponseSchema.parse(navFixture)).not.toThrow();
  });

  it("validates problem fixture", () => {
    expect(() => ProblemSchema.parse(problemFixture)).not.toThrow();
  });

  it("validates nav-listed placeholder problem fixture", () => {
    expect(() => ProblemSchema.parse(hepingProblemFixture)).not.toThrow();
  });

  it("validates topic fixture", () => {
    expect(() => TopicSchema.parse(topicFixture)).not.toThrow();
  });

  it("keeps topic previewVersion available when present", () => {
    const topic = TopicSchema.parse(topicFixture);

    expect(topic.previewVersion).toBe("mock-1");
  });

  it("validates messages fixture", () => {
    expect(() =>
      z.array(ProblemMessageSchema).parse(messagesFixture),
    ).not.toThrow();
  });

  it("validates annotations fixture", () => {
    expect(() =>
      z.array(WebAnnotationSchema).parse(annotationsFixture),
    ).not.toThrow();
  });

  it("validates problem annotation contracts", () => {
    expect(() =>
      ProblemAnnotationsResponseSchema.parse({
        annotations: annotationsFixture,
      }),
    ).not.toThrow();
    expect(() =>
      CreateWebAnnotationRequestSchema.parse({
        comment: "这个图形填充更明显",
        label: "第4步 · 图形",
        stepId: "q2s4",
        targetId: "step.q2s4.figure",
        targetType: "step_figure",
      }),
    ).not.toThrow();
    expect(() =>
      CreateWebAnnotationRequestSchema.parse({
        comment: "",
        label: "第4步 · 图形",
        targetId: "step.q2s4.figure",
        targetType: "step_figure",
      }),
    ).toThrow();
    expect(() =>
      CreateWebAnnotationResponseSchema.parse({
        annotation: annotationsFixture[0],
      }),
    ).not.toThrow();
  });

  it("validates site home fixture", () => {
    expect(() => SiteHomeSchema.parse(siteHomeFixture)).not.toThrow();
  });

  it("rejects a problem fixture without previewVersion", () => {
    const invalidProblem: Partial<typeof problemFixture> = {
      ...problemFixture,
    };
    delete invalidProblem.previewVersion;

    expect(() => ProblemSchema.parse(invalidProblem)).toThrow();
  });

  it("validates create problem contracts", () => {
    expect(() =>
      CreateProblemRequestSchema.parse({ text: "一道新题" }),
    ).not.toThrow();
    expect(() =>
      CreateProblemRequestSchema.parse({
        scenario: "failed",
        text: "一道新题",
      }),
    ).toThrow();
    expect(() =>
      CreateProblemResponseSchema.parse({
        problem: problemFixture,
        initialMessage: messagesFixture[0],
      }),
    ).not.toThrow();
  });

  it("validates upload start contract", () => {
    expect(() =>
      StartProblemUploadResponseSchema.parse({
        jobId: "job_upload_1",
        streamUrl: "/api/problem-upload-jobs/job_upload_1/events",
      }),
    ).not.toThrow();
  });

  it("validates patch problem contracts", () => {
    expect(() =>
      PatchProblemRequestSchema.parse({
        expectedAutosavedAt: "2026-06-16T09:00:00.000Z",
        patch: {
          title: "新标题",
          tags: ["二次函数综合"],
        },
      }),
    ).not.toThrow();
    expect(() =>
      PatchProblemResponseSchema.parse({ problem: problemFixture }),
    ).not.toThrow();
  });

  it("validates problem edit message contracts", () => {
    expect(() =>
      ProblemMessagesResponseSchema.parse({ messages: messagesFixture }),
    ).not.toThrow();
    expect(() =>
      CreateProblemMessageRequestSchema.parse({
        annotationIds: ["ann_1"],
        content: "把第4步图形填充更明显",
      }),
    ).not.toThrow();
    expect(() =>
      CreateProblemMessageRequestSchema.parse({ content: "" }),
    ).toThrow();
    expect(() =>
      CreateProblemMessageResponseSchema.parse({
        messages: [
          messagesFixture[0],
          {
            content: "已按要求更新网页预览。",
            createdAt: "2026-06-16T09:00:00.000Z",
            id: "msg_assistant_mock",
            problemId: "problem_hongqiao_25",
            role: "assistant",
          },
        ],
        preview: {
          previewUrl: problemFixture.previewUrl,
          previewVersion: "mock-edited-1",
        },
        problem: {
          ...problemFixture,
          previewVersion: "mock-edited-1",
          status: "published_dirty",
        },
      }),
    ).not.toThrow();
  });
});
