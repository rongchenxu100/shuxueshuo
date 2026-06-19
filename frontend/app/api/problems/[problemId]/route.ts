import { NextResponse } from "next/server";

import {
  ApiErrorSchema,
  NavResponseSchema,
  PatchProblemRequestSchema,
  PatchProblemResponseSchema,
  ProblemSchema,
  type Problem,
} from "@/lib/contracts";
import { patchMockProblem } from "@/lib/mock/problem-factory";
import { loadFixture } from "@/lib/mock/load-fixture";

export async function PATCH(
  request: Request,
  context: { params: Promise<{ problemId: string }> },
) {
  const { problemId } = await context.params;
  const payload = PatchProblemRequestSchema.parse(await request.json());

  if (payload.patch.title?.includes("[conflict]")) {
    const error = ApiErrorSchema.parse({
      error: {
        code: "autosave_conflict",
        message: "这个题目已在其他窗口被更新，请刷新后再继续编辑。",
        retryable: false,
      },
    });

    return NextResponse.json(error, { status: 409 });
  }

  const problem = await loadPatchProblem(problemId);

  if (!problem) {
    const error = ApiErrorSchema.parse({
      error: {
        code: "problem_not_found",
        message: "没有找到这个题目。",
        retryable: false,
      },
    });

    return NextResponse.json(error, { status: 404 });
  }

  const response = PatchProblemResponseSchema.parse({
    problem: patchMockProblem(
      {
        ...problem,
        id: problemId,
        autosavedAt: payload.expectedAutosavedAt,
      },
      payload.patch,
    ),
  });

  return NextResponse.json(response);
}

async function loadPatchProblem(problemId: string): Promise<Problem | null> {
  const nav = NavResponseSchema.parse(await loadFixture("nav.json"));
  const navProblem = nav.problems.find((problem) => problem.id === problemId);

  if (navProblem) {
    return navProblem;
  }

  if (
    problemId.startsWith("problem_text_") ||
    problemId.startsWith("problem_upload_")
  ) {
    const timestamp = new Date().toISOString();

    return ProblemSchema.parse({
      autosavedAt: timestamp,
      canEdit: true,
      canTutor: true,
      defaultMode: "edit",
      id: problemId,
      previewUrl: "/preview-fixtures/problems/hongqiao-25.html",
      previewVersion: `mock-patched-${Date.now()}`,
      publicUrl: null,
      shortTitle: "新建题目",
      status: "draft",
      subject: "math",
      tags: ["待分类"],
      title: "新建题目",
      updatedAt: timestamp,
    });
  }

  return null;
}
