import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import type {
  CreateWebAnnotationRequest,
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
  ChevronIcon,
  ExternalLinkIcon,
  RefreshIcon,
} from "./ui/icons";

export function PreviewPane({
  annotations,
  collapsed,
  onCreateAnnotation,
  onToggleCollapsed,
  selectedObject,
}: {
  annotations: WebAnnotation[];
  collapsed: boolean;
  onCreateAnnotation: (
    problemId: string,
    request: CreateWebAnnotationRequest,
  ) => Promise<WebAnnotation>;
  onToggleCollapsed: () => void;
  selectedObject: SelectedWorkspaceObject;
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
  const [isCreatingAnnotation, setIsCreatingAnnotation] = useState(false);
  const [annotationError, setAnnotationError] = useState<string | null>(null);
  const problemId =
    selectedObject.kind === "problem" ? selectedObject.item.id : null;
  const canAnnotate = Boolean(preview && problemId);
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
      setTargetRects([]);
      setAnnotationError(null);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [preview?.src]);

  useEffect(() => {
    if (!canAnnotate || !previewOrigin) {
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

      if (event.data.type === "preview-target-selected" && annotationMode) {
        setSelectedMarker(null);
        setSelectedTarget(event.data);
        setComment("");
        setAnnotationError(null);
        requestTargetRects(event.data.targetId);
      }
    }

    window.addEventListener("message", handleMessage);

    return () => {
      window.removeEventListener("message", handleMessage);
    };
  }, [annotationMode, canAnnotate, previewOrigin, requestTargetRects]);

  useEffect(() => {
    postToPreview({
      enabled: annotationMode && canAnnotate,
      type: "preview-set-annotation-mode",
    });
  }, [annotationMode, canAnnotate, postToPreview, preview?.src]);

  useEffect(() => {
    if (canAnnotate) {
      requestTargetRects();
    }
  }, [canAnnotate, preview?.src, requestTargetRects]);

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
