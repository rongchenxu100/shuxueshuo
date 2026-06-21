import type { Topic } from "@/lib/contracts";
import { NavResponseSchema } from "@/lib/contracts";
import { loadFixture } from "@/lib/mock/load-fixture";
import { createTopicFallback } from "@/lib/mock/topic-management";

export async function loadMockTopic(topicId: string): Promise<Topic> {
  const nav = NavResponseSchema.parse(await loadFixture("nav.json"));

  return (
    nav.topics.find((topic) => topic.id === topicId) ??
    createTopicFallback(topicId)
  );
}
