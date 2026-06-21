import { NextResponse } from "next/server";

import {
  DeleteTopicResponseSchema,
  PatchTopicRequestSchema,
  TopicResponseSchema,
} from "@/lib/contracts";
import { patchMockTopic } from "@/lib/mock/topic-management";

import { loadMockTopic } from "../_mock";

export async function PATCH(
  request: Request,
  context: { params: Promise<{ topicId: string }> },
) {
  const { topicId } = await context.params;
  const payload = PatchTopicRequestSchema.parse(await request.json());
  const topic = patchMockTopic(await loadMockTopic(topicId), payload);

  return NextResponse.json(TopicResponseSchema.parse({ topic }));
}

export async function DELETE(
  _request: Request,
  context: { params: Promise<{ topicId: string }> },
) {
  const { topicId } = await context.params;

  return NextResponse.json(DeleteTopicResponseSchema.parse({ topicId }));
}
