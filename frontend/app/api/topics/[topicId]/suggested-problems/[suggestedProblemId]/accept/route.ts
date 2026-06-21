import { NextResponse } from "next/server";

import { AcceptSuggestedProblemResponseSchema } from "@/lib/contracts";
import { acceptMockSuggestedProblem } from "@/lib/mock/topic-management";

import { loadMockTopic } from "../../../../_mock";

export async function POST(
  _request: Request,
  context: { params: Promise<{ suggestedProblemId: string; topicId: string }> },
) {
  const { suggestedProblemId, topicId } = await context.params;
  const response = acceptMockSuggestedProblem(
    await loadMockTopic(topicId),
    suggestedProblemId,
  );

  return NextResponse.json(AcceptSuggestedProblemResponseSchema.parse(response));
}
