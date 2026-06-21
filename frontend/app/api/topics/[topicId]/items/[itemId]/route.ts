import { NextResponse } from "next/server";

import { DeleteTopicItemResponseSchema } from "@/lib/contracts";
import { removeMockTopicItem } from "@/lib/mock/topic-management";

import { loadMockTopic } from "../../../_mock";

export async function DELETE(
  _request: Request,
  context: { params: Promise<{ itemId: string; topicId: string }> },
) {
  const { itemId, topicId } = await context.params;
  const topic = removeMockTopicItem(await loadMockTopic(topicId), itemId);

  return NextResponse.json(
    DeleteTopicItemResponseSchema.parse({ itemId, topic }),
  );
}
