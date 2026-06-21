import { describe, expect, it } from "vitest";

import type { NavResponse } from "@/lib/contracts";
import navFixture from "../../fixtures/nav.json";

import {
  autosaveStateLabel,
  getInitialSelection,
  getSelectionAfterRemoval,
  insertProblem,
  mergePublishedProblem,
  mergeAcceptedSuggestion,
  moveTopicItem,
  paginateItems,
  previewUrlWithVersion,
  publishActionLabel,
  publishStatusLabel,
  resolveSelection,
  updateProblem,
  updateSiteHome,
  updateTopic,
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

  it("maps publish actions from status and public URL", () => {
    expect(publishActionLabel("draft", null)).toBe("发布");
    expect(publishActionLabel("published_dirty", "/users/haorong/problems/a/"))
      .toBe("发布更新");
    expect(publishActionLabel("published", "/users/haorong/problems/a/"))
      .toBe("打开页面");
    expect(publishActionLabel("published", null)).toBe("发布");
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

  it("updates published objects in nav", () => {
    const publishedProblem = {
      ...nav.problems[2],
      publicUrl: "/users/haorong/problems/heping-25/",
      status: "published" as const,
    };
    const publishedTopic = {
      ...nav.topics[2],
      publicUrl: "/users/haorong/topics/geometry-overlap/",
      status: "published" as const,
    };
    const publishedSiteHome = {
      ...nav.siteHome,
      status: "published_dirty" as const,
    };

    expect(
      updateProblem(nav, publishedProblem).problems.find(
        (problem) => problem.id === publishedProblem.id,
      )?.publicUrl,
    ).toBe("/users/haorong/problems/heping-25/");
    expect(
      updateTopic(nav, publishedTopic).topics.find(
        (topic) => topic.id === publishedTopic.id,
      )?.status,
    ).toBe("published");
    expect(updateSiteHome(nav, publishedSiteHome).siteHome.status).toBe(
      "published_dirty",
    );
  });

  it("paginates items and clamps page bounds", () => {
    const items = Array.from({ length: 23 }, (_, index) => index + 1);

    expect(paginateItems(items, 2, 10)).toMatchObject({
      items: [11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
      page: 2,
      pageCount: 3,
      total: 23,
    });
    expect(paginateItems(items, 9, 10).page).toBe(3);
  });

  it("moves topic items and normalizes order", () => {
    const items = [
      { ...nav.topics[0].items[0], id: "a", order: 1 },
      { ...nav.topics[0].items[0], id: "b", order: 2 },
      { ...nav.topics[0].items[0], id: "c", order: 3 },
    ];

    expect(moveTopicItem(items, "b", "up").map((item) => item.id)).toEqual([
      "b",
      "a",
      "c",
    ]);
    expect(moveTopicItem(items, "c", "down")).toBe(items);
  });

  it("merges accepted suggestions into topic state", () => {
    const topic = nav.topics[0];
    const suggestion = topic.suggestedProblems[0];
    const item = {
      id: "topic_item_new",
      order: topic.items.length + 1,
      problemId: suggestion.problemId,
      status: "draft" as const,
      tags: suggestion.tags,
      title: suggestion.title,
    };
    const nextTopic = mergeAcceptedSuggestion(topic, item, suggestion.id);

    expect(nextTopic.items.at(-1)?.id).toBe("topic_item_new");
    expect(nextTopic.suggestedProblems).toHaveLength(0);
  });

  it("selects a fallback object after deleting selected objects", () => {
    expect(
      getSelectionAfterRemoval(nav, {
        kind: "problem",
        id: "problem_hongqiao_25",
      }),
    ).toEqual({ kind: "problem", id: "problem_heping_24" });
    expect(
      getSelectionAfterRemoval(
        { ...nav, problems: [] },
        {
          kind: "topic",
          id: "topic_tianjin_sanmo_25",
        },
      ),
    ).toEqual({ kind: "site_home" });
  });

  it("merges published problem status without losing local draft fields", () => {
    const currentProblem = {
      ...nav.problems[2],
      previewVersion: "mock-created-local",
      shortTitle: "本地新题",
      title: "本地新题完整标题",
    };
    const publishedProblem = {
      ...currentProblem,
      previewVersion: "mock-published-fallback",
      publicUrl: "/users/haorong/problems/local/",
      shortTitle: "新建题目",
      status: "published" as const,
      title: "新建题目",
      updatedAt: "2026-06-21T09:00:00.000Z",
    };

    expect(mergePublishedProblem(currentProblem, publishedProblem))
      .toMatchObject({
        previewVersion: "mock-created-local",
        publicUrl: "/users/haorong/problems/local/",
        shortTitle: "本地新题",
        status: "published",
        title: "本地新题完整标题",
        updatedAt: "2026-06-21T09:00:00.000Z",
      });
  });
});
