import { NextResponse } from "next/server";

import {
  CreateTutorSessionResponseSchema,
  TutorSessionsResponseSchema,
} from "@/lib/contracts";
import {
  ensureTutorSession,
  listTutorSessions,
} from "@/lib/mock/tutor-store";

export async function GET(
  _request: Request,
  context: { params: Promise<{ problemId: string }> },
) {
  const { problemId } = await context.params;

  return NextResponse.json(
    TutorSessionsResponseSchema.parse({
      sessions: listTutorSessions(problemId),
    }),
  );
}

export async function POST(
  _request: Request,
  context: { params: Promise<{ problemId: string }> },
) {
  const { problemId } = await context.params;

  return NextResponse.json(
    CreateTutorSessionResponseSchema.parse({
      session: ensureTutorSession(problemId),
    }),
  );
}
