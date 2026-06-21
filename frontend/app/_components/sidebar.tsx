"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import type { NavResponse, PublishStatus } from "@/lib/contracts";
import { useCurrentUser } from "@/lib/user/current-user";

import { type WorkspaceSelection } from "./workspace-model";

type HoveredSidebarEntity = {
  description: string;
  id: string;
  kind: "专题" | "题目" | "网站";
  label: string;
  left: number;
  status: PublishStatus;
  timestamp: string;
  top: number;
};

type DeleteSidebarEntity = HoveredSidebarEntity & {
  onDelete: () => void;
};

export function Sidebar({
  collapsed,
  nav,
  onCreateTopic,
  onDeleteProblem,
  onDeleteTopic,
  onOpenSearch,
  onToggleCollapsed,
  selection,
  onSelect,
}: {
  collapsed: boolean;
  nav: NavResponse;
  onCreateTopic: () => void;
  onDeleteProblem: (problemId: string) => void;
  onDeleteTopic: (topicId: string) => void;
  onOpenSearch: () => void;
  onToggleCollapsed: () => void;
  selection: WorkspaceSelection;
  onSelect: (selection: WorkspaceSelection) => void;
}) {
  const [hoveredEntity, setHoveredEntity] =
    useState<HoveredSidebarEntity | null>(null);
  const [deleteEntity, setDeleteEntity] =
    useState<DeleteSidebarEntity | null>(null);

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
        <SidebarSection
          action={
            <IconButton
              label="新建题目"
              onClick={() => onSelect({ kind: "new_problem" })}
            >
              <PlusIcon />
            </IconButton>
          }
          title="题目"
        >
          {nav.problems.map((problem) => (
            <SidebarEntityButton
              active={
                selection.kind === "problem" && selection.id === problem.id
              }
              description={problem.tags.join("、") || "暂无标签"}
              id={problem.id}
              status={problem.status}
              timestamp={problem.updatedAt}
              key={problem.id}
              label={problem.shortTitle}
              kind="题目"
              onDelete={() => onDeleteProblem(problem.id)}
              onDeleteRequest={setDeleteEntity}
              onHoverChange={setHoveredEntity}
              onClick={() => onSelect({ kind: "problem", id: problem.id })}
            />
          ))}
        </SidebarSection>

        <SidebarSection title="网站">
          <SidebarEntityButton
            active={selection.kind === "site_home"}
            description={nav.siteHome.description}
            id={nav.siteHome.id}
            kind="网站"
            status={nav.siteHome.status}
            timestamp={nav.siteHome.autosavedAt}
            label="网站首页"
            onHoverChange={setHoveredEntity}
            onClick={() => onSelect({ kind: "site_home" })}
          />
        </SidebarSection>

        <SidebarSection
          action={
            <IconButton label="新建专题" onClick={onCreateTopic}>
              <PlusIcon />
            </IconButton>
          }
          title="专题"
        >
          {nav.topics.map((topic) => (
            <SidebarEntityButton
              active={selection.kind === "topic" && selection.id === topic.id}
              description={topic.description}
              id={topic.id}
              status={topic.status}
              timestamp={topic.updatedAt}
              key={topic.id}
              label={topic.title}
              kind="专题"
              onDelete={() => onDeleteTopic(topic.id)}
              onDeleteRequest={setDeleteEntity}
              onHoverChange={setHoveredEntity}
              onClick={() => onSelect({ kind: "topic", id: topic.id })}
            />
          ))}
        </SidebarSection>
      </nav>
      <SidebarAccount />
      {hoveredEntity && !deleteEntity ? (
        <SidebarEntityPopover entity={hoveredEntity} />
      ) : null}
      {deleteEntity ? (
        <SidebarDeletePopover
          entity={deleteEntity}
          onCancel={() => setDeleteEntity(null)}
          onConfirm={() => {
            const deleteAction = deleteEntity.onDelete;
            setDeleteEntity(null);
            deleteAction();
          }}
        />
      ) : null}
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

function PlusIcon() {
  return (
    <svg
      aria-hidden="true"
      className="size-4"
      fill="none"
      viewBox="0 0 24 24"
    >
      <path
        d="M12 5v14M5 12h14"
        stroke="currentColor"
        strokeLinecap="round"
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
        {action ? <div className="flex w-16 justify-end">{action}</div> : null}
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
  description,
  id,
  kind,
  label,
  onDelete,
  onDeleteRequest,
  onHoverChange,
  onClick,
  status,
  timestamp,
}: {
  active: boolean;
  description: string;
  id: string;
  kind: "专题" | "题目" | "网站";
  label: string;
  onDelete?: () => void;
  onDeleteRequest?: (entity: DeleteSidebarEntity | null) => void;
  onHoverChange: (entity: HoveredSidebarEntity | null) => void;
  onClick: () => void;
  status: PublishStatus;
  timestamp: string;
}) {
  function getEntityFromElement(
    element: HTMLDivElement,
  ): HoveredSidebarEntity {
    const rect = element.getBoundingClientRect();

    return {
      description,
      id,
      kind,
      label,
      left: rect.right + 8,
      status,
      timestamp,
      top: rect.top,
    };
  }

  function handleMouseEnter(event: React.MouseEvent<HTMLDivElement>) {
    onHoverChange(getEntityFromElement(event.currentTarget));
  }

  function handleDeleteClick(event: React.MouseEvent<HTMLButtonElement>) {
    const rect = event.currentTarget.getBoundingClientRect();

    if (!onDelete || !onDeleteRequest) {
      return;
    }

    onHoverChange(null);
    onDeleteRequest({
      description,
      id,
      kind,
      label,
      left: rect.right + 8,
      onDelete,
      status,
      timestamp,
      top: rect.top,
    });
  }

  return (
    <div
      className="group relative"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={() => onHoverChange(null)}
    >
      <button
        aria-current={active ? "page" : undefined}
        className={`block w-full min-w-0 rounded-md border px-2 py-1.5 text-left transition ${
          active
            ? "border-teal-300 bg-teal-50 text-teal-950"
            : "border-transparent text-zinc-700 hover:border-zinc-200 hover:bg-zinc-50"
        }`}
        onClick={onClick}
        type="button"
      >
        <span className="flex min-w-0 items-center gap-2">
          <PublishStatusIcon status={status} />
          <span
            className="block min-w-0 flex-1 truncate text-sm font-medium"
            title={label}
          >
            {label}
          </span>
          <span className="w-16 shrink-0 text-right text-xs text-zinc-400 group-hover:hidden">
            {relativeTimeLabel(timestamp)}
          </span>
        </span>
      </button>
      <div className="absolute right-1 top-1/2 hidden -translate-y-1/2 items-center gap-1 group-hover:flex">
        {onDelete ? (
          <button
            aria-label={`删除${kind}`}
            className="flex size-6 items-center justify-center rounded text-zinc-500 hover:bg-red-50 hover:text-red-600"
            onClick={(event) => {
              event.stopPropagation();
              handleDeleteClick(event);
            }}
            type="button"
          >
            <TrashIcon />
          </button>
        ) : null}
      </div>
    </div>
  );
}

function TrashIcon() {
  return (
    <svg
      aria-hidden="true"
      className="size-4"
      fill="none"
      viewBox="0 0 24 24"
    >
      <path
        d="M5 7h14M10 11v6M14 11v6M9 7l.7-2h4.6L15 7M7 7l.7 13h8.6L17 7"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function SidebarEntityPopover({ entity }: { entity: HoveredSidebarEntity }) {
  return (
    <div
      className="fixed z-50 w-80 rounded-xl border border-zinc-200 bg-white p-4 shadow-xl"
      style={{
        left: entity.left,
        top: `min(${entity.top}px, calc(100vh - 11rem))`,
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 flex-1 text-sm font-semibold text-zinc-900">
          {entity.label}
        </h3>
        <span className="shrink-0 text-xs text-zinc-400">
          {relativeTimeLabel(entity.timestamp)}
        </span>
      </div>
      <div className="mt-3 flex items-center gap-2 text-xs text-zinc-500">
        <PublishStatusIcon status={entity.status} />
        <span>{publishStatusText(entity.status)}</span>
        <span className="text-zinc-300">·</span>
        <span>{entity.kind}</span>
      </div>
      <p className="mt-3 text-sm leading-6 text-zinc-600">
        {entity.description || `暂无${entity.kind}说明。`}
      </p>
      <p className="mt-3 truncate font-mono text-xs text-zinc-400">
        {entity.id}
      </p>
    </div>
  );
}

function SidebarDeletePopover({
  entity,
  onCancel,
  onConfirm,
}: {
  entity: DeleteSidebarEntity;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      className="fixed z-50 w-72 rounded-xl border border-zinc-200 bg-white p-3 shadow-xl"
      style={{
        left: entity.left,
        top: `min(${entity.top}px, calc(100vh - 9rem))`,
      }}
    >
      <p className="text-sm font-medium text-zinc-900">删除{entity.kind}？</p>
      <p className="mt-1 line-clamp-2 text-xs leading-5 text-zinc-500">
        {entity.label}
      </p>
      <p className="mt-2 text-xs leading-5 text-zinc-500">
        这是 mock 会话内删除，刷新后会恢复 fixture。
      </p>
      <div className="mt-3 flex justify-end gap-2">
        <button
          className="rounded px-2 py-1 text-xs text-zinc-500 hover:bg-zinc-50"
          onClick={onCancel}
          type="button"
        >
          取消
        </button>
        <button
          className="rounded bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700"
          onClick={onConfirm}
          type="button"
        >
          删除
        </button>
      </div>
    </div>
  );
}

function publishStatusText(status: PublishStatus): string {
  if (status === "published") {
    return "已发布";
  }

  if (status === "published_dirty") {
    return "已发布 · 有改动";
  }

  return "草稿";
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
