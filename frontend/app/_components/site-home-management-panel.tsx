"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { patchSiteHome } from "@/lib/api/client";
import { getAutosaveDelayMs } from "@/lib/autosave/scheduler";
import type { SiteHome, Topic } from "@/lib/contracts";

import { publishStatusLabel, type AutosaveState } from "./workspace-model";
import { useLatestRef } from "./use-latest-ref";

export function SiteHomeManagementPanel({
  onAutosaveErrorChange,
  onAutosaveStateChange,
  onOpenTopic,
  onSiteHomeChange,
  siteHome,
  topics,
}: {
  onAutosaveErrorChange: (message: string | null) => void;
  onAutosaveStateChange: (state: AutosaveState) => void;
  onOpenTopic: (topicId: string) => void;
  onSiteHomeChange: (siteHome: SiteHome) => void;
  siteHome: SiteHome;
  topics: Topic[];
}) {
  const [siteName, setSiteName] = useState(siteHome.siteName);
  const [description, setDescription] = useState(siteHome.description);
  const [featuredTopicIds, setFeaturedTopicIds] = useState(
    siteHome.featuredTopicIds,
  );
  const [recentProblemLimit, setRecentProblemLimit] = useState(
    siteHome.recentProblemLimit,
  );
  const [knowledgeTagsText, setKnowledgeTagsText] = useState(
    siteHome.knowledgeTags.join("，"),
  );
  const [isAddTopicOpen, setIsAddTopicOpen] = useState(false);
  const [topicPendingRemoval, setTopicPendingRemoval] = useState<Topic | null>(
    null,
  );
  const [rescheduleToken, setRescheduleToken] = useState(0);
  const lastSaveStartedAtRef = useRef<number | null>(null);
  const dirtyVersionRef = useRef(0);
  const isSavingRef = useRef(false);
  const knowledgeTags = useMemo(
    () =>
      knowledgeTagsText
        .split(/[，,\n]/)
        .map((tag) => tag.trim())
        .filter(Boolean),
    [knowledgeTagsText],
  );
  const featuredTopics = featuredTopicIds.flatMap((topicId) => {
    const topic = topics.find((item) => item.id === topicId);
    return topic ? [topic] : [];
  });
  const availableTopics = topics.filter(
    (topic) => !featuredTopicIds.includes(topic.id),
  );
  const hasDraftChanges =
    siteName !== siteHome.siteName ||
    description !== siteHome.description ||
    recentProblemLimit !== siteHome.recentProblemLimit ||
    knowledgeTags.join("|") !== siteHome.knowledgeTags.join("|") ||
    featuredTopicIds.join("|") !== siteHome.featuredTopicIds.join("|");
  const autosaveRef = useLatestRef({
    description,
    featuredTopicIds,
    knowledgeTags,
    onAutosaveErrorChange,
    onAutosaveStateChange,
    onSiteHomeChange,
    recentProblemLimit,
    siteName,
  });

  useEffect(() => {
    if (!hasDraftChanges) {
      return;
    }

    const delayMs = getAutosaveDelayMs(
      lastSaveStartedAtRef.current,
      Date.now(),
    );
    const timeout = window.setTimeout(() => {
      if (isSavingRef.current) {
        return;
      }

      const latest = autosaveRef.current;
      const savedVersion = dirtyVersionRef.current;
      isSavingRef.current = true;
      lastSaveStartedAtRef.current = Date.now();
      latest.onAutosaveStateChange("saving");
      latest.onAutosaveErrorChange(null);
      patchSiteHome({
        patch: {
          description: latest.description,
          featuredTopicIds: latest.featuredTopicIds,
          knowledgeTags: latest.knowledgeTags,
          recentProblemLimit: latest.recentProblemLimit,
          siteName: latest.siteName,
        },
      })
        .then(({ siteHome: patchedSiteHome }) => {
          // Mock PATCH focuses on status timestamps; keep the current draft
          // fields so the session UI does not briefly fall back to fixture data.
          latest.onSiteHomeChange({
            ...patchedSiteHome,
            description: latest.description,
            featuredTopicIds: latest.featuredTopicIds,
            knowledgeTags: latest.knowledgeTags,
            recentProblemLimit: latest.recentProblemLimit,
            siteName: latest.siteName,
          });
          if (dirtyVersionRef.current === savedVersion) {
            latest.onAutosaveErrorChange(null);
            latest.onAutosaveStateChange("saved");
          } else {
            setRescheduleToken((current) => current + 1);
          }
        })
        .catch((error) => {
          latest.onAutosaveStateChange("error");
          latest.onAutosaveErrorChange(
            error instanceof Error ? error.message : "首页保存失败。",
          );
        })
        .finally(() => {
          isSavingRef.current = false;
        });
    }, delayMs);

    return () => window.clearTimeout(timeout);
  }, [
    autosaveRef,
    description,
    featuredTopicIds,
    hasDraftChanges,
    knowledgeTags,
    recentProblemLimit,
    rescheduleToken,
    siteName,
  ]);

  function markDirty() {
    lastSaveStartedAtRef.current ??= Date.now();
    dirtyVersionRef.current += 1;
    onAutosaveErrorChange(null);
  }

  function handleSiteNameChange(nextSiteName: string) {
    markDirty();
    setSiteName(nextSiteName);
  }

  function handleDescriptionChange(nextDescription: string) {
    markDirty();
    setDescription(nextDescription);
  }

  function handleRecentProblemLimitChange(nextLimit: number) {
    markDirty();
    setRecentProblemLimit(nextLimit);
  }

  function handleKnowledgeTagsTextChange(nextTagsText: string) {
    markDirty();
    setKnowledgeTagsText(nextTagsText);
  }

  function addFeaturedTopic(topicId: string) {
    markDirty();
    setFeaturedTopicIds((current) =>
      current.includes(topicId) ? current : [...current, topicId],
    );
  }

  function removeFeaturedTopic(topicId: string) {
    markDirty();
    setFeaturedTopicIds((current) => current.filter((id) => id !== topicId));
  }

  function moveFeaturedTopic(topicId: string, direction: "down" | "up") {
    markDirty();
    setFeaturedTopicIds((current) => {
      const index = current.indexOf(topicId);
      const nextIndex = direction === "up" ? index - 1 : index + 1;

      if (index < 0 || nextIndex < 0 || nextIndex >= current.length) {
        return current;
      }

      const next = [...current];
      const [item] = next.splice(index, 1);
      next.splice(nextIndex, 0, item);
      return next;
    });
  }

  return (
    <div className="relative mx-auto min-h-[calc(100vh-9rem)] w-full max-w-[860px] space-y-4">
      <section className="rounded-lg border border-zinc-200/80 bg-white p-4 shadow-sm shadow-zinc-200/40">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-zinc-900">站点信息</h3>
            <p className="mt-1 text-xs text-zinc-500">
              控制首页标题、简介和公开页面摘要。
            </p>
          </div>
          <span className="max-w-[48%] truncate rounded-full bg-zinc-50 px-2.5 py-1 font-mono text-xs text-zinc-400">
            {siteHome.publicUrl ?? "尚未发布"}
          </span>
        </div>
        <div className="mt-4 grid gap-3">
          <input
            aria-label="站点名称"
            className="h-10 rounded-md border border-transparent bg-zinc-50 px-3 text-base font-semibold outline-none transition hover:bg-zinc-100 focus:border-teal-300 focus:bg-white focus:ring-2 focus:ring-teal-100"
            onChange={(event) => handleSiteNameChange(event.target.value)}
            placeholder="站点名称"
            value={siteName}
          />
          <textarea
            aria-label="站点说明"
            className="min-h-14 resize-none rounded-md border border-transparent bg-zinc-50 px-3 py-2 text-sm leading-5 text-zinc-700 outline-none transition hover:bg-zinc-100 focus:border-teal-300 focus:bg-white focus:ring-2 focus:ring-teal-100"
            onChange={(event) => handleDescriptionChange(event.target.value)}
            placeholder="站点说明"
            value={description}
          />
        </div>
      </section>

      <section className="rounded-md border border-zinc-200 bg-white">
        <div className="flex h-11 items-center justify-between border-b border-zinc-200 px-4">
          <h3 className="text-sm font-semibold">首页模块</h3>
          <span className="text-xs text-zinc-400">配置</span>
        </div>
        <div className="grid gap-4 p-4">
          <div className="flex items-center justify-between gap-3 rounded-md bg-zinc-50 px-3 py-2">
            <div>
              <p className="text-sm font-medium">最近发布题目数量</p>
              <p className="mt-0.5 text-xs text-zinc-500">
                控制首页最近题目模块的展示条数
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                className="size-7 rounded border border-zinc-200 bg-white text-sm disabled:opacity-40"
                disabled={recentProblemLimit <= 1}
                onClick={() =>
                  handleRecentProblemLimitChange(
                    Math.max(1, recentProblemLimit - 1),
                  )
                }
                type="button"
              >
                -
              </button>
              <span className="w-8 text-center text-sm font-medium">
                {recentProblemLimit}
              </span>
              <button
                className="size-7 rounded border border-zinc-200 bg-white text-sm disabled:opacity-40"
                disabled={recentProblemLimit >= 24}
                onClick={() =>
                  handleRecentProblemLimitChange(
                    Math.min(24, recentProblemLimit + 1),
                  )
                }
                type="button"
              >
                +
              </button>
            </div>
          </div>

          <div>
            <label className="text-sm font-medium" htmlFor="knowledgeTags">
              知识点标签
            </label>
            <textarea
              className="mt-2 min-h-20 w-full resize-none rounded-md border border-zinc-200 px-3 py-2 text-sm leading-5 outline-none transition focus:border-teal-400 focus:ring-2 focus:ring-teal-100"
              id="knowledgeTags"
              onChange={(event) =>
                handleKnowledgeTagsTextChange(event.target.value)
              }
              value={knowledgeTagsText}
            />
            <div className="mt-2 flex flex-wrap gap-2">
              {knowledgeTags.map((tag) => (
                <span
                  className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-1 text-xs text-zinc-600"
                  key={tag}
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-md border border-zinc-200 bg-white">
        <div className="flex min-h-11 items-center justify-between gap-3 border-b border-zinc-200 px-4 py-2">
          <h3 className="text-sm font-semibold">精选专题</h3>
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <button
              className="rounded-md border border-zinc-200 bg-white px-2.5 py-1 font-medium text-zinc-600 transition hover:bg-zinc-50 disabled:opacity-40"
              disabled={!availableTopics.length}
              onClick={() => setIsAddTopicOpen(true)}
              type="button"
            >
              添加专题
            </button>
            <span>{featuredTopics.length} 个</span>
          </div>
        </div>
        <div className="divide-y divide-zinc-100">
          {featuredTopics.length ? (
            featuredTopics.map((topic, index) => (
              <FeaturedTopicRow
                canMoveDown={index < featuredTopics.length - 1}
                canMoveUp={index > 0}
                key={topic.id}
                topic={topic}
                onMoveDown={() => moveFeaturedTopic(topic.id, "down")}
                onMoveUp={() => moveFeaturedTopic(topic.id, "up")}
                onOpen={() => onOpenTopic(topic.id)}
                onRemove={() => setTopicPendingRemoval(topic)}
              />
            ))
          ) : (
            <p className="px-4 py-8 text-sm text-zinc-500">
              暂无精选专题。
            </p>
          )}
        </div>
      </section>
      {isAddTopicOpen ? (
        <AddFeaturedTopicDialog
          topics={availableTopics}
          onAdd={(topicId) => {
            addFeaturedTopic(topicId);
          }}
          onClose={() => setIsAddTopicOpen(false)}
        />
      ) : null}
      {topicPendingRemoval ? (
        <ConfirmRemoveFeaturedTopicDialog
          topic={topicPendingRemoval}
          onCancel={() => setTopicPendingRemoval(null)}
          onConfirm={() => {
            removeFeaturedTopic(topicPendingRemoval.id);
            setTopicPendingRemoval(null);
          }}
        />
      ) : null}
    </div>
  );
}

function FeaturedTopicRow({
  canMoveDown,
  canMoveUp,
  onMoveDown,
  onMoveUp,
  onOpen,
  onRemove,
  topic,
}: {
  canMoveDown: boolean;
  canMoveUp: boolean;
  onMoveDown: () => void;
  onMoveUp: () => void;
  onOpen: () => void;
  onRemove: () => void;
  topic: Topic;
}) {
  return (
    <div className="flex min-h-11 items-center gap-2 px-4 text-sm">
      <span className="cursor-grab text-zinc-300">⋮⋮</span>
      <span className="min-w-0 flex-1 truncate font-medium">
        {topic.title}
      </span>
      <span className="hidden min-w-0 max-w-48 truncate text-xs text-zinc-400 xl:block">
        {topic.description}
      </span>
      <span className="shrink-0 rounded-full border border-zinc-200 px-2 py-0.5 text-xs text-zinc-500">
        {publishStatusLabel(topic.status)}
      </span>
      <span className="w-14 shrink-0 text-right text-xs text-zinc-400">
        {topic.items.length} 题
      </span>
      <button
        className="rounded px-1.5 py-1 text-xs text-zinc-500 transition hover:bg-zinc-50 hover:text-zinc-800 disabled:opacity-35"
        disabled={!canMoveUp}
        onClick={onMoveUp}
        type="button"
      >
        上移
      </button>
      <button
        className="rounded px-1.5 py-1 text-xs text-zinc-500 transition hover:bg-zinc-50 hover:text-zinc-800 disabled:opacity-35"
        disabled={!canMoveDown}
        onClick={onMoveDown}
        type="button"
      >
        下移
      </button>
      <button
        className="rounded px-1.5 py-1 text-xs text-zinc-500 transition hover:bg-zinc-50 hover:text-zinc-800"
        onClick={onOpen}
        type="button"
      >
        打开
      </button>
      <button
        className="rounded px-1.5 py-1 text-xs text-red-500 transition hover:bg-red-50"
        onClick={onRemove}
        type="button"
      >
        删除
      </button>
    </div>
  );
}

function AddFeaturedTopicDialog({
  onAdd,
  onClose,
  topics,
}: {
  onAdd: (topicId: string) => void;
  onClose: () => void;
  topics: Topic[];
}) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const results = useMemo(() => {
    const normalizedQuery = normalizeSearchText(query);

    if (!normalizedQuery) {
      return topics.slice(0, 8);
    }

    return topics
      .filter((topic) =>
        normalizeSearchText(
          `${topic.title} ${topic.description} ${topic.items.length}`,
        ).includes(normalizedQuery),
      )
      .slice(0, 12);
  }, [query, topics]);

  useEffect(() => {
    inputRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  function handleAdd(topicId: string) {
    onAdd(topicId);
    onClose();
  }

  return (
    <div
      className="absolute inset-0 z-50 flex items-start justify-center bg-zinc-950/15 px-4 pt-[10vh]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
      role="presentation"
    >
      <div
        aria-label="添加精选专题"
        className="w-full max-w-xl overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-2xl"
        role="dialog"
      >
        <div className="border-b border-zinc-100 px-4 py-3">
          <input
            className="w-full bg-transparent text-base outline-none placeholder:text-zinc-400"
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && results[0]) {
                event.preventDefault();
                handleAdd(results[0].id);
              }
            }}
            placeholder="搜索并添加专题"
            ref={inputRef}
            value={query}
          />
        </div>
        <div className="max-h-[56vh] overflow-y-auto p-2">
          {results.length ? (
            results.map((topic) => (
              <div
                className="flex items-center gap-3 rounded-lg px-3 py-2.5 transition hover:bg-zinc-50"
                key={topic.id}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-zinc-900">
                    {topic.title}
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-zinc-500">
                    {topic.description || `${topic.items.length} 个题目`}
                  </span>
                </span>
                <button
                  className="shrink-0 rounded-md border border-teal-200 bg-teal-50 px-2.5 py-1 text-xs font-medium text-teal-700 transition hover:bg-teal-100"
                  onClick={() => handleAdd(topic.id)}
                  type="button"
                >
                  添加
                </button>
              </div>
            ))
          ) : (
            <div className="px-3 py-8 text-center text-sm text-zinc-500">
              没有可添加的专题
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ConfirmRemoveFeaturedTopicDialog({
  onCancel,
  onConfirm,
  topic,
}: {
  onCancel: () => void;
  onConfirm: () => void;
  topic: Topic;
}) {
  return (
    <div
      className="absolute inset-0 z-50 flex items-center justify-center bg-zinc-950/15 px-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onCancel();
        }
      }}
      role="presentation"
    >
      <div
        aria-label="确认删除精选专题"
        className="w-full max-w-sm rounded-xl border border-zinc-200 bg-white p-4 shadow-2xl"
        role="dialog"
      >
        <h3 className="text-sm font-semibold text-zinc-900">删除精选专题</h3>
        <p className="mt-2 text-sm leading-6 text-zinc-600">
          确定从首页精选中删除「{topic.title}」吗？专题本身不会被删除。
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            className="rounded-md px-3 py-1.5 text-sm text-zinc-500 transition hover:bg-zinc-100"
            onClick={onCancel}
            type="button"
          >
            取消
          </button>
          <button
            className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-red-700"
            onClick={onConfirm}
            type="button"
          >
            删除
          </button>
        </div>
      </div>
    </div>
  );
}

function normalizeSearchText(value: string): string {
  return value.trim().toLowerCase();
}
