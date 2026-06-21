import { describe, expect, it } from "vitest";

import { PATCH } from "./route";

describe("site home management route", () => {
  it("patches site home configuration", async () => {
    const response = await PATCH(
      new Request("http://localhost/api/site/home", {
        body: JSON.stringify({
          patch: {
            featuredTopicIds: ["topic_path_minimum"],
            knowledgeTags: ["二次函数", "路径最值"],
            recentProblemLimit: 8,
            siteName: "新的题库",
          },
        }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "PATCH",
      }),
    );
    const payload = await response.json();

    expect(payload.siteHome).toMatchObject({
      featuredTopicIds: ["topic_path_minimum"],
      knowledgeTags: ["二次函数", "路径最值"],
      recentProblemLimit: 8,
      siteName: "新的题库",
      status: "published_dirty",
    });
  });
});
