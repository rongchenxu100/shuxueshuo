import { useCallback, useEffect, useRef, useState } from "react";

import { patchProblem } from "@/lib/api/client";
import type { Problem } from "@/lib/contracts";
import { getAutosaveDelayMs } from "@/lib/autosave/scheduler";

import type { AutosaveState } from "./workspace-model";
import { SlidersIcon } from "./ui/icons";

export function ProblemMetadataPopover({
  onAutosaveErrorChange,
  onAutosaveStateChange,
  onProblemDraftChange,
  onProblemPatched,
  problem,
}: {
  onAutosaveErrorChange: (message: string | null) => void;
  onAutosaveStateChange: (state: AutosaveState) => void;
  onProblemDraftChange: (
    problemId: string,
    patch: { title?: string; tags?: string[] },
  ) => void;
  onProblemPatched: (problem: Problem) => void;
  problem: Problem;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [title, setTitle] = useState(problem.title);
  const [tagsText, setTagsText] = useState(problem.tags.join("，"));
  const [hasDirtyChanges, setHasDirtyChanges] = useState(false);
  const [rescheduleToken, setRescheduleToken] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const latestDraftRef = useRef({
    tags: problem.tags,
    tagsText: problem.tags.join("，"),
    title: problem.title,
  });
  const lastSaveStartedAtRef = useRef<number | null>(null);
  const dirtyVersionRef = useRef(0);
  const isSavingRef = useRef(false);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      if (
        event.target instanceof Node &&
        containerRef.current?.contains(event.target)
      ) {
        return;
      }

      setIsOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  function handleTitleChange(nextTitle: string) {
    const nextTags = latestDraftRef.current.tags;
    setTitle(nextTitle);
    markDirty(nextTitle, latestDraftRef.current.tagsText, nextTags);
    onProblemDraftChange(problem.id, {
      tags: nextTags,
      title: nextTitle,
    });
  }

  function handleTagsChange(nextTagsText: string) {
    const nextTags = parseTags(nextTagsText);
    setTagsText(nextTagsText);
    markDirty(latestDraftRef.current.title, nextTagsText, nextTags);
    onProblemDraftChange(problem.id, {
      tags: nextTags,
      title: latestDraftRef.current.title,
    });
  }

  function markDirty(
    nextTitle: string,
    nextTagsText: string,
    nextTags: string[],
  ) {
    latestDraftRef.current = {
      tags: nextTags,
      tagsText: nextTagsText,
      title: nextTitle,
    };
    dirtyVersionRef.current += 1;
    setHasDirtyChanges(true);
    onAutosaveErrorChange(null);
  }

  const saveDraft = useCallback(async () => {
    if (isSavingRef.current || !hasDirtyChanges) {
      return;
    }

    const savedVersion = dirtyVersionRef.current;
    const draft = latestDraftRef.current;
    isSavingRef.current = true;
    lastSaveStartedAtRef.current = Date.now();
    onAutosaveStateChange("saving");

    try {
      const response = await patchProblem(problem.id, {
        expectedAutosavedAt: problem.autosavedAt,
        patch: {
          tags: draft.tags,
          title: draft.title,
        },
      });
      onProblemPatched(response.problem);

      if (dirtyVersionRef.current === savedVersion) {
        setHasDirtyChanges(false);
        onAutosaveErrorChange(null);
        onAutosaveStateChange("saved");
      } else {
        setRescheduleToken((current) => current + 1);
      }
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "保存失败，请稍后重试。";
      onAutosaveErrorChange(message);
      onAutosaveStateChange("error");
      setHasDirtyChanges(true);
    } finally {
      isSavingRef.current = false;
    }
  }, [
    hasDirtyChanges,
    onAutosaveErrorChange,
    onAutosaveStateChange,
    onProblemPatched,
    problem.autosavedAt,
    problem.id,
  ]);

  useEffect(() => {
    if (!hasDirtyChanges) {
      return;
    }

    const delayMs = getAutosaveDelayMs(
      lastSaveStartedAtRef.current,
      Date.now(),
    );
    const timeoutId = window.setTimeout(() => {
      void saveDraft();
    }, delayMs);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [hasDirtyChanges, problem.id, rescheduleToken, saveDraft, tagsText, title]);

  return (
    <div className="relative" ref={containerRef}>
      <button
        aria-label="编辑题目信息"
        aria-expanded={isOpen}
        className="flex size-7 items-center justify-center rounded-md text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-800"
        onClick={() => setIsOpen((current) => !current)}
        title="编辑题目信息"
        type="button"
      >
        <SlidersIcon className="size-4" />
      </button>
      {isOpen ? (
        <div className="absolute right-0 top-9 z-30 w-80 rounded-lg border border-zinc-200 bg-white p-4 text-left shadow-xl">
          <label className="block">
            <span className="text-xs font-medium text-zinc-500">标题</span>
            <input
              className="mt-1 h-9 w-full rounded-md border border-zinc-200 px-3 text-sm outline-none transition focus:border-teal-400"
              onChange={(event) => handleTitleChange(event.target.value)}
              value={title}
            />
          </label>
          <label className="mt-3 block">
            <span className="text-xs font-medium text-zinc-500">标签</span>
            <textarea
              className="mt-1 min-h-20 w-full resize-none rounded-md border border-zinc-200 px-3 py-2 text-sm leading-5 outline-none transition focus:border-teal-400"
              onChange={(event) => handleTagsChange(event.target.value)}
              value={tagsText}
            />
          </label>
          <p className="mt-2 text-xs leading-5 text-zinc-500">
            支持用中文顿号、逗号或换行分隔标签。
          </p>
        </div>
      ) : null}
    </div>
  );
}

function parseTags(value: string): string[] {
  return value
    .split(/[，,、\n]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}
