import { NextResponse } from "next/server";

import {
  ApiErrorSchema,
  NavResponseSchema,
  PublishTopicResponseSchema,
} from "@/lib/contracts";
import { loadFixture } from "@/lib/mock/load-fixture";
import { publishMockTopic } from "@/lib/mock/publish";

export async function POST(
  _request: Request,
  context: { params: Promise<{ topicId: string }> },
) {
  const { topicId } = await context.params;
  const nav = NavResponseSchema.parse(await loadFixture("nav.json"));
  const topic = nav.topics.find((item) => item.id === topicId);

  if (!topic) {
    return NextResponse.json(
      ApiErrorSchema.parse({
        error: {
          code: "topic_not_found",
          message: "没有找到这个专题。",
          retryable: false,
        },
      }),
      { status: 404 },
    );
  }

  const publishedTopic = publishMockTopic(topic);

  return NextResponse.json(
    PublishTopicResponseSchema.parse({
      publicUrl: publishedTopic.publicUrl,
      topic: publishedTopic,
    }),
  );
}
