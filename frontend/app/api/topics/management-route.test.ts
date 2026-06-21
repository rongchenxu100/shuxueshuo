import { describe, expect, it } from "vitest";

import { POST as createTopic } from "./route";
import { PATCH as patchTopic, DELETE as deleteTopic } from "./[topicId]/route";
import { POST as addTopicItem } from "./[topicId]/items/route";
import { PATCH as reorderTopicItems } from "./[topicId]/items/reorder/route";
import { DELETE as deleteTopicItem } from "./[topicId]/items/[itemId]/route";
import { GET as getSuggestions } from "./[topicId]/suggested-problems/route";
import { POST as acceptSuggestion } from "./[topicId]/suggested-problems/[suggestedProblemId]/accept/route";
import { POST as ignoreSuggestion } from "./[topicId]/suggested-problems/[suggestedProblemId]/ignore/route";

function topicContext(topicId: string) {
  return {
    params: Promise.resolve({ topicId }),
  };
}

function itemContext(topicId: string, itemId: string) {
  return {
    params: Promise.resolve({ itemId, topicId }),
  };
}

function suggestionContext(topicId: string, suggestedProblemId: string) {
  return {
    params: Promise.resolve({ suggestedProblemId, topicId }),
  };
}

function jsonRequest(url: string, body: unknown, method = "POST") {
  return new Request(url, {
    body: JSON.stringify(body),
    headers: {
      "Content-Type": "application/json",
    },
    method,
  });
}

describe("topic management routes", () => {
  it("creates, patches, and deletes mock topics", async () => {
    const createResponse = await createTopic(
      jsonRequest("http://localhost/api/topics", {
        description: "专题说明",
        title: "新专题",
      }),
    );
    const createPayload = await createResponse.json();

    expect(createPayload.topic).toMatchObject({
      description: "专题说明",
      status: "draft",
      title: "新专题",
    });

    const patchResponse = await patchTopic(
      jsonRequest(
        "http://localhost/api/topics/topic_tianjin_sanmo_25",
        {
          patch: {
            description: "更新说明",
            title: "更新专题",
          },
        },
        "PATCH",
      ),
      topicContext("topic_tianjin_sanmo_25"),
    );
    const patchPayload = await patchResponse.json();

    expect(patchPayload.topic).toMatchObject({
      description: "更新说明",
      status: "published_dirty",
      title: "更新专题",
    });

    const deleteResponse = await deleteTopic(
      new Request("http://localhost/api/topics/topic_tianjin_sanmo_25", {
        method: "DELETE",
      }),
      topicContext("topic_tianjin_sanmo_25"),
    );
    const deletePayload = await deleteResponse.json();

    expect(deletePayload.topicId).toBe("topic_tianjin_sanmo_25");
  });

  it("adds, reorders, and removes topic items", async () => {
    const addResponse = await addTopicItem(
      jsonRequest("http://localhost/api/topics/topic_path_minimum/items", {
        problemId: "problem_hexi_25",
        status: "draft",
        tags: ["二次函数综合"],
        title: "河西三模 25题",
      }),
      topicContext("topic_path_minimum"),
    );
    const addPayload = await addResponse.json();

    expect(addPayload.item).toMatchObject({
      problemId: "problem_hexi_25",
      title: "河西三模 25题",
    });

    const reorderResponse = await reorderTopicItems(
      jsonRequest(
        "http://localhost/api/topics/topic_tianjin_sanmo_25/items/reorder",
        { itemIds: ["topic_item_1"] },
        "PATCH",
      ),
      topicContext("topic_tianjin_sanmo_25"),
    );
    const reorderPayload = await reorderResponse.json();

    expect(reorderPayload.topic.items[0]).toMatchObject({
      id: "topic_item_1",
      order: 1,
    });

    const deleteResponse = await deleteTopicItem(
      new Request(
        "http://localhost/api/topics/topic_tianjin_sanmo_25/items/topic_item_1",
        { method: "DELETE" },
      ),
      itemContext("topic_tianjin_sanmo_25", "topic_item_1"),
    );
    const deletePayload = await deleteResponse.json();

    expect(deletePayload.itemId).toBe("topic_item_1");
    expect(deletePayload.topic.items).toHaveLength(0);
  });

  it("returns, accepts, and ignores suggested problems", async () => {
    const getResponse = await getSuggestions(
      new Request(
        "http://localhost/api/topics/topic_tianjin_sanmo_25/suggested-problems",
      ),
      topicContext("topic_tianjin_sanmo_25"),
    );
    const getPayload = await getResponse.json();

    expect(getPayload.suggestedProblems).toHaveLength(1);

    const acceptResponse = await acceptSuggestion(
      new Request(
        "http://localhost/api/topics/topic_tianjin_sanmo_25/suggested-problems/suggested_problem_1/accept",
        { method: "POST" },
      ),
      suggestionContext("topic_tianjin_sanmo_25", "suggested_problem_1"),
    );
    const acceptPayload = await acceptResponse.json();

    expect(acceptPayload.item.problemId).toBe("problem_hexi_25");
    expect(acceptPayload.topic.suggestedProblems).toHaveLength(0);

    const ignoreResponse = await ignoreSuggestion(
      new Request(
        "http://localhost/api/topics/topic_tianjin_sanmo_25/suggested-problems/suggested_problem_1/ignore",
        { method: "POST" },
      ),
      suggestionContext("topic_tianjin_sanmo_25", "suggested_problem_1"),
    );
    const ignorePayload = await ignoreResponse.json();

    expect(ignorePayload.suggestedProblemId).toBe("suggested_problem_1");
    expect(ignorePayload.topic.suggestedProblems).toHaveLength(0);
  });
});
