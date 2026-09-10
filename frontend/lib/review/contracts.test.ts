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
