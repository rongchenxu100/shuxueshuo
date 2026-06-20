import { NextResponse } from "next/server";

import {
  CreateProblemMessageRequestSchema,
  CreateProblemMessageResponseSchema,
  NavResponseSchema,
  ProblemMessagesResponseSchema,
  type Problem,
  type ProblemMessage,
} from "@/lib/contracts";
import { loadFixture } from "@/lib/mock/load-fixture";

// Mock-only runtime state for producing visibly changing preview versions.
// Next.js dev hot reload may reset this counter, which is fine for fixtures.
let mockEditRun = 0;

export async function GET(
  _request: Request,
  context: { params: Promise<{ problemId: string }> },
) {
  const { problemId } = await context.params;
  const messages = await loadMessages(problemId);

  return NextResponse.json(ProblemMessagesResponseSchema.parse({ messages }));
}

export async function POST(
  request: Request,
  context: { params: Promise<{ problemId: string }> },
) {
  const { problemId } = await context.params;
  const payload = CreateProblemMessageRequestSchema.parse(await request.json());
  const now = new Date();
  const timestamp = now.toISOString();
  const idSuffix = `${now.getTime()}_${mockEditRun++}`;
  const problem = await loadProblem(problemId, now);
  const previewVersion = `mock-edited-${idSuffix}`;
  const userMessage: ProblemMessage = {
    content: payload.content,
    createdAt: timestamp,
    id: `msg_user_${idSuffix}`,
    problemId,
    role: "user",
  };
  const assistantMessage: ProblemMessage = {
    content: "已按要求更新网页预览。",
    createdAt: timestamp,
    id: `msg_assistant_${idSuffix}`,
    problemId,
    role: "assistant",
  };
  const updatedProblem: Problem = {
    ...problem,
    autosavedAt: timestamp,
    previewVersion,
    status:
      problem.status === "published" ? "published_dirty" : problem.status,
    updatedAt: timestamp,
  };

  return NextResponse.json(
    CreateProblemMessageResponseSchema.parse({
      messages: [userMessage, assistantMessage],
      preview: {
        previewUrl: updatedProblem.previewUrl,
        previewVersion,
      },
      problem: updatedProblem,
    }),
  );
}

async function loadMessages(problemId: string): Promise<ProblemMessage[]> {
  if (problemId === "problem_hongqiao_25") {
    return ProblemMessagesResponseSchema.parse({
      messages: await loadFixture("messages/hongqiao-25.json"),
    }).messages;
  }

  return [];
}

async function loadProblem(problemId: string, now: Date): Promise<Problem> {
  const nav = NavResponseSchema.parse(await loadFixture("nav.json"));
  const navProblem = nav.problems.find((problem) => problem.id === problemId);

  if (navProblem) {
    return navProblem;
  }

  const timestamp = now.toISOString();

  return {
    autosavedAt: timestamp,
    canEdit: true,
    canTutor: true,
    defaultMode: "edit",
    id: problemId,
    previewUrl: "/preview-fixtures/problems/hongqiao-25.html",
    previewVersion: `mock-created-${now.getTime()}`,
    publicUrl: null,
    shortTitle: "新建题目",
    status: "draft",
    subject: "math",
    tags: ["待分类"],
    title: "新建题目",
    updatedAt: timestamp,
  };
}
