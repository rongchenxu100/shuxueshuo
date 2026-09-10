import { z } from "zod";

export const ArtifactSchema = z.object({
  schema_version: z.literal("review-artifact/v1"), id: z.string(), run_id: z.string(),
  stage: z.string(), role: z.string(), name: z.string(), media_type: z.string(),
  size: z.number(), sha256: z.string(), dependencies: z.array(z.string()),
  producer: z.string(),
  url: z.string(), created_at: z.number(), page_path: z.string().nullable(),
  reused_from: z.object({ run_id: z.string(), artifact_id: z.string(), sha256: z.string() }).optional(),
});
export const StageSchema = z.object({
  schema_version: z.literal("review-stage/v1").optional(),
  id: z.string(), title: z.string(), status: z.string(), summary: z.string(),
  started_at: z.number().nullable(), finished_at: z.number().nullable(),
  diagnostics: z.array(z.object({ code: z.string(), message: z.string() })),
  input_refs: z.array(z.string()).optional(), output_refs: z.array(z.string()).optional(),
  validation_refs: z.array(z.string()).optional(), call_refs: z.array(z.string()).optional(),
  raw_refs: z.array(z.string()).optional(), configuration_ref: z.string().nullable().optional(),
  attempts: z.array(z.object({ attempt: z.number(), call_ref: z.string() })).optional(),
  reused_from_run_id: z.string().optional(),
});
export const RunSchema = z.object({
  schema_version: z.literal("review-run/v1"), id: z.string(), filename: z.string(),
  parent_run_id: z.string().nullable(), status: z.string(), created_at: z.number(),
  updated_at: z.number(), started_at: z.number().nullable(), finished_at: z.number().nullable(),
  page_url: z.string().nullable(), stages: z.array(StageSchema), artifacts: z.array(ArtifactSchema),
  error: z.string().optional(),
  from_stage: z.string().optional(),
  rerun_options: z.record(z.string(), z.object({ available: z.boolean(), reason: z.string() })).optional(),
});
export const RunsSchema = z.object({ schema_version: z.literal("review-list/v1"), runs: z.array(RunSchema) });
export const StartSchema = z.object({ schema_version: z.literal("review-start/v1"), run_id: z.string(), review_url: z.string(), events_url: z.string() });
export type ReviewRun = z.infer<typeof RunSchema>;
export type Artifact = z.infer<typeof ArtifactSchema>;
export const terminal = (status: string) => ["succeeded", "failed", "interrupted"].includes(status);
export const statusLabel = (status: string) => ({ pending: "等待", initializing: "入库中", queued: "排队中", running: "运行中", succeeded: "成功", failed: "失败", blocked: "被阻塞", interrupted: "已中断" }[status] ?? status);

export async function reviewFetch(path: string, init?: RequestInit) {
  const response = await fetch(path, { ...init, cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `请求失败 (${response.status})`);
  }
  return response.json();
}
