import { describe, expect, it } from "vitest";

import { POST } from "./route";

function createContext(topicId: string) {
  return {
    params: Promise.resolve({ topicId }),
  };
}

describe("topic publish route", () => {
  it("publishes a draft topic and creates a public URL", async () => {
    const response = await POST(
      new Request(
        "http://localhost/api/topics/topic_geometry_overlap/publish",
        {
          method: "POST",
        },
      ),
      createContext("topic_geometry_overlap"),
    );
    const payload = await response.json();

    expect(payload.topic.status).toBe("published");
    expect(payload.publicUrl).toBe(
      "/users/haorong/topics/geometry-overlap/",
    );
  });

  it("publishes dirty changes without changing an existing public URL", async () => {
    const response = await POST(
      new Request(
        "http://localhost/api/topics/topic_tianjin_sanmo_25/publish",
        {
          method: "POST",
        },
      ),
      createContext("topic_tianjin_sanmo_25"),
    );
    const payload = await response.json();

    expect(payload.topic.status).toBe("published");
    expect(payload.publicUrl).toBe("/users/haorong/topics/tianjin-sanmo-25/");
  });
});
