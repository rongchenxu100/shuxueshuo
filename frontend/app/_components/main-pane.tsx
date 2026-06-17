import type { Problem, Topic } from "@/lib/contracts";

import { AutosaveBadge } from "./ui/autosave-badge";
import { HeaderBlock } from "./ui/header-block";
import { InfoGroup } from "./ui/info-group";
import { ModePill } from "./ui/mode-pill";
import { PlaceholderContent } from "./ui/placeholder-content";
import {
  publishStatusLabel,
  type AutosaveState,
  type SelectedWorkspaceObject,
} from "./workspace-model";

export function MainPane({
  autosaveState,
  selectedObject,
}: {
  autosaveState: AutosaveState;
  selectedObject: SelectedWorkspaceObject;
}) {
  const showAutosave = hasAutosaveSemantics(selectedObject);

  return (
    <section className="flex h-full flex-col border-r border-zinc-200 bg-zinc-50">
      <div className="border-b border-zinc-200 bg-white px-6 py-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-xs font-medium text-zinc-500">中间编辑区</p>
            <h2 className="mt-1 text-xl font-semibold">
              {mainTitle(selectedObject)}
            </h2>
          </div>
          {showAutosave ? <AutosaveBadge state={autosaveState} /> : null}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <MainContent selectedObject={selectedObject} />
      </div>
    </section>
  );
}

function MainContent({
  selectedObject,
}: {
  selectedObject: SelectedWorkspaceObject;
}) {
  if (selectedObject.kind === "new_problem") {
    return (
      <PlaceholderContent
        description="后续会在这里接入图片上传、OCR 进度和生成任务。"
        title="新建题目"
      />
    );
  }

  if (selectedObject.kind === "search") {
    return (
      <PlaceholderContent
        description="后续会在这里接入题目标题、标签和状态筛选。"
        title="搜索题目"
      />
    );
  }

  if (selectedObject.kind === "problem") {
    return <ProblemEditorPlaceholder problem={selectedObject.item} />;
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

function ProblemEditorPlaceholder({ problem }: { problem: Problem }) {
  return (
    <div className="space-y-6">
      <HeaderBlock
        description={problem.tags.join("、")}
        status={problem.status}
        title={problem.title}
      />
      <div className="grid grid-cols-2 gap-3">
        <ModePill active label="编辑模式" />
        <ModePill label="对话模式" />
      </div>
      <PlaceholderContent
        description="后续会在这里显示作者对话、注释组消息和底部输入框。"
        title="题目编辑占位"
      />
      <PlaceholderContent
        description="Phase 1 不发送消息，只预留对话区域。"
        title="后续对话区域占位"
      />
    </div>
  );
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

  if (selectedObject.kind === "search") {
    return "搜索题目";
  }

  if (selectedObject.kind === "problem") {
    return selectedObject.item.shortTitle;
  }

  if (selectedObject.kind === "site_home") {
    return "网站首页";
  }

  return selectedObject.item.title;
}
