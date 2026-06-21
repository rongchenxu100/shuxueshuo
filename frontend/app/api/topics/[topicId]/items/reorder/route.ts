import { NextResponse } from "next/server";

import {
  ReorderTopicItemsRequestSchema,
  TopicResponseSchema,
} from "@/lib/contracts";
import { reorderMockTopicItems } from "@/lib/mock/topic-management";

import { loadMockTopic } from "../../../_mock";

export async function PATCH(
  request: Request,
  context: { params: Promise<{ topicId: string }> },
) {
  const { topicId } = await context.params;
  const payload = ReorderTopicItemsRequestSchema.parse(await request.json());
  const topic = reorderMockTopicItems(
    await loadMockTopic(topicId),
    payload.itemIds,
  );

  return NextResponse.json(TopicResponseSchema.parse({ topic }));
}
