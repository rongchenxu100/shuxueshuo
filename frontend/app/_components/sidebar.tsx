"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import type { NavResponse, PublishStatus } from "@/lib/contracts";
import { useCurrentUser } from "@/lib/user/current-user";

import { type WorkspaceSelection } from "./workspace-model";

export function Sidebar({
  collapsed,
  nav,
  onOpenSearch,
  onToggleCollapsed,
  selection,
  onSelect,
}: {
  collapsed: boolean;
  nav: NavResponse;
  onOpenSearch: () => void;
  onToggleCollapsed: () => void;
  selection: WorkspaceSelection;
  onSelect: (selection: WorkspaceSelection) => void;
}) {
  if (collapsed) {
    return (
      <aside className="flex h-full min-w-0 flex-col items-center border-r border-zinc-200 bg-white">
        <div className="flex h-12 w-full shrink-0 items-center justify-center border-b border-zinc-200">
          <IconButton label="展开左侧栏" onClick={onToggleCollapsed}>
            <ChevronIcon direction="right" />
          </IconButton>
        </div>
        <div className="min-h-0 flex-1" />
        <SidebarAccount compact />
      </aside>
    );
  }

  return (
    <aside className="flex h-full min-w-0 flex-col border-r border-zinc-200 bg-white">
      <nav className="shrink-0 border-b border-zinc-200 px-3 py-4">
        <SidebarSection
          action={
            <IconButton label="收起左侧栏" onClick={onToggleCollapsed}>
              <ChevronIcon direction="left" />
            </IconButton>
          }
          title="入口"
        >
          <SidebarButton
            active={selection.kind === "new_problem"}
            label="新题目"
            onClick={() => onSelect({ kind: "new_problem" })}
          />
          <SidebarButton
            active={false}
            label="搜索"
            onClick={onOpenSearch}
          />
        </SidebarSection>
      </nav>

      <nav className="min-h-0 flex-1 space-y-6 overflow-y-auto px-3 py-4">
        <SidebarSection title="题目">
          {nav.problems.map((problem) => (
            <SidebarEntityButton
              active={
                selection.kind === "problem" && selection.id === problem.id
              }
              status={problem.status}
              timestamp={problem.updatedAt}
              key={problem.id}
              label={problem.shortTitle}
              onClick={() => onSelect({ kind: "problem", id: problem.id })}
            />
          ))}
        </SidebarSection>

        <SidebarSection title="网站">
          <SidebarEntityButton
            active={selection.kind === "site_home"}
            status={nav.siteHome.status}
            timestamp={nav.siteHome.autosavedAt}
            label="网站首页"
            onClick={() => onSelect({ kind: "site_home" })}
          />
        </SidebarSection>

        <SidebarSection title="专题">
          {nav.topics.map((topic) => (
            <SidebarEntityButton
              active={selection.kind === "topic" && selection.id === topic.id}
              status={topic.status}
              timestamp={topic.updatedAt}
              key={topic.id}
              label={topic.title}
              onClick={() => onSelect({ kind: "topic", id: topic.id })}
            />
          ))}
        </SidebarSection>
      </nav>
      <SidebarAccount />
    </aside>
  );
}

function IconButton({
  children,
  label,
  onClick,
}: {
  children: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-label={label}
      className="flex size-8 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900"
      onClick={onClick}
      title={label}
      type="button"
    >
      {children}
    </button>
  );
}

function ChevronIcon({ direction }: { direction: "left" | "right" }) {
  return (
    <svg
      aria-hidden="true"
      className="size-4"
      fill="none"
      viewBox="0 0 24 24"
    >
      <path
        d={direction === "left" ? "M15 6l-6 6 6 6" : "M9 6l6 6-6 6"}
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
      />
    </svg>
  );
}

function SidebarSection({
  action,
  children,
  title,
}: {
  action?: ReactNode;
  children: ReactNode;
  title: string;
}) {
  return (
    <section>
      <div className="flex min-h-8 items-center justify-between gap-2 px-2">
        <h2 className="text-xs font-semibold text-zinc-500">{title}</h2>
        {action}
      </div>
      <div className="mt-2 space-y-1">{children}</div>
    </section>
  );
}

function SidebarAccount({ compact = false }: { compact?: boolean }) {
  const currentUser = useCurrentUser();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

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

  return (
    <div
      className={`relative shrink-0 border-t border-zinc-200 ${
        compact ? "w-full p-2" : "p-3"
      }`}
      ref={containerRef}
    >
      {isOpen ? (
        <div
          className={`absolute bottom-16 rounded-lg border border-zinc-200 bg-white p-2 shadow-xl ${
            compact ? "left-2 w-64" : "inset-x-3"
          }`}
          id="sidebar-settings-menu"
          role="menu"
        >
          <button
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-zinc-800 transition hover:bg-zinc-50"
            role="menuitem"
            type="button"
          >
            <UserIcon />
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium">
                个人账户
              </span>
              <span className="mt-0.5 block truncate text-xs text-zinc-500">
                {currentUser.email}
              </span>
            </span>
          </button>
          <button
            className="mt-1 flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-zinc-800 transition hover:bg-zinc-50"
            role="menuitem"
            type="button"
          >
            <LogOutIcon />
            <span className="text-sm font-medium">退出登录</span>
          </button>
        </div>
      ) : null}
      <button
        aria-controls="sidebar-settings-menu"
        aria-expanded={isOpen}
        aria-label={compact ? "设置" : undefined}
        className={`flex w-full items-center ${
          compact ? "justify-center px-0" : "gap-3 px-3"
        } rounded-md py-2 text-left text-zinc-700 transition ${
          isOpen ? "bg-zinc-100" : "hover:bg-zinc-50"
        }`}
        onClick={() => setIsOpen((current) => !current)}
        title={compact ? "设置" : undefined}
        type="button"
      >
        <SettingsIcon />
        {compact ? null : <span className="text-sm font-medium">设置</span>}
      </button>
    </div>
  );
}

function LogOutIcon() {
  return (
    <svg
      aria-hidden="true"
      className="size-5 shrink-0 text-zinc-500"
      fill="none"
      viewBox="0 0 24 24"
    >
      <path
        d="M9 6H6.5A2.5 2.5 0 0 0 4 8.5v7A2.5 2.5 0 0 0 6.5 18H9"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.8"
      />
      <path
        d="M14 8l4 4-4 4M18 12H9"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function UserIcon() {
  return (
    <svg
      aria-hidden="true"
      className="size-5 shrink-0 text-zinc-500"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle cx="12" cy="8" r="3.5" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M5.5 19c1.2-3 3.4-4.5 6.5-4.5s5.3 1.5 6.5 4.5"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.8"
      />
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg
      aria-hidden="true"
      className="size-5 shrink-0 text-zinc-500"
      fill="none"
      viewBox="0 0 24 24"
    >
      <path
        d="M9.3 4.3 10 2.5h4l.7 1.8 2 .8 1.8-.8 2 3.4-1.5 1.2.2 1.1-.2 1.1 1.5 1.2-2 3.4-1.8-.8-2 .8L14 21.5h-4l-.7-1.8-2-.8-1.8.8-2-3.4L5 15.1 4.8 14l.2-1.1-1.5-1.2 2-3.4 1.8.8 2-.8Z"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth="1.6"
      />
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function SidebarButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
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
      <span className="block truncate text-sm font-medium">{label}</span>
    </button>
  );
}

function SidebarEntityButton({
  active,
  label,
  onClick,
  status,
  timestamp,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
  status: PublishStatus;
  timestamp: string;
}) {
  return (
    <button
      aria-current={active ? "page" : undefined}
      className={`w-full rounded-md border px-2 py-1.5 text-left transition ${
        active
          ? "border-teal-300 bg-teal-50 text-teal-950"
          : "border-transparent text-zinc-700 hover:border-zinc-200 hover:bg-zinc-50"
      }`}
      onClick={onClick}
      type="button"
    >
      <span className="flex items-center gap-2">
        <PublishStatusIcon status={status} />
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          {label}
        </span>
        <span className="shrink-0 text-xs text-zinc-400">
          {relativeTimeLabel(timestamp)}
        </span>
      </span>
    </button>
  );
}

function PublishStatusIcon({ status }: { status: PublishStatus }) {
  if (status === "published") {
    return (
      <span
        aria-label="已发布"
        className="flex size-4 shrink-0 items-center justify-center text-emerald-600"
        title="已发布"
      >
        <GlobeIcon />
      </span>
    );
  }

  if (status === "published_dirty") {
    return (
      <span
        aria-label="已发布，有改动"
        className="relative flex size-4 shrink-0 items-center justify-center text-emerald-600"
        title="已发布 · 有改动"
      >
        <GlobeIcon />
        <span className="absolute -right-0.5 -top-0.5 size-2 rounded-full border border-white bg-amber-500" />
      </span>
    );
  }

  return (
    <span
      aria-label="草稿"
      className="flex size-4 shrink-0 items-center justify-center text-zinc-400"
      title="草稿"
    >
      <FilePenIcon />
    </span>
  );
}

function GlobeIcon() {
  return (
    <svg
      aria-hidden="true"
      className="size-4"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle cx="12" cy="12" r="8.5" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M3.8 12h16.4M12 3.5c2.2 2.2 3.3 5 3.3 8.5s-1.1 6.3-3.3 8.5c-2.2-2.2-3.3-5-3.3-8.5S9.8 5.7 12 3.5Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function FilePenIcon() {
  return (
    <svg
      aria-hidden="true"
      className="size-4"
      fill="none"
      viewBox="0 0 24 24"
    >
      <path
        d="M6.5 4.5h6l4 4v4.2"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
      <path
        d="M13 4.5v4h4M6.5 4.5A1.5 1.5 0 0 0 5 6v12a1.5 1.5 0 0 0 1.5 1.5h5"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
      <path
        d="m14 18.8 4.2-4.2a1.4 1.4 0 0 1 2 2L16 20.8l-2.8.7.8-2.7Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function relativeTimeLabel(timestamp: string): string {
  const then = new Date(timestamp).getTime();

  if (!Number.isFinite(then)) {
    return "";
  }

  const diffMs = Math.max(Date.now() - then, 0);
  const diffMinutes = Math.floor(diffMs / 60_000);

  if (diffMinutes < 1) {
    return "刚刚";
  }

  if (diffMinutes < 60) {
    return `${diffMinutes}分钟前`;
  }

  const diffHours = Math.floor(diffMinutes / 60);

  if (diffHours < 24) {
    return `${diffHours}小时前`;
  }

  const diffWeeks = Math.max(1, Math.floor(diffHours / (24 * 7)));

  if (diffWeeks < 5) {
    return `${diffWeeks}周前`;
  }

  return `${Math.max(1, Math.floor(diffWeeks / 4))}月前`;
}
