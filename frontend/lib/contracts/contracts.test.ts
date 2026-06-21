import { describe, expect, it } from "vitest";
import { z } from "zod";

import {
  AcceptSuggestedProblemResponseSchema,
  AddTopicItemRequestSchema,
  AddTopicItemResponseSchema,
  CreateWebAnnotationRequestSchema,
  CreateWebAnnotationResponseSchema,
  CreateProblemRequestSchema,
  CreateProblemResponseSchema,
  CreateProblemMessageRequestSchema,
  CreateTopicRequestSchema,
  CreateTutorMessageRequestSchema,
  CreateTutorMessageResponseSchema,
  CreateTutorSessionResponseSchema,
  DeleteTopicItemResponseSchema,
  DeleteTopicResponseSchema,
  IgnoreSuggestedProblemResponseSchema,
  CreateProblemMessageResponseSchema,
  NavResponseSchema,
  PatchProblemRequestSchema,
  PatchProblemResponseSchema,
  PatchSiteHomeRequestSchema,
  PatchSiteHomeResponseSchema,
  PatchTopicRequestSchema,
  ProblemSchema,
  ProblemAnnotationsResponseSchema,
  ProblemMessageSchema,
  ProblemMessagesResponseSchema,
  PublishProblemResponseSchema,
  PublishSiteHomeResponseSchema,
  PublishTopicResponseSchema,
  ReorderTopicItemsRequestSchema,
  SiteHomeSchema,
  StartProblemUploadResponseSchema,
  TopicResponseSchema,
  TopicSuggestedProblemsResponseSchema,
  TopicSchema,
  TutorActionSchema,
  TutorMessagesResponseSchema,
  TutorSessionsResponseSchema,
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

  it("validates publish response contracts", () => {
    expect(() =>
      PublishProblemResponseSchema.parse({
        problem: {
          ...problemFixture,
          publicUrl: "/users/haorong/problems/tj-2026-hongqiao-sanmo-25/",
          status: "published",
        },
        publicUrl: "/users/haorong/problems/tj-2026-hongqiao-sanmo-25/",
      }),
    ).not.toThrow();
    expect(() =>
      PublishTopicResponseSchema.parse({
        publicUrl: "/users/haorong/topics/tianjin-sanmo-25/",
        topic: {
          ...topicFixture,
          publicUrl: "/users/haorong/topics/tianjin-sanmo-25/",
          status: "published",
        },
      }),
    ).not.toThrow();
    expect(() =>
      PublishSiteHomeResponseSchema.parse({
        publicUrl: "/users/haorong/",
        siteHome: {
          ...siteHomeFixture,
          publicUrl: "/users/haorong/",
          status: "published",
        },
      }),
    ).not.toThrow();
  });

  it("validates topic management contracts", () => {
    const [topicItem] = topicFixture.items;
    const [suggestion] = topicFixture.suggestedProblems;

    expect(() =>
      CreateTopicRequestSchema.parse({
        description: "整理几何专题",
        title: "几何专题",
      }),
    ).not.toThrow();
    expect(() =>
      PatchTopicRequestSchema.parse({
        patch: {
          description: "新的说明",
          title: "新的专题",
        },
      }),
    ).not.toThrow();
    expect(() => TopicResponseSchema.parse({ topic: topicFixture }))
      .not.toThrow();
    expect(() =>
      DeleteTopicResponseSchema.parse({ topicId: topicFixture.id }),
    ).not.toThrow();
    expect(() =>
      AddTopicItemRequestSchema.parse({
        problemId: "problem_hexi_25",
        status: "draft",
        tags: ["二次函数综合"],
        title: "河西三模 25题",
      }),
    ).not.toThrow();
    expect(() =>
      AddTopicItemResponseSchema.parse({
        item: topicItem,
        topic: topicFixture,
      }),
    ).not.toThrow();
    expect(() =>
      ReorderTopicItemsRequestSchema.parse({ itemIds: [topicItem.id] }),
    ).not.toThrow();
    expect(() =>
      DeleteTopicItemResponseSchema.parse({
        itemId: topicItem.id,
        topic: topicFixture,
      }),
    ).not.toThrow();
    expect(() =>
      TopicSuggestedProblemsResponseSchema.parse({
        suggestedProblems: topicFixture.suggestedProblems,
      }),
    ).not.toThrow();
    expect(() =>
      AcceptSuggestedProblemResponseSchema.parse({
        item: topicItem,
        topic: topicFixture,
      }),
    ).not.toThrow();
    expect(() =>
      IgnoreSuggestedProblemResponseSchema.parse({
        suggestedProblemId: suggestion.id,
        topic: topicFixture,
      }),
    ).not.toThrow();
  });

  it("validates site home management contracts", () => {
    expect(() =>
      PatchSiteHomeRequestSchema.parse({
        patch: {
          featuredTopicIds: ["topic_tianjin_sanmo_25"],
          knowledgeTags: ["二次函数"],
          recentProblemLimit: 6,
          siteName: "数学可视化题库",
        },
      }),
    ).not.toThrow();
    expect(() =>
      PatchSiteHomeResponseSchema.parse({ siteHome: siteHomeFixture }),
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

  it("validates tutor mode contracts", () => {
    const session = {
      createdAt: "2026-06-16T09:00:00.000Z",
      currentStepId: "q2s4",
      id: "tutor_session_problem_hongqiao_25_user_haorong",
      problemId: "problem_hongqiao_25",
      title: "学习对话",
      updatedAt: "2026-06-16T09:00:00.000Z",
      userId: "user_haorong",
    };
    const messages = [
      {
        content: "为什么这里要构造 B₁？",
        createdAt: "2026-06-16T09:00:00.000Z",
        currentStepId: "q2s4",
        id: "tmsg_user_1",
        role: "user",
        selectedTargetId: "step.q2s4.figure",
        sessionId: session.id,
      },
      {
        actions: [
          { stepId: "q2s4", type: "scroll_to_step" },
          { targetId: "step.q2s4.figure", type: "highlight_target" },
          { text: "先看等量关系。", type: "show_hint" },
        ],
        content: "我会结合你选中的网页区域来解释。",
        createdAt: "2026-06-16T09:00:00.000Z",
        id: "tmsg_assistant_1",
        role: "assistant",
        sessionId: session.id,
      },
    ];

    expect(() =>
      TutorSessionsResponseSchema.parse({ sessions: [session] }),
    ).not.toThrow();
    expect(() =>
      CreateTutorSessionResponseSchema.parse({ session }),
    ).not.toThrow();
    expect(() =>
      TutorMessagesResponseSchema.parse({ messages, session }),
    ).not.toThrow();
    expect(() =>
      CreateTutorMessageRequestSchema.parse({
        content: "为什么这里要构造 B₁？",
        currentStepId: "q2s4",
        pageState: {
          scrollY: 1280,
          sliderValues: {},
        },
        selectedTargetId: "step.q2s4.figure",
      }),
    ).not.toThrow();
    expect(() =>
      CreateTutorMessageRequestSchema.parse({ content: "" }),
    ).toThrow();
    expect(() =>
      CreateTutorMessageResponseSchema.parse({ messages, session }),
    ).not.toThrow();
    expect(() =>
      TutorActionSchema.parse({
        targetId: "step.q2s4.figure",
        type: "highlight_target",
      }),
    ).not.toThrow();
  });
});
