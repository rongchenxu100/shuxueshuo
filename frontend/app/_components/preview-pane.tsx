import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type {
  CreateWebAnnotationRequest,
  TutorAction,
  WebAnnotation,
} from "@/lib/contracts";

import { AnnotationOverlay } from "./annotation-overlay";
import {
  previewUrlWithVersion,
  type SelectedWorkspaceObject,
} from "./workspace-model";
import {
  canAcceptPreviewMessage,
  getAnnotationMarkerPositions,
  getPreviewOrigin,
  isPreviewBridgeMessage,
  type PreviewTargetRect,
  type PreviewTargetSelectedMessage,
} from "./preview-bridge";
import {
  AnnotationIcon,
  ArrowUpIcon,
  ChevronIcon,
  ExternalLinkIcon,
  MicIcon,
  RefreshIcon,
  SlidersIcon,
} from "./ui/icons";

export function PreviewPane({
  annotations,
  collapsed,
  mode,
  onCreateAnnotation,
  onTutorQuestionSubmit,
  onToggleCollapsed,
  selectedObject,
  tutorActionBatch,
}: {
  annotations: WebAnnotation[];
  collapsed: boolean;
  mode: "edit" | "tutor";
  onCreateAnnotation: (
    problemId: string,
    request: CreateWebAnnotationRequest,
  ) => Promise<WebAnnotation>;
  onTutorQuestionSubmit?: (
    target: PreviewTargetSelectedMessage,
    content: string,
  ) => void;
  onToggleCollapsed: () => void;
  selectedObject: SelectedWorkspaceObject;
  tutorActionBatch?: { actions: TutorAction[]; id: number } | null;
}) {
  const preview = getPreview(selectedObject);
  const [reloadNonce, setReloadNonce] = useState(0);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [annotationMode, setAnnotationMode] = useState(false);
  const [targetRects, setTargetRects] = useState<PreviewTargetRect[]>([]);
  const [selectedTarget, setSelectedTarget] =
    useState<PreviewTargetSelectedMessage | null>(null);
  const [selectedMarker, setSelectedMarker] = useState<WebAnnotation | null>(
    null,
  );
  const [comment, setComment] = useState("");
  const [tutorTarget, setTutorTarget] =
    useState<PreviewTargetSelectedMessage | null>(null);
  const [tutorPrompt, setTutorPrompt] = useState("");
  const [isCreatingAnnotation, setIsCreatingAnnotation] = useState(false);
  const [annotationError, setAnnotationError] = useState<string | null>(null);
  const problemId =
    selectedObject.kind === "problem" ? selectedObject.item.id : null;
  const canAnnotate = Boolean(preview && problemId && mode === "edit");
  const canSelectTutorTarget = Boolean(
    preview && problemId && mode === "tutor" && onTutorQuestionSubmit,
  );
  const previewOrigin = useMemo(() => {
    if (!preview || typeof window === "undefined") {
      return "";
    }

    return getPreviewOrigin(preview.src, window.location.origin);
  }, [preview]);
  const markerPositions = useMemo(
    () => getAnnotationMarkerPositions(annotations, targetRects),
    [annotations, targetRects],
  );

  const postToPreview = useCallback((message: unknown) => {
    const targetWindow = iframeRef.current?.contentWindow;

    if (!targetWindow || !previewOrigin) {
      return;
    }

    targetWindow.postMessage(message, previewOrigin);
  }, [previewOrigin]);

  const requestTargetRects = useCallback((extraTargetId?: string) => {
    const targetIds = Array.from(
      new Set([
        ...annotations.map((annotation) => annotation.targetId),
        ...(extraTargetId ? [extraTargetId] : []),
      ]),
    );

    postToPreview({
      targetIds,
      type: "preview-request-target-rects",
    });
  }, [annotations, postToPreview]);

  useEffect(() => {
    const frameId = window.requestAnimationFrame(() => {
      setAnnotationMode(false);
      setSelectedTarget(null);
      setSelectedMarker(null);
      setComment("");
      setTutorTarget(null);
      setTutorPrompt("");
      setTargetRects([]);
      setAnnotationError(null);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [preview?.src]);

  useEffect(() => {
    if (mode === "tutor") {
      const frameId = window.requestAnimationFrame(() => {
        setAnnotationMode(false);
        setSelectedTarget(null);
        setSelectedMarker(null);
        setComment("");
        setTutorTarget(null);
        setTutorPrompt("");
        setAnnotationError(null);
      });

      return () => {
        window.cancelAnimationFrame(frameId);
      };
    }
  }, [mode]);

  useEffect(() => {
    if ((!canAnnotate && !canSelectTutorTarget) || !previewOrigin) {
      return;
    }

    function handleMessage(event: MessageEvent) {
      const iframeWindow = iframeRef.current?.contentWindow ?? null;

      if (
        !canAcceptPreviewMessage({
          eventOrigin: event.origin,
          eventSource: event.source,
          expectedOrigin: previewOrigin,
          iframeWindow,
        }) ||
        !isPreviewBridgeMessage(event.data)
      ) {
        return;
      }

      if (
        event.data.type === "preview-ready" ||
        event.data.type === "preview-layout-changed"
      ) {
        requestTargetRects();
        return;
      }

      if (event.data.type === "preview-target-rects") {
        setTargetRects(event.data.rects);
        return;
      }

      if (event.data.type === "preview-target-selected") {
        if (mode === "edit" && annotationMode) {
          setSelectedMarker(null);
          setSelectedTarget(event.data);
          setComment("");
          setAnnotationError(null);
          requestTargetRects(event.data.targetId);
          return;
        }

        if (mode === "tutor") {
          setTutorTarget(event.data);
          setTutorPrompt("");
          requestTargetRects(event.data.targetId);
        }
      }
    }

    window.addEventListener("message", handleMessage);

    return () => {
      window.removeEventListener("message", handleMessage);
    };
  }, [
    annotationMode,
    canAnnotate,
    canSelectTutorTarget,
    mode,
    previewOrigin,
    requestTargetRects,
  ]);

  useEffect(() => {
    postToPreview({
      enabled: annotationMode && canAnnotate,
      type: "preview-set-annotation-mode",
    });
  }, [annotationMode, canAnnotate, postToPreview, preview?.src]);

  useEffect(() => {
    postToPreview({
      enabled: canSelectTutorTarget,
      type: "preview-set-tutor-target-mode",
    });
  }, [canSelectTutorTarget, postToPreview, preview?.src]);

  useEffect(() => {
    if (!tutorActionBatch) {
      return;
    }

    tutorActionBatch.actions.forEach((action) => {
      if (action.type === "scroll_to_step") {
        postToPreview({
          stepId: action.stepId,
          type: "preview-scroll-to-step",
        });
      }

      if (action.type === "highlight_target") {
        postToPreview({
          targetId: action.targetId,
          type: "preview-highlight-target",
        });
      }
    });
  }, [postToPreview, tutorActionBatch]);

  useEffect(() => {
    if (canAnnotate || canSelectTutorTarget) {
      requestTargetRects();
    }
  }, [canAnnotate, canSelectTutorTarget, preview?.src, requestTargetRects]);

  async function handleCreateAnnotation() {
    if (!problemId || !selectedTarget || !comment.trim()) {
      return;
    }

    setIsCreatingAnnotation(true);
    setAnnotationError(null);

    try {
      await onCreateAnnotation(problemId, {
        comment: comment.trim(),
        label: selectedTarget.label,
        screenshotUrl: undefined,
        stepId: selectedTarget.stepId,
        targetId: selectedTarget.targetId,
        targetType: selectedTarget.targetType,
      });
      setSelectedTarget(null);
      setComment("");
      requestTargetRects(selectedTarget.targetId);
    } catch (error) {
      setAnnotationError(
        error instanceof Error ? error.message : "创建注释失败，请重试。",
      );
    } finally {
      setIsCreatingAnnotation(false);
    }
  }

  function handleToggleAnnotationMode() {
    const nextAnnotationMode = !annotationMode;

    setAnnotationMode(nextAnnotationMode);

    if (!nextAnnotationMode) {
      setSelectedTarget(null);
      setSelectedMarker(null);
      setComment("");
      setAnnotationError(null);
    }
  }

  function handleTutorPromptSubmit() {
    if (!tutorTarget || !tutorPrompt.trim()) {
      return;
    }

    onTutorQuestionSubmit?.(tutorTarget, tutorPrompt.trim());
    setTutorTarget(null);
    setTutorPrompt("");
  }

  if (collapsed) {
    return (
      <section className="flex h-full min-w-0 flex-col items-center border-l border-zinc-200 bg-white">
        <div className="flex h-12 w-full shrink-0 items-center justify-center border-b border-zinc-200">
          <IconButton label="展开右侧预览" onClick={onToggleCollapsed}>
            <ChevronIcon direction="left" />
          </IconButton>
        </div>
      </section>
    );
  }

  return (
    <section className="flex h-full min-w-0 flex-col bg-white">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-zinc-200 bg-white px-2">
        <IconButton label="收起右侧预览" onClick={onToggleCollapsed}>
          <ChevronIcon direction="right" />
        </IconButton>
        <span className="text-sm font-medium text-zinc-700">预览</span>
        <div className="ml-auto flex items-center gap-1">
          <IconButton
            disabled={!preview}
            label="刷新预览"
            onClick={() => setReloadNonce((current) => current + 1)}
          >
            <RefreshIcon />
          </IconButton>
          {preview ? (
            <a
              aria-label="打开预览"
              className="flex size-8 shrink-0 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900"
              href={preview.src}
              rel="noreferrer"
              target="_blank"
              title="打开预览"
            >
              <ExternalLinkIcon />
            </a>
          ) : (
            <IconButton disabled label="打开预览" onClick={() => undefined}>
              <ExternalLinkIcon />
            </IconButton>
          )}
          {canAnnotate ? (
            <AnnotationModeButton
              active={annotationMode}
              label={annotationMode ? "关闭注释" : "添加注释"}
              onClick={handleToggleAnnotationMode}
            />
          ) : null}
        </div>
      </div>

      <div className="relative min-h-0 flex-1 bg-zinc-200">
        {preview ? (
          <>
            <iframe
              className="h-full w-full border-0 bg-white"
              key={`${preview.src}-${reloadNonce}`}
              onLoad={() => {
                postToPreview({
                  enabled: annotationMode && canAnnotate,
                  type: "preview-set-annotation-mode",
                });
                postToPreview({
                  enabled: canSelectTutorTarget,
                  type: "preview-set-tutor-target-mode",
                });
                requestTargetRects();
              }}
              ref={iframeRef}
              src={preview.src}
              title={`${preview.title}预览`}
            />
            {canAnnotate ? (
              <AnnotationOverlay
                annotationError={annotationError}
                annotationMode={annotationMode}
                comment={comment}
                isCreatingAnnotation={isCreatingAnnotation}
                markerPositions={markerPositions}
                selectedMarker={selectedMarker}
                selectedTarget={selectedTarget}
                onCloseMarker={() => setSelectedMarker(null)}
                onCloseTarget={() => {
                  setSelectedTarget(null);
                  setComment("");
                  setAnnotationError(null);
                }}
                onCommentChange={setComment}
                onCreateAnnotation={handleCreateAnnotation}
                onSelectMarker={setSelectedMarker}
              />
            ) : null}
            {canSelectTutorTarget ? (
              <TutorPromptOverlay
                prompt={tutorPrompt}
                selectedTarget={tutorTarget}
                onClose={() => {
                  setTutorTarget(null);
                  setTutorPrompt("");
                }}
                onPromptChange={setTutorPrompt}
                onSubmit={handleTutorPromptSubmit}
              />
            ) : null}
          </>
        ) : (
          <div className="flex h-full items-center justify-center rounded border border-dashed border-zinc-300 bg-zinc-50 text-sm text-zinc-500">
            当前对象暂无网页预览。
          </div>
        )}
      </div>
    </section>
  );
}

function TutorPromptOverlay({
  onClose,
  onPromptChange,
  onSubmit,
  prompt,
  selectedTarget,
}: {
  onClose: () => void;
  onPromptChange: (prompt: string) => void;
  onSubmit: () => void;
  prompt: string;
  selectedTarget: PreviewTargetSelectedMessage | null;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const targetPosition = selectedTarget
    ? {
        left: `max(1rem, min(${selectedTarget.clientX + 12}px, calc(100% - 25rem)))`,
        top: `max(1rem, min(${selectedTarget.clientY + 12}px, calc(100% - 12rem)))`,
      }
    : { left: 16, top: 16 };

  useEffect(() => {
    if (!selectedTarget) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      textareaRef.current?.focus();
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [selectedTarget]);

  useEffect(() => {
    const input = textareaRef.current;

    if (!input) {
      return;
    }

    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 144)}px`;
  }, [prompt]);

  useEffect(() => {
    if (!selectedTarget) {
      return;
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose, selectedTarget]);

  if (!selectedTarget) {
    return null;
  }

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <div
        className="pointer-events-auto absolute w-96 max-w-[calc(100%-2rem)] rounded-[28px] border border-zinc-200 bg-white px-4 py-3 shadow-xl"
        style={targetPosition}
      >
        <div className="flex items-end gap-3">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full text-zinc-400">
            <SlidersIcon />
          </span>
          <textarea
            className="max-h-36 min-h-8 min-w-0 flex-1 resize-none overflow-y-auto bg-transparent py-1 text-base leading-7 outline-none placeholder:text-zinc-400"
            onChange={(event) => onPromptChange(event.target.value)}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing &&
                prompt.trim()
              ) {
                event.preventDefault();
                onSubmit();
              }
            }}
            placeholder="问这里..."
            ref={textareaRef}
            rows={1}
            value={prompt}
          />
          {prompt.trim() ? (
            <button
              aria-label="发送提问"
              className="flex size-9 shrink-0 items-center justify-center rounded-full bg-zinc-900 text-white transition hover:bg-zinc-700"
              onClick={onSubmit}
              type="button"
            >
              <ArrowUpIcon />
            </button>
          ) : (
            <span className="flex size-8 shrink-0 items-center justify-center text-zinc-400">
              <MicIcon />
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function IconButton({
  active,
  children,
  disabled,
  label,
  onClick,
}: {
  active?: boolean;
  children: ReactNode;
  disabled?: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-label={label}
      className={`flex size-8 shrink-0 items-center justify-center rounded-md transition hover:bg-zinc-100 hover:text-zinc-900 disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent disabled:hover:text-zinc-500 ${
        active ? "bg-teal-50 text-teal-700" : "text-zinc-500"
      }`}
      disabled={disabled}
      onClick={onClick}
      title={label}
      type="button"
    >
      {children}
    </button>
  );
}

function AnnotationModeButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  if (active) {
    return (
      <button
        aria-label={label}
        className="flex h-9 shrink-0 items-center gap-2 rounded-2xl bg-sky-50 px-3 text-sm font-medium text-sky-600 transition hover:bg-sky-100"
        onClick={onClick}
        title={label}
        type="button"
      >
        <span className="flex size-5 items-center justify-center rounded-full border border-sky-500 text-sky-600">
          <AnnotationIcon />
        </span>
        <span>正在注释</span>
      </button>
    );
  }

  return (
    <IconButton label={label} onClick={onClick}>
      <AnnotationIcon />
    </IconButton>
  );
}

function getPreview(selectedObject: SelectedWorkspaceObject):
  | { src: string; title: string }
  | null {
  if (selectedObject.kind === "problem") {
    return {
      src: previewUrlWithVersion(
        selectedObject.item.previewUrl,
        selectedObject.item.previewVersion,
      ),
      title: selectedObject.item.shortTitle,
    };
  }

  if (selectedObject.kind === "site_home") {
    return {
      src: selectedObject.item.previewUrl,
      title: selectedObject.item.siteName,
    };
  }

  if (selectedObject.kind === "topic") {
    return {
      src: previewUrlWithVersion(
        selectedObject.item.previewUrl,
        selectedObject.item.previewVersion,
      ),
      title: selectedObject.item.title,
    };
  }

  return null;
}
