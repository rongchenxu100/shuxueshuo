import { NextResponse } from "next/server";

import {
  AddTopicItemRequestSchema,
  AddTopicItemResponseSchema,
} from "@/lib/contracts";
import { addMockTopicItem } from "@/lib/mock/topic-management";

import { loadMockTopic } from "../../_mock";

export async function POST(
  request: Request,
  context: { params: Promise<{ topicId: string }> },
) {
  const { topicId } = await context.params;
  const payload = AddTopicItemRequestSchema.parse(await request.json());
  const response = addMockTopicItem(await loadMockTopic(topicId), payload);

  return NextResponse.json(AddTopicItemResponseSchema.parse(response));
}
