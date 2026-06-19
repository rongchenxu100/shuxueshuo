import type { UploadJobProgressEvent } from "@/lib/contracts";

export type ProblemCreationScenario =
  | "success"
  | "rejected"
  | "failed"
  | "disconnect";

export type NewProblemPromptSnapshot = {
  fileName: string | null;
  filePreviewUrl: string | null;
  text: string;
};

export type ProblemConversationAttempt = {
  error: string | null;
  events: UploadJobProgressEvent[];
  id: number;
  kind: "text" | "upload";
  prompt: NewProblemPromptSnapshot;
  status: "submitting" | "completed" | "failed";
  systemMessage?: string;
};
