import { NextResponse } from "next/server";

import {
  CreateWebAnnotationRequestSchema,
  CreateWebAnnotationResponseSchema,
  ProblemAnnotationsResponseSchema,
} from "@/lib/contracts";
import {
  createProblemAnnotation,
  getProblemAnnotations,
} from "@/lib/mock/annotation-store";

export async function GET(
  _request: Request,
  context: { params: Promise<{ problemId: string }> },
) {
  const { problemId } = await context.params;
  const annotations = await getProblemAnnotations(problemId);

  return NextResponse.json(
    ProblemAnnotationsResponseSchema.parse({ annotations }),
  );
}

export async function POST(
  request: Request,
  context: { params: Promise<{ problemId: string }> },
) {
  const { problemId } = await context.params;
  const payload = CreateWebAnnotationRequestSchema.parse(await request.json());
  const annotation = await createProblemAnnotation(problemId, payload);

  return NextResponse.json(
    CreateWebAnnotationResponseSchema.parse({ annotation }),
  );
}
