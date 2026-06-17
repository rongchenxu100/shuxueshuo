import { describe, expect, it } from "vitest";
import { z } from "zod";

import {
  NavResponseSchema,
  ProblemSchema,
  ProblemMessageSchema,
  SiteHomeSchema,
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
});
