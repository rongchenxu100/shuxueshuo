import { describe, expect, it } from "vitest";

import type { NavResponse } from "@/lib/contracts";
import navFixture from "../../fixtures/nav.json";

import {
  autosaveStateLabel,
  getInitialSelection,
  insertProblem,
  previewUrlWithVersion,
  publishStatusLabel,
  resolveSelection,
} from "./workspace-model";

const nav = navFixture as NavResponse;

describe("workspace model", () => {
  it("selects the first problem by default", () => {
    expect(getInitialSelection(nav)).toEqual({
      kind: "problem",
      id: "problem_hongqiao_25",
    });
  });

  it("falls back to site home when there are no problems", () => {
    expect(getInitialSelection({ ...nav, problems: [] })).toEqual({
      kind: "site_home",
    });
  });

  it("resolves problem, topic, and site home selections", () => {
    expect(resolveSelection(nav, { kind: "problem", id: "problem_heping_24" }))
      .toMatchObject({
        kind: "problem",
        item: { shortTitle: "和平三模 24题" },
      });
    expect(resolveSelection(nav, { kind: "topic", id: "topic_path_minimum" }))
      .toMatchObject({
        kind: "topic",
        item: { title: "二次函数路径最值" },
      });
    expect(resolveSelection(nav, { kind: "site_home" })).toMatchObject({
      kind: "site_home",
      item: { siteName: "数学可视化题库" },
    });
  });

  it("falls back explicitly for unknown selection kinds", () => {
    expect(
      resolveSelection(nav, { kind: "settings" } as never),
    ).toStrictEqual({
      kind: "new_problem",
    });
  });

  it("maps publish statuses to Chinese labels", () => {
    expect(publishStatusLabel("draft")).toBe("草稿");
    expect(publishStatusLabel("published")).toBe("已发布");
    expect(publishStatusLabel("published_dirty")).toBe("已发布 · 有改动");
  });

  it("maps autosave states to Chinese labels", () => {
    expect(autosaveStateLabel("saving")).toBe("正在保存");
    expect(autosaveStateLabel("saved")).toBe("刚刚已保存");
    expect(autosaveStateLabel("error")).toBe("保存失败");
  });

  it("adds or updates previewVersion in iframe URLs", () => {
    expect(previewUrlWithVersion("/preview.html", "mock-1")).toBe(
      "/preview.html?v=mock-1",
    );
    expect(previewUrlWithVersion("/preview.html?mode=work", "mock-2")).toBe(
      "/preview.html?mode=work&v=mock-2",
    );
    expect(previewUrlWithVersion("/preview.html?v=old#step", "mock-3")).toBe(
      "/preview.html?v=mock-3#step",
    );
  });

  it("inserts a created problem at the top", () => {
    const [problem] = nav.problems;
    const nextNav = insertProblem(nav, { ...problem, id: "problem_new" });

    expect(nextNav.problems[0].id).toBe("problem_new");
  });
});
