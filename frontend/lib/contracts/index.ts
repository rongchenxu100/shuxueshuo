import { z } from "zod";

export const PublishStatusSchema = z.enum([
  "draft",
  "published",
  "published_dirty",
]);
export type PublishStatus = z.infer<typeof PublishStatusSchema>;

export const ProblemModeSchema = z.enum(["edit", "tutor"]);
export type ProblemMode = z.infer<typeof ProblemModeSchema>;

export const MessageAttachmentSchema = z.object({
  id: z.string(),
  kind: z.enum(["problem_image", "reference_image"]),
  url: z.string(),
  filename: z.string().optional(),
  mimeType: z.string().optional(),
  ocrText: z.string().optional(),
  createdAt: z.string(),
});
export type MessageAttachment = z.infer<typeof MessageAttachmentSchema>;

export const AnnotationTargetTypeSchema = z.enum([
  "problem_text",
  "problem_figure",
  "step",
  "step_title",
  "step_figure",
  "step_derivation",
  "step_navigation",
]);
export type AnnotationTargetType = z.infer<typeof AnnotationTargetTypeSchema>;

export const WebAnnotationSchema = z.object({
  id: z.string(),
  problemId: z.string(),
  targetId: z.string(),
  targetType: AnnotationTargetTypeSchema,
  stepId: z.string().optional(),
  label: z.string(),
  comment: z.string(),
  screenshotUrl: z.string().optional(),
  createdAt: z.string(),
});
export type WebAnnotation = z.infer<typeof WebAnnotationSchema>;

export const CreateWebAnnotationRequestSchema = z.object({
  targetId: z.string(),
  targetType: AnnotationTargetTypeSchema,
  stepId: z.string().optional(),
  label: z.string(),
  comment: z.string().min(1),
  screenshotUrl: z.string().optional(),
});
export type CreateWebAnnotationRequest = z.infer<
  typeof CreateWebAnnotationRequestSchema
>;

export const CreateWebAnnotationResponseSchema = z.object({
  annotation: WebAnnotationSchema,
});
export type CreateWebAnnotationResponse = z.infer<
  typeof CreateWebAnnotationResponseSchema
>;

export const ProblemAnnotationsResponseSchema = z.object({
  annotations: z.array(WebAnnotationSchema),
});
export type ProblemAnnotationsResponse = z.infer<
  typeof ProblemAnnotationsResponseSchema
>;

export const ProblemMessageSchema = z.object({
  id: z.string(),
  problemId: z.string(),
  role: z.enum(["user", "assistant", "system"]),
  content: z.string(),
  attachments: z.array(MessageAttachmentSchema).optional(),
  annotations: z.array(WebAnnotationSchema).optional(),
  createdAt: z.string(),
});
export type ProblemMessage = z.infer<typeof ProblemMessageSchema>;

export const TutorActionSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("scroll_to_step"),
    stepId: z.string(),
  }),
  z.object({
    type: z.literal("highlight_target"),
    targetId: z.string(),
  }),
  z.object({
    type: z.literal("show_hint"),
    text: z.string(),
  }),
]);
export type TutorAction = z.infer<typeof TutorActionSchema>;

export const TutorSessionSchema = z.object({
  id: z.string(),
  problemId: z.string(),
  userId: z.string(),
  title: z.string().optional(),
  currentStepId: z.string().optional(),
  createdAt: z.string(),
  updatedAt: z.string(),
});
export type TutorSession = z.infer<typeof TutorSessionSchema>;

export const TutorMessageSchema = z.object({
  id: z.string(),
  sessionId: z.string(),
  role: z.enum(["user", "assistant", "system"]),
  content: z.string(),
  selectedTargetId: z.string().optional(),
  currentStepId: z.string().optional(),
  actions: z.array(TutorActionSchema).optional(),
  createdAt: z.string(),
});
export type TutorMessage = z.infer<typeof TutorMessageSchema>;

export const ProblemSchema = z.object({
  id: z.string(),
  title: z.string(),
  shortTitle: z.string(),
  status: PublishStatusSchema,
  defaultMode: ProblemModeSchema.optional(),
  canEdit: z.boolean().optional(),
  canTutor: z.boolean().optional(),
  subject: z.literal("math"),
  tags: z.array(z.string()),
  updatedAt: z.string(),
  autosavedAt: z.string(),
  publicUrl: z.string().nullable(),
  previewUrl: z.string(),
  previewVersion: z.string(),
});
export type Problem = z.infer<typeof ProblemSchema>;

export const TopicItemSchema = z.object({
  id: z.string(),
  problemId: z.string(),
  title: z.string(),
  tags: z.array(z.string()),
  status: PublishStatusSchema,
  order: z.number(),
});
export type TopicItem = z.infer<typeof TopicItemSchema>;

export const SuggestedProblemSchema = z.object({
  id: z.string(),
  problemId: z.string(),
  title: z.string(),
  reason: z.string(),
  confidence: z.number().optional(),
  tags: z.array(z.string()),
});
export type SuggestedProblem = z.infer<typeof SuggestedProblemSchema>;

export const TopicSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string(),
  status: PublishStatusSchema,
  updatedAt: z.string(),
  autosavedAt: z.string(),
  publicUrl: z.string().nullable(),
  previewUrl: z.string(),
  previewVersion: z.string().optional(),
  items: z.array(TopicItemSchema),
  suggestedProblems: z.array(SuggestedProblemSchema),
});
export type Topic = z.infer<typeof TopicSchema>;

export const SiteHomeSchema = z.object({
  id: z.string(),
  siteName: z.string(),
  description: z.string(),
  status: PublishStatusSchema,
  autosavedAt: z.string(),
  publicUrl: z.string().nullable(),
  previewUrl: z.string(),
  featuredTopicIds: z.array(z.string()),
  recentProblemLimit: z.number(),
  knowledgeTags: z.array(z.string()),
});
export type SiteHome = z.infer<typeof SiteHomeSchema>;

export const NavResponseSchema = z.object({
  problems: z.array(ProblemSchema),
  siteHome: SiteHomeSchema,
  topics: z.array(TopicSchema),
});
export type NavResponse = z.infer<typeof NavResponseSchema>;

export const ApiErrorSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    retryable: z.boolean(),
  }),
});
export type ApiError = z.infer<typeof ApiErrorSchema>;

export const CreateProblemRequestSchema = z
  .object({
    text: z.string().min(1),
  })
  .strict();
export type CreateProblemRequest = z.infer<typeof CreateProblemRequestSchema>;

export const CreateProblemResponseSchema = z.object({
  problem: ProblemSchema,
  initialMessage: ProblemMessageSchema,
});
export type CreateProblemResponse = z.infer<
  typeof CreateProblemResponseSchema
>;

export const StartProblemUploadResponseSchema = z.object({
  jobId: z.string(),
  streamUrl: z.string(),
});
export type StartProblemUploadResponse = z.infer<
  typeof StartProblemUploadResponseSchema
>;

export const PatchProblemRequestSchema = z.object({
  patch: z
    .object({
      title: z.string().optional(),
      tags: z.array(z.string()).optional(),
    })
    .refine((patch) => patch.title !== undefined || patch.tags !== undefined, {
      message: "patch must include title or tags",
    }),
  expectedAutosavedAt: z.string(),
});
export type PatchProblemRequest = z.infer<typeof PatchProblemRequestSchema>;

export const PatchProblemResponseSchema = z.object({
  problem: ProblemSchema,
});
export type PatchProblemResponse = z.infer<
  typeof PatchProblemResponseSchema
>;

export const ProblemMessagesResponseSchema = z.object({
  messages: z.array(ProblemMessageSchema),
});
export type ProblemMessagesResponse = z.infer<
  typeof ProblemMessagesResponseSchema
>;

export const CreateProblemMessageRequestSchema = z.object({
  annotationIds: z.array(z.string()).optional(),
  content: z.string().min(1),
});
export type CreateProblemMessageRequest = z.infer<
  typeof CreateProblemMessageRequestSchema
>;

export const CreateProblemMessageResponseSchema = z.object({
  messages: z.array(ProblemMessageSchema),
  preview: z.object({
    previewUrl: z.string(),
    previewVersion: z.string(),
  }),
  problem: ProblemSchema,
});
export type CreateProblemMessageResponse = z.infer<
  typeof CreateProblemMessageResponseSchema
>;

export const UploadJobProgressEventSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("progress"),
    stage: z.enum([
      "stored",
      "detecting",
      "ocr",
      "generating",
      "compiling",
    ]),
    message: z.string(),
  }),
  z.object({
    type: z.literal("done"),
    result: z.literal("created"),
    problem: ProblemSchema,
    initialMessage: ProblemMessageSchema,
  }),
  z.object({
    type: z.literal("rejected"),
    message: z.string(),
  }),
  z.object({
    type: z.literal("failed"),
    error: ApiErrorSchema.shape.error,
  }),
]);
export type UploadJobProgressEvent = z.infer<
  typeof UploadJobProgressEventSchema
>;
