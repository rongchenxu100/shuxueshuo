import {
  CreateWebAnnotationRequestSchema,
  ProblemAnnotationsResponseSchema,
  type CreateWebAnnotationRequest,
  type WebAnnotation,
} from "@/lib/contracts";
import { loadFixture } from "@/lib/mock/load-fixture";

let annotationsByProblemId: Map<string, WebAnnotation[]> | null = null;

// Mock-only runtime state. Route handlers share this module while the dev
// server is alive, but hot reload may reset it back to fixture defaults.
let mockAnnotationRun = 0;

export function resetMockAnnotationStore() {
  annotationsByProblemId = null;
  mockAnnotationRun = 0;
}

export async function getProblemAnnotations(
  problemId: string,
): Promise<WebAnnotation[]> {
  const store = await getAnnotationStore();

  return [...(store.get(problemId) ?? [])];
}

export async function getProblemAnnotationsByIds(
  problemId: string,
  annotationIds: string[] | undefined,
): Promise<WebAnnotation[]> {
  if (!annotationIds?.length) {
    return [];
  }

  const annotations = await getProblemAnnotations(problemId);
  const annotationsById = new Map(
    annotations.map((annotation) => [annotation.id, annotation]),
  );

  return annotationIds.flatMap((annotationId) => {
    const annotation = annotationsById.get(annotationId);

    return annotation ? [annotation] : [];
  });
}

export async function createProblemAnnotation(
  problemId: string,
  request: CreateWebAnnotationRequest,
  now = new Date(),
): Promise<WebAnnotation> {
  const store = await getAnnotationStore();
  const payload = CreateWebAnnotationRequestSchema.parse(request);
  const timestamp = now.toISOString();
  const annotation: WebAnnotation = {
    ...payload,
    createdAt: timestamp,
    id: `ann_mock_${now.getTime()}_${mockAnnotationRun++}`,
    problemId,
  };

  store.set(problemId, [...(store.get(problemId) ?? []), annotation]);

  return annotation;
}

async function getAnnotationStore() {
  if (annotationsByProblemId) {
    return annotationsByProblemId;
  }

  const fixtureAnnotations = ProblemAnnotationsResponseSchema.parse({
    annotations: await loadFixture("annotations/hongqiao-25.json"),
  }).annotations;
  annotationsByProblemId = new Map<string, WebAnnotation[]>();

  fixtureAnnotations.forEach((annotation) => {
    annotationsByProblemId?.set(annotation.problemId, [
      ...(annotationsByProblemId.get(annotation.problemId) ?? []),
      annotation,
    ]);
  });

  return annotationsByProblemId;
}
