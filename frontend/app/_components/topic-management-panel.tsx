"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  acceptTopicSuggestedProblem,
  addTopicItem,
  deleteTopicItem,
  getTopicSuggestedProblems,
  ignoreTopicSuggestedProblem,
  patchTopic,
  reorderTopicItems,
} from "@/lib/api/client";
import { getAutosaveDelayMs } from "@/lib/autosave/scheduler";
import type {
  Problem,
  SuggestedProblem,
  Topic,
  TopicItem,
} from "@/lib/contracts";

import {
  mergeAcceptedSuggestion,
  moveTopicItem,
  paginateItems,
  publishStatusLabel,
  removeSuggestedProblem,
  type AutosaveState,
} from "./workspace-model";
import { useLatestRef } from "./use-latest-ref";

const PAGE_SIZE = 10;

export function TopicManagementPanel({
  onAutosaveErrorChange,
  onAutosaveStateChange,
  onOpenProblem,
  onTopicChange,
  problems,
  topic,
}: {
  onAutosaveErrorChange: (message: string | null) => void;
  onAutosaveStateChange: (state: AutosaveState) => void;
  onOpenProblem: (problemId: string) => void;
  onTopicChange: (topic: Topic) => void;
  problems: Problem[];
  topic: Topic;
}) {
  const [title, setTitle] = useState(topic.title);
  const [description, setDescription] = useState(topic.description);
  const [suggestions, setSuggestions] = useState(topic.suggestedProblems);
  const [isSuggestionsOpen, setIsSuggestionsOpen] = useState(false);
  const [isAddProblemOpen, setIsAddProblemOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [itemPendingRemoval, setItemPendingRemoval] =
    useState<TopicItem | null>(null);
  const [rescheduleToken, setRescheduleToken] = useState(0);
  const lastSaveStartedAtRef = useRef<number | null>(null);
  const dirtyVersionRef = useRef(0);
  const isSavingRef = useRef(false);
  const sortedItems = useMemo(
    () => [...topic.items].sort((a, b) => a.order - b.order),
    [topic.items],
  );
  const availableProblems = problems.filter(
    (problem) => !topic.items.some((item) => item.problemId === problem.id),
  );
  const paginatedItems = paginateItems(sortedItems, page, PAGE_SIZE);
  const hasDraftChanges =
    title !== topic.title || description !== topic.description;
  const autosaveRef = useLatestRef({
    description,
    onAutosaveErrorChange,
    onAutosaveStateChange,
    onTopicChange,
    suggestions,
    title,
    topicId: topic.id,
    topicItems: topic.items,
  });

  useEffect(() => {
    let isActive = true;

    getTopicSuggestedProblems(topic.id)
      .then(({ suggestedProblems }) => {
        if (isActive) {
          setSuggestions(suggestedProblems);
        }
      })
      .catch(() => undefined);

    return () => {
      isActive = false;
    };
  }, [topic.id]);

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

      patchTopic(latest.topicId, {
        patch: {
          description: latest.description,
          title: latest.title,
        },
      })
        .then(({ topic: patchedTopic }) => {
          // Mock PATCH focuses on status timestamps; keep local list state from
          // this editing session instead of falling back to fixture contents.
          latest.onTopicChange({
            ...patchedTopic,
            items: latest.topicItems,
            suggestedProblems: latest.suggestions,
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
            error instanceof Error ? error.message : "专题保存失败。",
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
    hasDraftChanges,
    rescheduleToken,
    title,
    topic.id,
  ]);

  function handleTitleChange(nextTitle: string) {
    lastSaveStartedAtRef.current ??= Date.now();
    dirtyVersionRef.current += 1;
    onAutosaveErrorChange(null);
    setTitle(nextTitle);
  }

  function handleDescriptionChange(nextDescription: string) {
    lastSaveStartedAtRef.current ??= Date.now();
    dirtyVersionRef.current += 1;
    onAutosaveErrorChange(null);
    setDescription(nextDescription);
  }

  async function handleAcceptSuggestion(suggestion: SuggestedProblem) {
    const { item, topic: responseTopic } = await acceptTopicSuggestedProblem(
      topic.id,
      suggestion.id,
    );
    const nextTopic = {
      ...mergeAcceptedSuggestion(topic, item, suggestion.id),
      autosavedAt: responseTopic.autosavedAt,
      status: responseTopic.status,
      updatedAt: responseTopic.updatedAt,
    };

    setSuggestions((current) => removeSuggestedProblem(current, suggestion.id));
    onTopicChange(nextTopic);
  }

  async function handleIgnoreSuggestion(suggestionId: string) {
    const { topic: responseTopic } = await ignoreTopicSuggestedProblem(
      topic.id,
      suggestionId,
    );
    const nextSuggestions = removeSuggestedProblem(suggestions, suggestionId);

    setSuggestions(nextSuggestions);
    onTopicChange({
      ...topic,
      autosavedAt: responseTopic.autosavedAt,
      status: responseTopic.status,
      suggestedProblems: nextSuggestions,
      updatedAt: responseTopic.updatedAt,
    });
  }

  async function handleRemoveItem(itemId: string) {
    const { topic: responseTopic } = await deleteTopicItem(topic.id, itemId);
    onTopicChange({
      ...topic,
      autosavedAt: responseTopic.autosavedAt,
      items: topic.items.filter((item) => item.id !== itemId),
      status: responseTopic.status,
      updatedAt: responseTopic.updatedAt,
    });
  }

  async function handleAddProblem(problemId: string) {
    const problem = problems.find((item) => item.id === problemId);

    if (!problem) {
      return;
    }

    const { item, topic: responseTopic } = await addTopicItem(topic.id, {
      problemId: problem.id,
      status: problem.status,
      tags: problem.tags,
      title: problem.title,
    });

    onTopicChange({
      ...topic,
      autosavedAt: responseTopic.autosavedAt,
      items: [...topic.items, { ...item, order: topic.items.length + 1 }],
      status: responseTopic.status,
      updatedAt: responseTopic.updatedAt,
    });
  }

  async function handleMoveItem(itemId: string, direction: "down" | "up") {
    const nextItems = moveTopicItem(sortedItems, itemId, direction);
    const { topic: responseTopic } = await reorderTopicItems(topic.id, {
      itemIds: nextItems.map((item) => item.id),
    });

    onTopicChange({
      ...topic,
      autosavedAt: responseTopic.autosavedAt,
      items: nextItems,
      status: responseTopic.status,
      updatedAt: responseTopic.updatedAt,
    });
  }

  return (
    <div className="relative mx-auto min-h-[calc(100vh-9rem)] w-full max-w-[860px] space-y-4">
      <section className="rounded-lg border border-zinc-200/80 bg-white p-4 shadow-sm shadow-zinc-200/40">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-zinc-900">
              专题基础信息
            </h3>
            <p className="mt-1 text-xs text-zinc-500">
              用于左侧列表、专题页标题和公开页面摘要。
            </p>
          </div>
          <span className="max-w-[48%] truncate rounded-full bg-zinc-50 px-2.5 py-1 font-mono text-xs text-zinc-400">
            {topic.publicUrl ?? "尚未发布"}
          </span>
        </div>
        <div className="mt-4 grid gap-3">
          <input
            aria-label="专题标题"
            className="h-10 rounded-md border border-transparent bg-zinc-50 px-3 text-base font-semibold outline-none transition hover:bg-zinc-100 focus:border-teal-300 focus:bg-white focus:ring-2 focus:ring-teal-100"
            onChange={(event) => handleTitleChange(event.target.value)}
            placeholder="专题标题"
            value={title}
          />
          <textarea
            aria-label="专题说明"
            className="min-h-14 resize-none rounded-md border border-transparent bg-zinc-50 px-3 py-2 text-sm leading-5 text-zinc-700 outline-none transition hover:bg-zinc-100 focus:border-teal-300 focus:bg-white focus:ring-2 focus:ring-teal-100"
            onChange={(event) => handleDescriptionChange(event.target.value)}
            placeholder="专题说明"
            value={description}
          />
        </div>
      </section>

      <section className="rounded-md border border-teal-100 bg-teal-50/70 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-teal-950">
              新题归类建议
            </h3>
            <p className="mt-1 text-sm text-teal-700">
              发现 {suggestions.length} 道可能属于本专题的新题
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              className="rounded-md border border-teal-200 bg-white px-2.5 py-1 text-xs font-medium text-teal-700 transition hover:bg-teal-50"
              onClick={() => setIsSuggestionsOpen((current) => !current)}
              type="button"
            >
              {isSuggestionsOpen ? "收起建议" : "查看建议"}
            </button>
            <button
              className="rounded-md px-2.5 py-1 text-xs font-medium text-teal-700 transition hover:bg-white/70"
              disabled={!suggestions.length}
              onClick={() => {
                const nextTopic = { ...topic, suggestedProblems: [] };
                setSuggestions([]);
                onTopicChange(nextTopic);
              }}
              type="button"
            >
              全部忽略
            </button>
          </div>
        </div>
        {isSuggestionsOpen ? (
          <div className="mt-3 space-y-2">
            {suggestions.map((suggestion) => (
              <SuggestionRow
                key={suggestion.id}
                suggestion={suggestion}
                onAccept={() => handleAcceptSuggestion(suggestion)}
                onIgnore={() => handleIgnoreSuggestion(suggestion.id)}
              />
            ))}
          </div>
        ) : null}
      </section>

      <section className="rounded-md border border-zinc-200 bg-white">
        <div className="flex min-h-11 items-center justify-between gap-3 border-b border-zinc-200 px-4 py-2">
          <h3 className="text-sm font-semibold">专题内题目</h3>
          <div className="flex min-w-0 items-center gap-2 text-xs text-zinc-500">
            <button
              className="rounded-md border border-zinc-200 bg-white px-2.5 py-1 font-medium text-zinc-600 transition hover:bg-zinc-50 disabled:opacity-40"
              disabled={!availableProblems.length}
              onClick={() => setIsAddProblemOpen(true)}
              type="button"
            >
              添加题目
            </button>
            <span>
              {paginatedItems.total
                ? `${(paginatedItems.page - 1) * PAGE_SIZE + 1}-${Math.min(
                    paginatedItems.page * PAGE_SIZE,
                    paginatedItems.total,
                  )} / ${paginatedItems.total}`
                : "0 / 0"}
            </span>
            <button
              className="rounded border border-zinc-200 px-2 py-1 disabled:opacity-40"
              disabled={paginatedItems.page <= 1}
              onClick={() => setPage((current) => current - 1)}
              type="button"
            >
              上一页
            </button>
            <button
              className="rounded border border-zinc-200 px-2 py-1 disabled:opacity-40"
              disabled={paginatedItems.page >= paginatedItems.pageCount}
              onClick={() => setPage((current) => current + 1)}
              type="button"
            >
              下一页
            </button>
          </div>
        </div>
        <div className="divide-y divide-zinc-100">
          {paginatedItems.items.length ? (
            paginatedItems.items.map((item) => (
              <TopicItemRow
                canMoveDown={
                  sortedItems.findIndex(
                    (sortedItem) => sortedItem.id === item.id,
                  ) < sortedItems.length - 1
                }
                canMoveUp={
                  sortedItems.findIndex(
                    (sortedItem) => sortedItem.id === item.id,
                  ) > 0
                }
                item={item}
                key={item.id}
                problem={problems.find(
                  (problem) => problem.id === item.problemId,
                )}
                onMoveDown={() => handleMoveItem(item.id, "down")}
                onMoveUp={() => handleMoveItem(item.id, "up")}
                onOpen={() => onOpenProblem(item.problemId)}
                onRemove={() => setItemPendingRemoval(item)}
              />
            ))
          ) : (
            <p className="px-4 py-8 text-sm text-zinc-500">
              暂无已收录题目。
            </p>
          )}
        </div>
      </section>
      {isAddProblemOpen ? (
        <AddTopicProblemDialog
          problems={availableProblems}
          onAdd={handleAddProblem}
          onClose={() => setIsAddProblemOpen(false)}
        />
      ) : null}
      {itemPendingRemoval ? (
        <ConfirmRemoveTopicItemDialog
          item={itemPendingRemoval}
          onCancel={() => setItemPendingRemoval(null)}
          onConfirm={() => {
            const itemId = itemPendingRemoval.id;
            setItemPendingRemoval(null);
            void handleRemoveItem(itemId);
          }}
        />
      ) : null}
    </div>
  );
}

function SuggestionRow({
  onAccept,
  onIgnore,
  suggestion,
}: {
  onAccept: () => void;
  onIgnore: () => void;
  suggestion: SuggestedProblem;
}) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-teal-100 bg-white px-3 py-2 text-sm">
      <span className="size-2 rounded-full bg-teal-500" />
      <span className="min-w-0 flex-1 truncate font-medium">
        {suggestion.title}
      </span>
      <span className="hidden min-w-0 flex-1 truncate text-xs text-zinc-500 lg:block">
        {suggestion.reason}
      </span>
      <button
        className="rounded px-2 py-1 text-xs font-medium text-teal-700 hover:bg-teal-50"
        onClick={onAccept}
        type="button"
      >
        接受
      </button>
      <button
        className="rounded px-2 py-1 text-xs font-medium text-zinc-500 hover:bg-zinc-50"
        onClick={onIgnore}
        type="button"
      >
        忽略
      </button>
    </div>
  );
}

function AddTopicProblemDialog({
  onAdd,
  onClose,
  problems,
}: {
  onAdd: (problemId: string) => Promise<void>;
  onClose: () => void;
  problems: Problem[];
}) {
  const [query, setQuery] = useState("");
  const [addingProblemId, setAddingProblemId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const results = useMemo(() => {
    const normalizedQuery = normalizeSearchText(query);

    if (!normalizedQuery) {
      return problems.slice(0, 8);
    }

    return problems
      .filter((problem) =>
        normalizeSearchText(
          `${problem.shortTitle} ${problem.title} ${problem.tags.join(" ")}`,
        ).includes(normalizedQuery),
      )
      .slice(0, 12);
  }, [problems, query]);

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

  async function handleAdd(problemId: string) {
    setAddingProblemId(problemId);
    try {
      await onAdd(problemId);
    } finally {
      setAddingProblemId(null);
    }
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
        aria-label="添加专题题目"
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
                void handleAdd(results[0].id);
              }
            }}
            placeholder="搜索并添加题目"
            ref={inputRef}
            value={query}
          />
        </div>
        <div className="max-h-[56vh] overflow-y-auto p-2">
          {results.length ? (
            results.map((problem) => (
              <div
                className="flex items-center gap-3 rounded-lg px-3 py-2.5 transition hover:bg-zinc-50"
                key={problem.id}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-zinc-900">
                    {problem.shortTitle}
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-zinc-500">
                    {problem.tags.join(" · ") || problem.title}
                  </span>
                </span>
                <button
                  className="shrink-0 rounded-md border border-teal-200 bg-teal-50 px-2.5 py-1 text-xs font-medium text-teal-700 transition hover:bg-teal-100 disabled:opacity-50"
                  disabled={addingProblemId !== null}
                  onClick={() => void handleAdd(problem.id)}
                  type="button"
                >
                  {addingProblemId === problem.id ? "添加中" : "添加"}
                </button>
              </div>
            ))
          ) : (
            <div className="px-3 py-8 text-center text-sm text-zinc-500">
              没有可添加的题目
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ConfirmRemoveTopicItemDialog({
  item,
  onCancel,
  onConfirm,
}: {
  item: TopicItem;
  onCancel: () => void;
  onConfirm: () => void;
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
        aria-label="确认删除专题题目"
        className="w-full max-w-sm rounded-xl border border-zinc-200 bg-white p-4 shadow-2xl"
        role="dialog"
      >
        <h3 className="text-sm font-semibold text-zinc-900">删除题目</h3>
        <p className="mt-2 text-sm leading-6 text-zinc-600">
          确定从当前专题中删除「{item.title}」吗？题目本身不会被删除。
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

function TopicItemRow({
  canMoveDown,
  canMoveUp,
  item,
  onMoveDown,
  onMoveUp,
  onOpen,
  onRemove,
  problem,
}: {
  canMoveDown: boolean;
  canMoveUp: boolean;
  item: TopicItem;
  onMoveDown: () => void;
  onMoveUp: () => void;
  onOpen: () => void;
  onRemove: () => void;
  problem?: Problem;
}) {
  return (
    <div className="flex min-h-11 items-center gap-2 px-4 text-sm">
      <span className="cursor-grab text-zinc-300">⋮⋮</span>
      <span className="min-w-0 flex-1 truncate font-medium">{item.title}</span>
      <span className="hidden truncate text-xs text-zinc-400 xl:block">
        {item.tags.join("、")}
      </span>
      <span className="shrink-0 rounded-full border border-zinc-200 px-2 py-0.5 text-xs text-zinc-500">
        {publishStatusLabel(item.status)}
      </span>
      <span className="w-16 shrink-0 text-right text-xs text-zinc-400">
        {problem ? "已同步" : "mock"}
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

function normalizeSearchText(value: string): string {
  return value.trim().toLowerCase();
}
