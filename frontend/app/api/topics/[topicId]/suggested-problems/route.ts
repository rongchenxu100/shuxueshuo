import { NextResponse } from "next/server";

import { TopicSuggestedProblemsResponseSchema } from "@/lib/contracts";

import { loadMockTopic } from "../../_mock";

export async function GET(
  _request: Request,
  context: { params: Promise<{ topicId: string }> },
) {
  const { topicId } = await context.params;
  const topic = await loadMockTopic(topicId);

  return NextResponse.json(
    TopicSuggestedProblemsResponseSchema.parse({
      suggestedProblems: topic.suggestedProblems,
    }),
  );
}
