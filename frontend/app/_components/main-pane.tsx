import { useState } from "react";

import type {
  Problem,
  ProblemMessage,
  PublishStatus,
  SiteHome,
  Topic,
  UploadJobProgressEvent,
  WebAnnotation,
} from "@/lib/contracts";

import { NewProblemPanel } from "./new-problem-panel";
import { ProblemConversationPanel } from "./problem-conversation-panel";
import { ProblemMetadataPopover } from "./problem-metadata-popover";
import { SiteHomeManagementPanel } from "./site-home-management-panel";
import { TopicManagementPanel } from "./topic-management-panel";
import { AutosaveBadge } from "./ui/autosave-badge";
import {
  publishActionLabel,
  publishStatusLabel,
  type AutosaveState,
  type SelectedWorkspaceObject,
  type WorkspaceSelection,
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
  onSiteHomeChange,
  onSelectionChange,
  onTopicChange,
  onUploadErrorChange,
  onUploadEventsChange,
  pendingAnnotationIds,
  problems,
  problemAnnotations,
  problemConversation,
  selectedObject,
  topics,
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
  onSiteHomeChange: (siteHome: SiteHome) => void;
  onSelectionChange: (selection: WorkspaceSelection) => void;
  onTopicChange: (topic: Topic) => void;
  onUploadErrorChange: (message: string | null) => void;
  onUploadEventsChange: (events: UploadJobProgressEvent[]) => void;
  pendingAnnotationIds: string[];
  problems: Problem[];
  problemAnnotations: WebAnnotation[];
  problemConversation: ProblemMessage[];
  selectedObject: SelectedWorkspaceObject;
  topics: Topic[];
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
          onAutosaveErrorChange={onAutosaveErrorChange}
          onAutosaveStateChange={onAutosaveStateChange}
          onPendingAnnotationRemove={onPendingAnnotationRemove}
          onPendingAnnotationsCommitted={onPendingAnnotationsCommitted}
          onSiteHomeChange={onSiteHomeChange}
          onSelectionChange={onSelectionChange}
          onTopicChange={onTopicChange}
          onUploadErrorChange={onUploadErrorChange}
          onUploadEventsChange={onUploadEventsChange}
          pendingAnnotationIds={pendingAnnotationIds}
          problems={problems}
          problemAnnotations={problemAnnotations}
          problemConversation={problemConversation}
          topics={topics}
        />
      </div>
    </section>
  );
}

function MainContent({
  onAutosaveErrorChange,
  onAutosaveStateChange,
  onProblemCreated,
  onProblemConversationChange,
  onProblemEdited,
  onPendingAnnotationRemove,
  onPendingAnnotationsCommitted,
  onSiteHomeChange,
  onSelectionChange,
  onTopicChange,
  onUploadErrorChange,
  onUploadEventsChange,
  pendingAnnotationIds,
  problems,
  problemAnnotations,
  problemConversation,
  selectedObject,
  topics,
}: {
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
  onPendingAnnotationRemove: (
    problemId: string,
    annotationId: string,
  ) => void;
  onPendingAnnotationsCommitted: (problemId: string) => void;
  onSiteHomeChange: (siteHome: SiteHome) => void;
  onSelectionChange: (selection: WorkspaceSelection) => void;
  onTopicChange: (topic: Topic) => void;
  onUploadErrorChange: (message: string | null) => void;
  onUploadEventsChange: (events: UploadJobProgressEvent[]) => void;
  pendingAnnotationIds: string[];
  problems: Problem[];
  problemAnnotations: WebAnnotation[];
  problemConversation: ProblemMessage[];
  selectedObject: SelectedWorkspaceObject;
  topics: Topic[];
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
    return (
      <SiteHomeManagementPanel
        key={selectedObject.item.id}
        siteHome={selectedObject.item}
        topics={topics}
        onAutosaveErrorChange={onAutosaveErrorChange}
        onAutosaveStateChange={onAutosaveStateChange}
        onOpenTopic={(topicId) =>
          onSelectionChange({ kind: "topic", id: topicId })
        }
        onSiteHomeChange={onSiteHomeChange}
      />
    );
  }

  return (
    <TopicManagementPanel
      key={selectedObject.item.id}
      problems={problems}
      topic={selectedObject.item}
      onAutosaveErrorChange={onAutosaveErrorChange}
      onAutosaveStateChange={onAutosaveStateChange}
      onOpenProblem={(problemId) =>
        onSelectionChange({ kind: "problem", id: problemId })
      }
      onTopicChange={onTopicChange}
    />
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
