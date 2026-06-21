"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";

import {
  createProblemAnnotation,
  getProblemAnnotations,
  getProblemMessages,
} from "@/lib/api/client";
import type {
  CreateWebAnnotationRequest,
  NavResponse,
  Problem,
  ProblemMessage,
  UploadJobProgressEvent,
  WebAnnotation,
} from "@/lib/contracts";
import { deriveProblemShortTitle } from "@/lib/problems/short-title";

import { MainPane } from "./main-pane";
import { PreviewPane } from "./preview-pane";
import { Sidebar } from "./sidebar";
import {
  getInitialSelection,
  insertProblem,
  resolveSelection,
  type AutosaveState,
  type SelectedWorkspaceObject,
  type WorkspaceSelection,
} from "./workspace-model";

const WORKSPACE_DESIGN_WIDTH = 1060;
const SIDEBAR_COLLAPSED_WIDTH = 48;
const SIDEBAR_DEFAULT_WIDTH = 280;
const SIDEBAR_MIN_WIDTH = 220;
const SIDEBAR_MAX_WIDTH = 420;
const PREVIEW_COLLAPSED_WIDTH = 48;
const PREVIEW_DEFAULT_WIDTH = 420;
const PREVIEW_MIN_WIDTH = 360;
const PREVIEW_MAX_WIDTH = 760;
const MAIN_MIN_WIDTH = 360;

export function AuthoringWorkspace({ initialNav }: { initialNav: NavResponse }) {
  const [nav, setNav] = useState<NavResponse>(initialNav);
  const [selection, setSelection] = useState<WorkspaceSelection>(() =>
    getInitialSelection(initialNav),
  );
  const [autosaveState, setAutosaveState] = useState<AutosaveState>("saved");
  const [autosaveError, setAutosaveError] = useState<string | null>(null);
  const [, setUploadEvents] = useState<UploadJobProgressEvent[]>([]);
  const [, setUploadError] = useState<string | null>(null);
  const [problemConversations, setProblemConversations] = useState<
    Record<string, ProblemMessage[]>
  >({});
  const [problemAnnotations, setProblemAnnotations] = useState<
    Record<string, WebAnnotation[]>
  >({});
  const [pendingAnnotationIds, setPendingAnnotationIds] = useState<
    Record<string, string[]>
  >({});
  const loadedProblemMessageIdsRef = useRef<Set<string>>(new Set());
  const loadedProblemAnnotationIdsRef = useRef<Set<string>>(new Set());
  const [workspaceScale, setWorkspaceScale] = useState(1);
  const [workspaceViewportWidth, setWorkspaceViewportWidth] = useState(
    WORKSPACE_DESIGN_WIDTH,
  );
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT_WIDTH);
  const [previewWidth, setPreviewWidth] = useState(PREVIEW_DEFAULT_WIDTH);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isPreviewCollapsed, setIsPreviewCollapsed] = useState(false);
  const [isSearchOpen, setIsSearchOpen] = useState(false);

  const selectedObject = useMemo<SelectedWorkspaceObject>(
    () => resolveSelection(nav, selection),
    [nav, selection],
  );
  const selectedObjectHasPreview =
    selectedObject.kind === "problem" ||
    selectedObject.kind === "site_home" ||
    selectedObject.kind === "topic";

  useEffect(() => {
    function updateWorkspaceScale() {
      const viewportWidth = Math.max(window.innerWidth, 1);
      setWorkspaceViewportWidth(viewportWidth);
      setWorkspaceScale(
        Math.min(1, viewportWidth / WORKSPACE_DESIGN_WIDTH),
      );
    }

    updateWorkspaceScale();
    window.addEventListener("resize", updateWorkspaceScale);

    const visualViewport = window.visualViewport;
    visualViewport?.addEventListener("resize", updateWorkspaceScale);

    return () => {
      window.removeEventListener("resize", updateWorkspaceScale);
      visualViewport?.removeEventListener("resize", updateWorkspaceScale);
    };
  }, []);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setIsSearchOpen(true);
      }
    }

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  useEffect(() => {
    if (selectedObject.kind !== "problem") {
      return;
    }

    const problemId = selectedObject.item.id;

    if (
      loadedProblemMessageIdsRef.current.has(problemId) ||
      problemConversations[problemId]
    ) {
      return;
    }

    let isActive = true;
    loadedProblemMessageIdsRef.current.add(problemId);

    getProblemMessages(problemId)
      .then(({ messages }) => {
        if (!isActive) {
          return;
        }

        setProblemConversations((currentConversations) => {
          if (currentConversations[problemId]) {
            return currentConversations;
          }

          return {
            ...currentConversations,
            [problemId]: messages,
          };
        });
      })
      .catch(() => {
        loadedProblemMessageIdsRef.current.delete(problemId);
      });

    return () => {
      isActive = false;
    };
  }, [problemConversations, selectedObject]);

  useEffect(() => {
    if (selectedObject.kind !== "problem") {
      return;
    }

    const problemId = selectedObject.item.id;

    if (
      loadedProblemAnnotationIdsRef.current.has(problemId) ||
      problemAnnotations[problemId]
    ) {
      return;
    }

    let isActive = true;
    loadedProblemAnnotationIdsRef.current.add(problemId);

    getProblemAnnotations(problemId)
      .then(({ annotations }) => {
        if (!isActive) {
          return;
        }

        setProblemAnnotations((currentAnnotations) => {
          if (currentAnnotations[problemId]) {
            return currentAnnotations;
          }

          return {
            ...currentAnnotations,
            [problemId]: annotations,
          };
        });
      })
      .catch(() => {
        loadedProblemAnnotationIdsRef.current.delete(problemId);
      });

    return () => {
      isActive = false;
    };
  }, [problemAnnotations, selectedObject]);

  function handleProblemCreated(
    problem: Problem,
    messages: ProblemMessage[],
  ) {
    setNav((currentNav) => insertProblem(currentNav, problem));
    setProblemConversations((currentConversations) => ({
      ...currentConversations,
      [problem.id]: messages,
    }));
    setProblemAnnotations((currentAnnotations) => ({
      ...currentAnnotations,
      [problem.id]: [],
    }));
    setPendingAnnotationIds((currentPendingIds) => ({
      ...currentPendingIds,
      [problem.id]: [],
    }));
    loadedProblemMessageIdsRef.current.add(problem.id);
    loadedProblemAnnotationIdsRef.current.add(problem.id);
    setSelection({ kind: "problem", id: problem.id });
    setAutosaveError(null);
  }

  function handleProblemConversationChange(
    problemId: string,
    messages: ProblemMessage[],
  ) {
    setProblemConversations((currentConversations) => ({
      ...currentConversations,
      [problemId]: messages,
    }));
  }

  function handleProblemDraftChange(
    problemId: string,
    patch: { title?: string; tags?: string[] },
  ) {
    setNav((currentNav) => ({
      ...currentNav,
      problems: currentNav.problems.map((problem) => {
        if (problem.id !== problemId) {
          return problem;
        }

        const title = patch.title ?? problem.title;

        return {
          ...problem,
          shortTitle:
            patch.title === undefined
              ? problem.shortTitle
              : deriveProblemShortTitle(title),
          tags: patch.tags ?? problem.tags,
          title,
        };
      }),
    }));
  }

  function handleProblemPatched(problem: Problem) {
    updateProblemInNav(problem);
  }

  function handleProblemEdited(problem: Problem) {
    updateProblemInNav(problem);
  }

  async function handleProblemAnnotationCreate(
    problemId: string,
    request: CreateWebAnnotationRequest,
  ) {
    const { annotation } = await createProblemAnnotation(problemId, request);

    setProblemAnnotations((currentAnnotations) => ({
      ...currentAnnotations,
      [problemId]: [...(currentAnnotations[problemId] ?? []), annotation],
    }));
    setPendingAnnotationIds((currentPendingIds) => ({
      ...currentPendingIds,
      [problemId]: [
        ...(currentPendingIds[problemId] ?? []).filter(
          (annotationId) => annotationId !== annotation.id,
        ),
        annotation.id,
      ],
    }));

    return annotation;
  }

  function handlePendingAnnotationRemove(
    problemId: string,
    annotationId: string,
  ) {
    setPendingAnnotationIds((currentPendingIds) => ({
      ...currentPendingIds,
      [problemId]: (currentPendingIds[problemId] ?? []).filter(
        (currentAnnotationId) => currentAnnotationId !== annotationId,
      ),
    }));
  }

  function handlePendingAnnotationsCommitted(problemId: string) {
    setPendingAnnotationIds((currentPendingIds) => ({
      ...currentPendingIds,
      [problemId]: [],
    }));
  }

  function updateProblemInNav(problem: Problem) {
    setNav((currentNav) => ({
      ...currentNav,
      problems: currentNav.problems.map((item) =>
        item.id === problem.id ? problem : item,
      ),
    }));
  }

  function handleResizePointerDown(
    side: "left" | "right",
    event: ReactPointerEvent<HTMLButtonElement>,
  ) {
    event.preventDefault();
    const pointerStartX = event.clientX;
    const sidebarStartWidth = sidebarWidth;
    const previewStartWidth = previewWidth;
    const logicalWorkspaceWidth =
      workspaceScale < 1 ? WORKSPACE_DESIGN_WIDTH : workspaceViewportWidth;
    const leftWidth = isSidebarCollapsed
      ? SIDEBAR_COLLAPSED_WIDTH
      : sidebarWidth;
    const rightWidth =
      selectedObjectHasPreview && !isPreviewCollapsed
        ? previewWidth
        : selectedObjectHasPreview
          ? PREVIEW_COLLAPSED_WIDTH
          : 0;

    function handlePointerMove(moveEvent: PointerEvent) {
      const delta = (moveEvent.clientX - pointerStartX) / workspaceScale;

      if (side === "left") {
        const maxAllowedWidth = Math.min(
          SIDEBAR_MAX_WIDTH,
          logicalWorkspaceWidth - rightWidth - MAIN_MIN_WIDTH,
        );
        setSidebarWidth(
          clamp(
            sidebarStartWidth + delta,
            SIDEBAR_MIN_WIDTH,
            Math.max(SIDEBAR_MIN_WIDTH, maxAllowedWidth),
          ),
        );
        return;
      }

      const maxAllowedWidth = Math.min(
        PREVIEW_MAX_WIDTH,
        logicalWorkspaceWidth - leftWidth - MAIN_MIN_WIDTH,
      );
      setPreviewWidth(
        clamp(
          previewStartWidth - delta,
          PREVIEW_MIN_WIDTH,
          Math.max(PREVIEW_MIN_WIDTH, maxAllowedWidth),
        ),
      );
    }

    function handlePointerUp() {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    }

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
  }

  const shouldScaleWorkspace = workspaceScale < 1;
  const workspaceStyle: CSSProperties = shouldScaleWorkspace
    ? {
        height: `${100 / workspaceScale}%`,
        left: 0,
        position: "absolute",
        top: 0,
        transform: `scale(${workspaceScale})`,
        transformOrigin: "top left",
        width: `${WORKSPACE_DESIGN_WIDTH}px`,
      }
    : {
        height: "100%",
        left: 0,
        position: "absolute",
        top: 0,
        width: "100%",
      };
  const gridTemplateColumns = `${
    isSidebarCollapsed ? `${SIDEBAR_COLLAPSED_WIDTH}px` : `${sidebarWidth}px`
  } minmax(360px, 1fr) ${
    selectedObjectHasPreview
      ? isPreviewCollapsed
        ? `${PREVIEW_COLLAPSED_WIDTH}px`
        : `${previewWidth}px`
      : "0px"
  }`;
  const selectedProblemAnnotations =
    selectedObject.kind === "problem"
      ? (problemAnnotations[selectedObject.item.id] ?? [])
      : [];
  const selectedPendingAnnotationIds =
    selectedObject.kind === "problem"
      ? (pendingAnnotationIds[selectedObject.item.id] ?? [])
      : [];
  const selectedPendingAnnotations = selectedPendingAnnotationIds.flatMap(
    (annotationId) => {
      const annotation = selectedProblemAnnotations.find(
        (item) => item.id === annotationId,
      );

      return annotation ? [annotation] : [];
    },
  );

  return (
    <main className="relative h-full overflow-hidden bg-zinc-100 text-zinc-950">
      <div
        className="grid h-full"
        style={{ ...workspaceStyle, gridTemplateColumns }}
      >
        <div className="relative min-w-0">
          <Sidebar
            collapsed={isSidebarCollapsed}
            nav={nav}
            selection={selection}
            onOpenSearch={() => setIsSearchOpen(true)}
            onToggleCollapsed={() =>
              setIsSidebarCollapsed((current) => !current)
            }
            onSelect={setSelection}
          />
          {!isSidebarCollapsed ? (
            <ResizeHandle
              label="调整左侧栏宽度"
              side="right"
              onPointerDown={(event) =>
                handleResizePointerDown("left", event)
              }
            />
          ) : null}
        </div>
        <MainPane
          autosaveState={autosaveState}
          autosaveError={autosaveError}
          problemConversation={
            selectedObject.kind === "problem"
              ? (problemConversations[selectedObject.item.id] ?? [])
              : []
          }
          problemAnnotations={
            selectedProblemAnnotations
          }
          pendingAnnotationIds={selectedPendingAnnotationIds}
          selectedObject={selectedObject}
          onProblemCreated={handleProblemCreated}
          onProblemEdited={handleProblemEdited}
          onProblemDraftChange={handleProblemDraftChange}
          onProblemPatched={handleProblemPatched}
          onProblemConversationChange={handleProblemConversationChange}
          onPendingAnnotationRemove={handlePendingAnnotationRemove}
          onPendingAnnotationsCommitted={handlePendingAnnotationsCommitted}
          onAutosaveErrorChange={setAutosaveError}
          onAutosaveStateChange={setAutosaveState}
          onUploadErrorChange={setUploadError}
          onUploadEventsChange={setUploadEvents}
        />
        {selectedObjectHasPreview ? (
          <div className="relative min-w-0">
            {!isPreviewCollapsed ? (
              <ResizeHandle
                label="调整右侧栏宽度"
                side="left"
                onPointerDown={(event) =>
                  handleResizePointerDown("right", event)
                }
              />
            ) : null}
            <PreviewPane
              annotations={selectedPendingAnnotations}
              collapsed={isPreviewCollapsed}
              selectedObject={selectedObject}
              onCreateAnnotation={handleProblemAnnotationCreate}
              onToggleCollapsed={() =>
                setIsPreviewCollapsed((current) => !current)
              }
            />
          </div>
        ) : null}
      </div>
      {isSearchOpen ? (
        <SearchDialog
          nav={nav}
          onClose={() => setIsSearchOpen(false)}
          onSelect={(nextSelection) => {
            setSelection(nextSelection);
            setIsSearchOpen(false);
          }}
        />
      ) : null}
    </main>
  );
}

function ResizeHandle({
  label,
  onPointerDown,
  side,
}: {
  label: string;
  onPointerDown: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  side: "left" | "right";
}) {
  return (
    <button
      aria-label={label}
      className={`absolute top-0 z-20 h-full w-2 cursor-col-resize transition hover:bg-teal-400/20 ${
        side === "left" ? "-left-1" : "-right-1"
      }`}
      onPointerDown={onPointerDown}
      type="button"
    >
      <span className="sr-only">{label}</span>
    </button>
  );
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

type SearchResult = {
  badge?: string;
  detail: string;
  id: string;
  label: string;
  selection: WorkspaceSelection;
};

function SearchDialog({
  nav,
  onClose,
  onSelect,
}: {
  nav: NavResponse;
  onClose: () => void;
  onSelect: (selection: WorkspaceSelection) => void;
}) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const results = useMemo(() => {
    const normalizedQuery = normalizeSearchText(query);
    const allResults: SearchResult[] = [
      ...nav.problems.map((problem) => ({
        badge: problem.subject,
        detail: problem.tags.join(" · ") || "暂无标签",
        id: `problem-${problem.id}`,
        label: problem.shortTitle,
        selection: { kind: "problem", id: problem.id } as const,
      })),
      {
        badge: "网站",
        detail: nav.siteHome.siteName,
        id: "site-home",
        label: "网站首页",
        selection: { kind: "site_home" } as const,
      },
      ...nav.topics.map((topic) => ({
        badge: "专题",
        detail: `${topic.items.length} 个题目`,
        id: `topic-${topic.id}`,
        label: topic.title,
        selection: { kind: "topic", id: topic.id } as const,
      })),
    ];

    if (!normalizedQuery) {
      return allResults.slice(0, 8);
    }

    return allResults
      .filter((result) =>
        normalizeSearchText(
          `${result.label} ${result.detail} ${result.badge ?? ""}`,
        ).includes(normalizedQuery),
      )
      .slice(0, 12);
  }, [nav, query]);

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

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-zinc-950/15 px-4 pt-[12vh]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
      role="presentation"
    >
      <div
        aria-label="搜索对象"
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
                onSelect(results[0].selection);
              }
            }}
            placeholder="搜索题目、网站、专题"
            ref={inputRef}
            value={query}
          />
        </div>
        <div className="max-h-[56vh] overflow-y-auto p-2">
          {results.length ? (
            results.map((result) => (
              <button
                className="flex w-full items-center justify-between gap-4 rounded-lg px-3 py-2.5 text-left transition hover:bg-zinc-50"
                key={result.id}
                onClick={() => onSelect(result.selection)}
                type="button"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-zinc-900">
                    {result.label}
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-zinc-500">
                    {result.detail}
                  </span>
                </span>
                {result.badge ? (
                  <span className="shrink-0 rounded border border-zinc-200 px-1.5 py-0.5 text-[11px] text-zinc-500">
                    {result.badge}
                  </span>
                ) : null}
              </button>
            ))
          ) : (
            <div className="px-3 py-8 text-center text-sm text-zinc-500">
              没有找到匹配对象
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function normalizeSearchText(value: string): string {
  return value.trim().toLowerCase();
}
