import { useState } from "react";

import type {
  Problem,
  ProblemMessage,
  PublishStatus,
  Topic,
  UploadJobProgressEvent,
  WebAnnotation,
} from "@/lib/contracts";

import { NewProblemPanel } from "./new-problem-panel";
import { ProblemConversationPanel } from "./problem-conversation-panel";
import { ProblemMetadataPopover } from "./problem-metadata-popover";
import { AutosaveBadge } from "./ui/autosave-badge";
import { HeaderBlock } from "./ui/header-block";
import { InfoGroup } from "./ui/info-group";
import { PlaceholderContent } from "./ui/placeholder-content";
import {
  publishActionLabel,
  publishStatusLabel,
  type AutosaveState,
  type SelectedWorkspaceObject,
} from "./workspace-model";

export function MainPane({
  autosaveState,
  autosaveError,
  onAutosaveErrorChange,
  onAutosaveStateChange,
  onProblemCreated,
  onProblemConversationChange,
  onProblemEdited,
  onProblemDraftChange,
  onProblemPatched,
  onPendingAnnotationRemove,
  onPendingAnnotationsCommitted,
  onPublish,
  onUploadErrorChange,
  onUploadEventsChange,
  pendingAnnotationIds,
  problemAnnotations,
  problemConversation,
  selectedObject,
}: {
  autosaveState: AutosaveState;
  autosaveError: string | null;
  onAutosaveErrorChange: (message: string | null) => void;
  onAutosaveStateChange: (state: AutosaveState) => void;
  onProblemCreated: (
    problem: Problem,
    messages: ProblemMessage[],
  ) => void;
  onProblemConversationChange: (
    problemId: string,
    messages: ProblemMessage[],
  ) => void;
  onProblemEdited: (problem: Problem) => void;
  onProblemDraftChange: (
    problemId: string,
    patch: { title?: string; tags?: string[] },
  ) => void;
  onProblemPatched: (problem: Problem) => void;
  onPendingAnnotationRemove: (
    problemId: string,
    annotationId: string,
  ) => void;
  onPendingAnnotationsCommitted: (problemId: string) => void;
  onPublish: (selectedObject: SelectedWorkspaceObject) => Promise<void>;
  onUploadErrorChange: (message: string | null) => void;
  onUploadEventsChange: (events: UploadJobProgressEvent[]) => void;
  pendingAnnotationIds: string[];
  problemAnnotations: WebAnnotation[];
  problemConversation: ProblemMessage[];
  selectedObject: SelectedWorkspaceObject;
}) {
  const showAutosave = hasAutosaveSemantics(selectedObject);
  const shouldLockContent =
    selectedObject.kind === "new_problem" || selectedObject.kind === "problem";
  const statusLabel = mainStatusLabel(selectedObject);
  const publishableObject = getPublishableObject(selectedObject);
  const [isPublishing, setIsPublishing] = useState(false);
  const selectedObjectKey = getSelectedObjectKey(selectedObject);
  const [publishError, setPublishError] = useState<{
    key: string;
    message: string;
  } | null>(null);
  const currentPublishError =
    publishError?.key === selectedObjectKey ? publishError.message : null;

  async function handlePublishClick() {
    if (!publishableObject || isPublishing) {
      return;
    }

    if (
      publishableObject.status === "published" &&
      publishableObject.publicUrl
    ) {
      window.open(publishableObject.publicUrl, "_blank", "noopener,noreferrer");
      return;
    }

    setIsPublishing(true);
    setPublishError(null);

    try {
      await onPublish(selectedObject);
    } catch (error) {
      setPublishError({
        key: selectedObjectKey,
        message:
          error instanceof Error ? error.message : "发布失败，请稍后重试。",
      });
    } finally {
      setIsPublishing(false);
    }
  }

  return (
    <section className="flex h-full min-h-0 min-w-0 flex-col border-r border-zinc-200 bg-zinc-50">
      <div className="h-12 shrink-0 border-b border-zinc-200 bg-white px-4">
        <div className="flex h-full items-center justify-between gap-4">
          <h2 className="truncate text-sm font-medium text-zinc-800">
            {mainTitle(selectedObject)}
          </h2>
          <div className="flex shrink-0 items-center gap-2">
            {statusLabel ? (
              <span className="rounded-full border border-zinc-200 px-2 py-0.5 text-xs text-zinc-500">
                {statusLabel}
              </span>
            ) : null}
            {selectedObject.kind === "problem" ? (
              <ProblemMetadataPopover
                key={selectedObject.item.id}
                problem={selectedObject.item}
                onAutosaveErrorChange={onAutosaveErrorChange}
                onAutosaveStateChange={onAutosaveStateChange}
                onProblemDraftChange={onProblemDraftChange}
                onProblemPatched={onProblemPatched}
              />
            ) : null}
            {showAutosave ? <AutosaveBadge state={autosaveState} /> : null}
            {publishableObject ? (
              <button
                className="rounded-md border border-teal-200 bg-teal-50 px-3 py-1 text-xs font-medium text-teal-700 transition hover:bg-teal-100 disabled:cursor-not-allowed disabled:border-zinc-200 disabled:bg-zinc-100 disabled:text-zinc-400"
                disabled={isPublishing || autosaveState === "saving"}
                onClick={handlePublishClick}
                title={
                  autosaveState === "saving"
                    ? "保存完成后才能发布"
                    : publishActionLabel(
                        publishableObject.status,
                        publishableObject.publicUrl,
                      )
                }
                type="button"
              >
                {isPublishing
                  ? "发布中"
                  : publishActionLabel(
                      publishableObject.status,
                      publishableObject.publicUrl,
                    )}
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <div
        className={
          shouldLockContent
            ? "min-h-0 flex-1 overflow-hidden"
            : "flex-1 overflow-y-auto px-5 py-5"
        }
      >
        {currentPublishError ? (
          <p className="mb-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {currentPublishError}
          </p>
        ) : null}
        {autosaveError && showAutosave ? (
          <p className="mb-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {autosaveError}
          </p>
        ) : null}
        <MainContent
          selectedObject={selectedObject}
          onProblemCreated={onProblemCreated}
          onProblemConversationChange={onProblemConversationChange}
          onProblemEdited={onProblemEdited}
          onPendingAnnotationRemove={onPendingAnnotationRemove}
          onPendingAnnotationsCommitted={onPendingAnnotationsCommitted}
          onUploadErrorChange={onUploadErrorChange}
          onUploadEventsChange={onUploadEventsChange}
          pendingAnnotationIds={pendingAnnotationIds}
          problemAnnotations={problemAnnotations}
          problemConversation={problemConversation}
        />
      </div>
    </section>
  );
}

function MainContent({
  onProblemCreated,
  onProblemConversationChange,
  onProblemEdited,
  onPendingAnnotationRemove,
  onPendingAnnotationsCommitted,
  onUploadErrorChange,
  onUploadEventsChange,
  pendingAnnotationIds,
  problemAnnotations,
  problemConversation,
  selectedObject,
}: {
  onProblemCreated: (
    problem: Problem,
    messages: ProblemMessage[],
  ) => void;
  onProblemConversationChange: (
    problemId: string,
    messages: ProblemMessage[],
  ) => void;
  onProblemEdited: (problem: Problem) => void;
  onPendingAnnotationRemove: (
    problemId: string,
    annotationId: string,
  ) => void;
  onPendingAnnotationsCommitted: (problemId: string) => void;
  onUploadErrorChange: (message: string | null) => void;
  onUploadEventsChange: (events: UploadJobProgressEvent[]) => void;
  pendingAnnotationIds: string[];
  problemAnnotations: WebAnnotation[];
  problemConversation: ProblemMessage[];
  selectedObject: SelectedWorkspaceObject;
}) {
  if (selectedObject.kind === "new_problem") {
    return (
      <NewProblemPanel
        onProblemCreated={onProblemCreated}
        onUploadErrorChange={onUploadErrorChange}
        onUploadEventsChange={onUploadEventsChange}
      />
    );
  }

  if (selectedObject.kind === "problem") {
    return (
      <ProblemConversationPanel
        key={selectedObject.item.id}
        conversation={problemConversation}
        annotations={problemAnnotations}
        pendingAnnotationIds={pendingAnnotationIds}
        problem={selectedObject.item}
        onProblemEdited={onProblemEdited}
        onConversationChange={onProblemConversationChange}
        onPendingAnnotationRemove={onPendingAnnotationRemove}
        onPendingAnnotationsCommitted={onPendingAnnotationsCommitted}
      />
    );
  }

  if (selectedObject.kind === "site_home") {
    const siteHome = selectedObject.item;

    return (
      <div className="space-y-6">
        <HeaderBlock
          description={siteHome.description}
          status={siteHome.status}
          title={siteHome.siteName}
        />
        <InfoGroup
          items={[
            ["精选专题", siteHome.featuredTopicIds.join("、") || "暂无"],
            ["最近发布题目数量", `${siteHome.recentProblemLimit}`],
            ["知识点入口", siteHome.knowledgeTags.join("、")],
          ]}
        />
        <PlaceholderContent
          description="Phase 1 只展示首页配置摘要，Phase 4 再接入可编辑的首页管理。"
          title="首页管理占位"
        />
      </div>
    );
  }

  return <TopicEditorPlaceholder topic={selectedObject.item} />;
}

function TopicEditorPlaceholder({ topic }: { topic: Topic }) {
  return (
    <div className="space-y-6">
      <HeaderBlock
        description={topic.description}
        status={topic.status}
        title={topic.title}
      />
      <InfoGroup
        items={[
          ["已收录题目", `${topic.items.length} 个`],
          ["自动归类建议", `${topic.suggestedProblems.length} 条`],
        ]}
      />
      <section>
        <h3 className="text-sm font-semibold">已收录题目</h3>
        <div className="mt-3 space-y-2">
          {topic.items.length ? (
            topic.items.map((item) => (
              <div
                className="rounded-md border border-zinc-200 bg-white px-4 py-3"
                key={item.id}
              >
                <p className="text-sm font-medium">{item.title}</p>
                <p className="mt-1 text-xs text-zinc-500">
                  {item.tags.join("、")} · {publishStatusLabel(item.status)}
                </p>
              </div>
            ))
          ) : (
            <p className="rounded-md border border-dashed border-zinc-300 px-4 py-6 text-sm text-zinc-500">
              暂无已收录题目。
            </p>
          )}
        </div>
      </section>
      <section>
        <h3 className="text-sm font-semibold">自动归类建议</h3>
        <div className="mt-3 space-y-2">
          {topic.suggestedProblems.length ? (
            topic.suggestedProblems.map((item) => (
              <div
                className="rounded-md border border-zinc-200 bg-white px-4 py-3"
                key={item.id}
              >
                <p className="text-sm font-medium">{item.title}</p>
                <p className="mt-1 text-xs leading-5 text-zinc-500">
                  {item.reason}
                </p>
              </div>
            ))
          ) : (
            <p className="rounded-md border border-dashed border-zinc-300 px-4 py-6 text-sm text-zinc-500">
              暂无建议题目。
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

function hasAutosaveSemantics(
  selectedObject: SelectedWorkspaceObject,
): boolean {
  return (
    selectedObject.kind === "problem" ||
    selectedObject.kind === "site_home" ||
    selectedObject.kind === "topic"
  );
}

function mainTitle(selectedObject: SelectedWorkspaceObject): string {
  if (selectedObject.kind === "new_problem") {
    return "新建题目";
  }

  if (selectedObject.kind === "problem") {
    return selectedObject.item.shortTitle;
  }

  if (selectedObject.kind === "site_home") {
    return "网站首页";
  }

  return selectedObject.item.title;
}

function mainStatusLabel(selectedObject: SelectedWorkspaceObject): string | null {
  if (
    selectedObject.kind === "problem" ||
    selectedObject.kind === "site_home" ||
    selectedObject.kind === "topic"
  ) {
    return publishStatusLabel(selectedObject.item.status);
  }

  return null;
}

function getPublishableObject(
  selectedObject: SelectedWorkspaceObject,
): { publicUrl: string | null; status: PublishStatus } | null {
  if (
    selectedObject.kind === "problem" ||
    selectedObject.kind === "site_home" ||
    selectedObject.kind === "topic"
  ) {
    return {
      publicUrl: selectedObject.item.publicUrl,
      status: selectedObject.item.status,
    };
  }

  return null;
}

function getSelectedObjectKey(selectedObject: SelectedWorkspaceObject): string {
  if (selectedObject.kind === "problem" || selectedObject.kind === "topic") {
    return `${selectedObject.kind}:${selectedObject.item.id}`;
  }

  return selectedObject.kind;
}
