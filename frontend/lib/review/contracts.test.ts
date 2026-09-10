import { describe, expect, it } from "vitest";
import { RunSchema, StartSchema, statusLabel, terminal } from "./contracts";

describe("Review contract", () => {
  it("requires actual stage and artifact records, not upload mock results", () => {
    expect(StartSchema.safeParse({ jobId: "mock", streamUrl: "/mock" }).success).toBe(false);
    const run = { schema_version: "review-run/v1", id: "run", filename: "image.png", parent_run_id: null,
      status: "running", created_at: 1, updated_at: 2, started_at: 2, finished_at: null, page_url: null,
      artifacts: [], stages: [{ id: "lesson", title: "学生讲解", status: "pending", summary: "", started_at: null, finished_at: null, diagnostics: [] }] };
    expect(RunSchema.parse(run).page_url).toBeNull();
    expect(RunSchema.safeParse({ ...run, schema_version: "review-run/v2" }).success).toBe(false);
  });
  it("distinguishes failure, interruption and blocked downstream", () => {
    expect(terminal("interrupted")).toBe(true);
    expect(terminal("running")).toBe(false);
    expect(statusLabel("blocked")).toBe("被阻塞");
  });
});

import { RebuildPlanSchema, EditableProblemSchema, ProblemPreviewSchema, pageValidityLabel } from "./contracts";

describe("Review revision and rebuild contracts", () => {
  const plan = { schema_version: "review-rebuild-plan/v1", run_id: "run", base_revision_id: "revision",
    requested_stage: "visual", fingerprint: "content-hash", reuse_stages: ["source", "solver", "lesson"],
    rerun_stages: ["visual", "page"], reasons: [{ stage: "visual", code: "build.resource_changed", message: "VisualSpec" }],
    calls_models: false, model_stages: [], available: true, page_validity: "stale", latest_run_id: "run", page_run_id: "old" };
  it("preserves revision and fingerprint for optimistic submission", () => {
    const checked = RebuildPlanSchema.parse(plan);
    expect(checked.base_revision_id).toBe("revision");
    expect(checked.fingerprint).toBe("content-hash");
    expect(checked.calls_models).toBe(false);
    expect(RebuildPlanSchema.safeParse({ ...plan, fingerprint: undefined }).success).toBe(false);
  });
  it("never labels unknown or stale output as current", () => {
    expect(pageValidityLabel("unknown")).toContain("缺少版本证据");
    expect(pageValidityLabel("stale")).toContain("历史预览");
    expect(pageValidityLabel("current")).toBe("当前有效");
  });
  it("keeps invalid domain diagnostics and requires editable revision identity", () => {
    expect(ProblemPreviewSchema.parse({ ok: false, diagnostics: [{ path: "$.family_id" }], diff: [] }).ok).toBe(false);
    expect(EditableProblemSchema.safeParse({ domain: {}, schema: {} }).success).toBe(false);
  });
});
