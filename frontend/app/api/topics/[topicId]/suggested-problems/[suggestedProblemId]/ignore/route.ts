import { NextResponse } from "next/server";

import { IgnoreSuggestedProblemResponseSchema } from "@/lib/contracts";
import { ignoreMockSuggestedProblem } from "@/lib/mock/topic-management";

import { loadMockTopic } from "../../../../_mock";

export async function POST(
  _request: Request,
  context: { params: Promise<{ suggestedProblemId: string; topicId: string }> },
) {
  const { suggestedProblemId, topicId } = await context.params;
  const topic = ignoreMockSuggestedProblem(
    await loadMockTopic(topicId),
    suggestedProblemId,
  );

  return NextResponse.json(
    IgnoreSuggestedProblemResponseSchema.parse({ suggestedProblemId, topic }),
  );
}
