import { NextResponse } from "next/server";

import {
  CreateTopicRequestSchema,
  TopicResponseSchema,
} from "@/lib/contracts";
import { createMockTopic } from "@/lib/mock/topic-management";

export async function POST(request: Request) {
  const payload = CreateTopicRequestSchema.parse(await request.json());
  const topic = createMockTopic(payload);

  return NextResponse.json(TopicResponseSchema.parse({ topic }));
}
