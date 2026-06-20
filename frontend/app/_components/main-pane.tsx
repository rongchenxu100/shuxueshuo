import type {
  Problem,
  ProblemMessage,
  Topic,
  UploadJobProgressEvent,
} from "@/lib/contracts";

import { NewProblemPanel } from "./new-problem-panel";
import { ProblemConversationPanel } from "./problem-conversation-panel";
import { ProblemMetadataPopover } from "./problem-metadata-popover";
import { AutosaveBadge } from "./ui/autosave-badge";
import { HeaderBlock } from "./ui/header-block";
import { InfoGroup } from "./ui/info-group";
import { PlaceholderContent } from "./ui/placeholder-content";
import {
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
  onUploadErrorChange,
  onUploadEventsChange,
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
  onUploadErrorChange: (message: string | null) => void;
  onUploadEventsChange: (events: UploadJobProgressEvent[]) => void;
  problemConversation: ProblemMessage[];
  selectedObject: SelectedWorkspaceObject;
}) {
  const showAutosave = hasAutosaveSemantics(selectedObject);
  const shouldLockContent =
    selectedObject.kind === "new_problem" || selectedObject.kind === "problem";
  const statusLabel = mainStatusLabel(selectedObject);

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
          onUploadErrorChange={onUploadErrorChange}
          onUploadEventsChange={onUploadEventsChange}
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
  onUploadErrorChange,
  onUploadEventsChange,
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
  onUploadErrorChange: (message: string | null) => void;
  onUploadEventsChange: (events: UploadJobProgressEvent[]) => void;
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
        problem={selectedObject.item}
        onProblemEdited={onProblemEdited}
        onConversationChange={onProblemConversationChange}
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
