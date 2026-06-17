import type { ReactNode } from "react";

import type { NavResponse } from "@/lib/contracts";

import {
  publishStatusLabel,
  type WorkspaceSelection,
} from "./workspace-model";

export function Sidebar({
  nav,
  selection,
  onSelect,
}: {
  nav: NavResponse;
  selection: WorkspaceSelection;
  onSelect: (selection: WorkspaceSelection) => void;
}) {
  return (
    <aside className="flex h-full flex-col border-r border-zinc-200 bg-white">
      <div className="border-b border-zinc-200 px-5 py-5">
        <p className="text-xs font-medium text-teal-700">Phase 1</p>
        <h1 className="mt-1 text-lg font-semibold tracking-tight">
          创作后台
        </h1>
      </div>

      <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
        <SidebarSection title="入口">
          <SidebarButton
            active={selection.kind === "new_problem"}
            detail="上传或录入题目"
            label="新题目"
            onClick={() => onSelect({ kind: "new_problem" })}
          />
          <SidebarButton
            active={selection.kind === "search"}
            detail="按标题、标签查找"
            label="搜索"
            onClick={() => onSelect({ kind: "search" })}
          />
        </SidebarSection>

        <SidebarSection title="题目">
          {nav.problems.map((problem) => (
            <SidebarButton
              active={
                selection.kind === "problem" && selection.id === problem.id
              }
              badge={publishStatusLabel(problem.status)}
              detail={problem.tags.join(" · ")}
              key={problem.id}
              label={problem.shortTitle}
              onClick={() => onSelect({ kind: "problem", id: problem.id })}
            />
          ))}
        </SidebarSection>

        <SidebarSection title="网站">
          <SidebarButton
            active={selection.kind === "site_home"}
            badge={publishStatusLabel(nav.siteHome.status)}
            detail={nav.siteHome.siteName}
            label="网站首页"
            onClick={() => onSelect({ kind: "site_home" })}
          />
        </SidebarSection>

        <SidebarSection title="专题">
          {nav.topics.map((topic) => (
            <SidebarButton
              active={selection.kind === "topic" && selection.id === topic.id}
              badge={publishStatusLabel(topic.status)}
              detail={`${topic.items.length} 个题目`}
              key={topic.id}
              label={topic.title}
              onClick={() => onSelect({ kind: "topic", id: topic.id })}
            />
          ))}
        </SidebarSection>
      </nav>
    </aside>
  );
}

function SidebarSection({
  children,
  title,
}: {
  children: ReactNode;
  title: string;
}) {
  return (
    <section>
      <h2 className="px-2 text-xs font-semibold text-zinc-500">{title}</h2>
      <div className="mt-2 space-y-1">{children}</div>
    </section>
  );
}

function SidebarButton({
  active,
  badge,
  detail,
  label,
  onClick,
}: {
  active: boolean;
  badge?: string;
  detail: string;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-current={active ? "page" : undefined}
      className={`w-full rounded-md border px-3 py-2 text-left transition ${
        active
          ? "border-teal-300 bg-teal-50 text-teal-950"
          : "border-transparent text-zinc-700 hover:border-zinc-200 hover:bg-zinc-50"
      }`}
      onClick={onClick}
      type="button"
    >
      <span className="flex items-start justify-between gap-3">
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium">{label}</span>
          <span className="mt-1 block truncate text-xs text-zinc-500">
            {detail}
          </span>
        </span>
        {badge ? (
          <span className="shrink-0 rounded border border-zinc-200 bg-white px-1.5 py-0.5 text-[11px] text-zinc-600">
            {badge}
          </span>
        ) : null}
      </span>
    </button>
  );
}
