import type {
  AddTopicItemRequest,
  PatchSiteHomeRequest,
  PatchTopicRequest,
  SiteHome,
  SuggestedProblem,
  Topic,
  TopicItem,
} from "@/lib/contracts";
import { makeUserPath, slugFromId } from "@/lib/mock/publish";

const TOPIC_PREVIEW_URL = "/preview-fixtures/topics/tianjin-sanmo-25.html";

export function createMockTopic(
  input: { description?: string; title?: string } = {},
  now = new Date(),
): Topic {
  const idSuffix = String(now.getTime());
  const timestamp = now.toISOString();
  const id = `topic_mock_${idSuffix}`;

  return {
    autosavedAt: timestamp,
    description: input.description ?? "",
    id,
    items: [],
    previewUrl: TOPIC_PREVIEW_URL,
    previewVersion: `mock-topic-${idSuffix}`,
    publicUrl: null,
    status: "draft",
    suggestedProblems: [],
    title: input.title ?? "新建专题",
    updatedAt: timestamp,
  };
}

export function createTopicFallback(topicId: string, now = new Date()): Topic {
  const timestamp = now.toISOString();

  return {
    autosavedAt: timestamp,
    description: "",
    id: topicId,
    items: [],
    previewUrl: TOPIC_PREVIEW_URL,
    previewVersion: `mock-topic-${now.getTime()}`,
    publicUrl: null,
    status: "draft",
    suggestedProblems: [],
    title: "新建专题",
    updatedAt: timestamp,
  };
}

export function patchMockTopic(
  topic: Topic,
  request: PatchTopicRequest,
  now = new Date(),
): Topic {
  const timestamp = now.toISOString();

  return {
    ...topic,
    ...request.patch,
    autosavedAt: timestamp,
    status: topic.status === "published" ? "published_dirty" : topic.status,
    updatedAt: timestamp,
  };
}

export function addMockTopicItem(
  topic: Topic,
  request: AddTopicItemRequest,
  now = new Date(),
): { item: TopicItem; topic: Topic } {
  const item: TopicItem = {
    id: `topic_item_${request.problemId}_${now.getTime()}`,
    order: topic.items.length + 1,
    problemId: request.problemId,
    status: request.status,
    tags: request.tags,
    title: request.title,
  };

  return {
    item,
    topic: touchTopic({
      ...topic,
      items: normalizeTopicItemOrder([...topic.items, item]),
    }, now),
  };
}

export function acceptMockSuggestedProblem(
  topic: Topic,
  suggestedProblemId: string,
  now = new Date(),
): { item: TopicItem; topic: Topic } {
  const suggestion = topic.suggestedProblems.find(
    (item) => item.id === suggestedProblemId,
  );
  const fallbackSuggestion: SuggestedProblem = {
    id: suggestedProblemId,
    problemId: suggestedProblemId.replace(/^suggested_/, "problem_"),
    reason: "mock 自动归类建议",
    tags: ["待分类"],
    title: "自动归类题目",
  };
  const acceptedSuggestion = suggestion ?? fallbackSuggestion;
  const item: TopicItem = {
    id: `topic_item_${acceptedSuggestion.problemId}_${now.getTime()}`,
    order: topic.items.length + 1,
    problemId: acceptedSuggestion.problemId,
    status: "draft",
    tags: acceptedSuggestion.tags,
    title: acceptedSuggestion.title,
  };

  return {
    item,
    topic: touchTopic({
      ...topic,
      items: normalizeTopicItemOrder([...topic.items, item]),
      suggestedProblems: topic.suggestedProblems.filter(
        (current) => current.id !== suggestedProblemId,
      ),
    }, now),
  };
}

export function ignoreMockSuggestedProblem(
  topic: Topic,
  suggestedProblemId: string,
  now = new Date(),
): Topic {
  return touchTopic({
    ...topic,
    suggestedProblems: topic.suggestedProblems.filter(
      (item) => item.id !== suggestedProblemId,
    ),
  }, now);
}

export function removeMockTopicItem(
  topic: Topic,
  itemId: string,
  now = new Date(),
): Topic {
  return touchTopic({
    ...topic,
    items: normalizeTopicItemOrder(
      topic.items.filter((item) => item.id !== itemId),
    ),
  }, now);
}

export function reorderMockTopicItems(
  topic: Topic,
  itemIds: string[],
  now = new Date(),
): Topic {
  const order = new Map(itemIds.map((itemId, index) => [itemId, index]));
  const items = [...topic.items].sort((a, b) => {
    const aOrder = order.get(a.id) ?? a.order;
    const bOrder = order.get(b.id) ?? b.order;
    return aOrder - bOrder;
  });

  return touchTopic({
    ...topic,
    items: normalizeTopicItemOrder(items),
  }, now);
}

export function patchMockSiteHome(
  siteHome: SiteHome,
  request: PatchSiteHomeRequest,
  now = new Date(),
): SiteHome {
  return {
    ...siteHome,
    ...request.patch,
    autosavedAt: now.toISOString(),
    status: siteHome.status === "published" ? "published_dirty" : siteHome.status,
  };
}

export function ensureTopicPublicUrl(topic: Topic): string {
  return topic.publicUrl ?? makeUserPath("topics", slugFromId(topic.id));
}

function touchTopic(topic: Topic, now: Date): Topic {
  const timestamp = now.toISOString();

  return {
    ...topic,
    autosavedAt: timestamp,
    status: topic.status === "published" ? "published_dirty" : topic.status,
    updatedAt: timestamp,
  };
}

function normalizeTopicItemOrder(items: TopicItem[]): TopicItem[] {
  return items.map((item, index) => ({
    ...item,
    order: index + 1,
  }));
}
