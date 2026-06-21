import { NextResponse } from "next/server";

import {
  CreateTutorMessageRequestSchema,
  CreateTutorMessageResponseSchema,
  TutorMessagesResponseSchema,
} from "@/lib/contracts";
import {
  appendTutorMessage,
  getTutorMessages,
} from "@/lib/mock/tutor-store";

export async function GET(
  _request: Request,
  context: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await context.params;

  return NextResponse.json(
    TutorMessagesResponseSchema.parse(getTutorMessages(sessionId)),
  );
}

export async function POST(
  request: Request,
  context: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await context.params;
  const payload = CreateTutorMessageRequestSchema.parse(await request.json());

  return NextResponse.json(
    CreateTutorMessageResponseSchema.parse(
      appendTutorMessage(sessionId, payload),
    ),
  );
}
