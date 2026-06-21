import { NextResponse } from "next/server";

import {
  ApiErrorSchema,
  NavResponseSchema,
  ProblemSchema,
  PublishProblemResponseSchema,
  type Problem,
} from "@/lib/contracts";
import { loadFixture } from "@/lib/mock/load-fixture";
import { publishMockProblem } from "@/lib/mock/publish";

export async function POST(
  _request: Request,
  context: { params: Promise<{ problemId: string }> },
) {
  const { problemId } = await context.params;
  const nav = NavResponseSchema.parse(await loadFixture("nav.json"));
  const problem =
    nav.problems.find((item) => item.id === problemId) ??
    loadSessionProblemFallback(problemId);

  if (!problem) {
    return NextResponse.json(
      ApiErrorSchema.parse({
        error: {
          code: "problem_not_found",
          message: "没有找到这个题目。",
          retryable: false,
        },
      }),
      { status: 404 },
    );
  }

  const publishedProblem = publishMockProblem(problem);

  return NextResponse.json(
    PublishProblemResponseSchema.parse({
      problem: publishedProblem,
      publicUrl: publishedProblem.publicUrl,
    }),
  );
}

function loadSessionProblemFallback(problemId: string): Problem | null {
  if (
    !problemId.startsWith("problem_text_") &&
    !problemId.startsWith("problem_upload_")
  ) {
    return null;
  }

  const timestamp = new Date().toISOString();

  return ProblemSchema.parse({
    autosavedAt: timestamp,
    canEdit: true,
    canTutor: true,
    defaultMode: "edit",
    id: problemId,
    previewUrl: "/preview-fixtures/problems/hongqiao-25.html",
    previewVersion: `mock-published-${Date.now()}`,
    publicUrl: null,
    shortTitle: "新建题目",
    status: "draft",
    subject: "math",
    tags: ["待分类"],
    title: "新建题目",
    updatedAt: timestamp,
  });
}
