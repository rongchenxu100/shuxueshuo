import { describe, expect, it } from "vitest";

import { POST } from "./route";

describe("site home publish route", () => {
  it("publishes the site home idempotently", async () => {
    const response = await POST();
    const payload = await response.json();

    expect(payload.siteHome.status).toBe("published");
    expect(payload.publicUrl).toBe("/users/haorong/");
    expect(payload.siteHome.autosavedAt).toBe("2026-06-16T09:00:00.000Z");
  });
});
