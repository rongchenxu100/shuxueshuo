import type { Problem, ProblemMessage } from "../contracts";
import { deriveProblemShortTitle } from "../problems/short-title";

const PREVIEW_URL = "/preview-fixtures/problems/hongqiao-25.html";

export function createMockProblemFromText(
  text: string,
  now = new Date(),
): { problem: Problem; initialMessage: ProblemMessage } {
  const normalizedText = text.trim();
  const timestamp = now.toISOString();
  const idSuffix = String(now.getTime());
  const title =
    normalizedText
      .split(/\n/)
      .find((line) => line.trim())
      ?.replace(/\s+/g, " ")
      .trim()
      .slice(0, 18) || "新建题目";
  const shortTitle = deriveProblemShortTitle(title);

  return {
    problem: {
      id: `problem_text_${idSuffix}`,
      title,
      shortTitle,
      status: "draft",
      defaultMode: "edit",
      canEdit: true,
      canTutor: true,
      subject: "math",
      tags: ["待分类"],
      updatedAt: timestamp,
      autosavedAt: timestamp,
      publicUrl: null,
      previewUrl: PREVIEW_URL,
      previewVersion: `mock-created-${idSuffix}`,
    },
    initialMessage: {
      id: `msg_text_${idSuffix}`,
      problemId: `problem_text_${idSuffix}`,
      role: "user",
      content: normalizedText,
      createdAt: timestamp,
    },
  };
}

export function createMockProblemFromUpload(now = new Date()): {
  problem: Problem;
  initialMessage: ProblemMessage;
} {
  const timestamp = now.toISOString();
  const idSuffix = String(now.getTime());
  const problemId = `problem_upload_${idSuffix}`;

  return {
    problem: {
      id: problemId,
      title: "上传生成的新题目",
      shortTitle: "上传生成的新题目",
      status: "draft",
      defaultMode: "edit",
      canEdit: true,
      canTutor: true,
      subject: "math",
      tags: ["待分类"],
      updatedAt: timestamp,
      autosavedAt: timestamp,
      publicUrl: null,
      previewUrl: PREVIEW_URL,
      previewVersion: `mock-created-${idSuffix}`,
    },
    initialMessage: {
      id: `msg_upload_${idSuffix}`,
      problemId,
      role: "user",
      content: "上传题目图片",
      attachments: [
        {
          id: `att_upload_${idSuffix}`,
          kind: "problem_image",
          url: `/uploads/${problemId}/original.jpg`,
          filename: "original.jpg",
          mimeType: "image/jpeg",
          createdAt: timestamp,
        },
      ],
      createdAt: timestamp,
    },
  };
}

export function patchMockProblem(
  problem: Problem,
  patch: { title?: string; tags?: string[] },
  now = new Date(),
): Problem {
  const timestamp = now.toISOString();
  const title = patch.title ?? problem.title;
  const shortTitle =
    patch.title === undefined
      ? problem.shortTitle
      : deriveProblemShortTitle(patch.title);

  return {
    ...problem,
    title,
    shortTitle,
    tags: patch.tags ?? problem.tags,
    status: problem.status === "published" ? "published_dirty" : problem.status,
    updatedAt: timestamp,
    autosavedAt: timestamp,
  };
}
