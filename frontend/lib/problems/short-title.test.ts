import { describe, expect, it } from "vitest";

import { deriveProblemShortTitle } from "./short-title";

describe("deriveProblemShortTitle", () => {
  it("derives compact titles for Tianjin mock exam problems", () => {
    expect(
      deriveProblemShortTitle("2026 年天津市红桥区三模第 25 题"),
    ).toBe("红桥三模 25题");
    expect(
      deriveProblemShortTitle("2026 年天津市和平区三模第 24 题"),
    ).toBe("和平三模 24题");
  });

  it("falls back to a compact prefix", () => {
    expect(
      deriveProblemShortTitle("这是一道非常长非常长的题目标题用于测试"),
    ).toBe("这是一道非常长非常长的题目标题用于测");
  });

  it("uses a default title when the input is blank", () => {
    expect(deriveProblemShortTitle("   ")).toBe("新建题目");
  });
});
