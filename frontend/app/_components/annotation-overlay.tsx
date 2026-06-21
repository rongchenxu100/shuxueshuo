import { useEffect, useRef } from "react";

import type { WebAnnotation } from "@/lib/contracts";

import {
  type PreviewTargetSelectedMessage,
  getAnnotationMarkerPositions,
} from "./preview-bridge";
import {
  AnnotationIcon,
  ArrowUpIcon,
  MicIcon,
  SlidersIcon,
} from "./ui/icons";

export function AnnotationOverlay({
  annotationError,
  annotationMode,
  comment,
  isCreatingAnnotation,
  markerPositions,
  onCloseMarker,
  onCloseTarget,
  onCommentChange,
  onCreateAnnotation,
  onSelectMarker,
  selectedMarker,
  selectedTarget,
}: {
  annotationError: string | null;
  annotationMode: boolean;
  comment: string;
  isCreatingAnnotation: boolean;
  markerPositions: ReturnType<typeof getAnnotationMarkerPositions>;
  onCloseMarker: () => void;
  onCloseTarget: () => void;
  onCommentChange: (comment: string) => void;
  onCreateAnnotation: () => void;
  onSelectMarker: (annotation: WebAnnotation) => void;
  selectedMarker: WebAnnotation | null;
  selectedTarget: PreviewTargetSelectedMessage | null;
}) {
  const commentInputRef = useRef<HTMLTextAreaElement>(null);
  const visibleMarkerPositions = annotationMode ? markerPositions : [];
  const targetPosition = selectedTarget
    ? {
        left: `max(1rem, min(${selectedTarget.clientX + 12}px, calc(100% - 25rem)))`,
        top: `max(1rem, min(${selectedTarget.clientY + 12}px, calc(100% - 14rem)))`,
      }
    : { left: 16, top: 16 };
  const selectedMarkerPosition = selectedMarker
    ? visibleMarkerPositions.find(
        (position) => position.annotation.id === selectedMarker.id,
      )
    : null;

  useEffect(() => {
    if (!selectedTarget) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      commentInputRef.current?.focus();
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [selectedTarget]);

  useEffect(() => {
    const input = commentInputRef.current;

    if (!input) {
      return;
    }

    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
  }, [comment]);

  useEffect(() => {
    if (!selectedTarget && !selectedMarker) {
      return;
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onCloseTarget();
        onCloseMarker();
      }
    }

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onCloseMarker, onCloseTarget, selectedMarker, selectedTarget]);

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {annotationMode ? (
        <div className="absolute left-3 top-3 flex items-center gap-1.5 rounded-full bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-600 shadow-sm">
          <span className="flex size-4 items-center justify-center rounded-full border border-sky-500">
            <AnnotationIcon />
          </span>
          正在注释
        </div>
      ) : null}
      {visibleMarkerPositions.map((position, index) => (
        <button
          aria-label={`查看注释 ${index + 1}`}
          className="pointer-events-auto absolute flex size-7 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-2 border-white bg-teal-600 text-xs font-semibold text-white shadow-lg transition hover:bg-teal-700"
          key={position.annotation.id}
          onClick={() => {
            onCloseTarget();
            onSelectMarker(position.annotation);
          }}
          style={{ left: position.x, top: position.y }}
          type="button"
        >
          {index + 1}
        </button>
      ))}
      {selectedMarker && selectedMarkerPosition ? (
        <div
          className="pointer-events-auto absolute w-64 rounded-2xl border border-zinc-200 bg-white p-3 text-sm shadow-xl"
          style={{
            left: `min(${selectedMarkerPosition.x + 14}px, calc(100% - 17rem))`,
            top: selectedMarkerPosition.y + 14,
          }}
        >
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="font-medium text-zinc-900">
                {selectedMarker.label}
              </div>
              <p className="mt-1 leading-5 text-zinc-600">
                {selectedMarker.comment}
              </p>
            </div>
            <button
              className="rounded-md px-1.5 text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-900"
              onClick={onCloseMarker}
              type="button"
            >
              关闭
            </button>
          </div>
        </div>
      ) : null}
      {selectedTarget ? (
        <div
          className="pointer-events-auto absolute w-96 max-w-[calc(100%-2rem)] rounded-[28px] border border-zinc-200 bg-white px-4 py-3 shadow-xl"
          style={targetPosition}
        >
          <div className="flex items-end gap-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full text-zinc-400">
              <SlidersIcon />
            </span>
            <textarea
              className="max-h-40 min-h-8 min-w-0 flex-1 resize-none overflow-y-auto bg-transparent py-1 text-base leading-7 outline-none placeholder:text-zinc-400"
              disabled={isCreatingAnnotation}
              onChange={(event) => onCommentChange(event.target.value)}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing &&
                  comment.trim()
                ) {
                  event.preventDefault();
                  onCreateAnnotation();
                }
              }}
              placeholder="添加评论..."
              ref={commentInputRef}
              rows={1}
              value={comment}
            />
            {comment.trim() ? (
              <button
                aria-label="发送注释"
                className="flex size-9 shrink-0 items-center justify-center rounded-full bg-zinc-900 text-white transition hover:bg-zinc-700 disabled:cursor-not-allowed disabled:bg-zinc-300"
                disabled={isCreatingAnnotation}
                onClick={onCreateAnnotation}
                type="button"
              >
                {isCreatingAnnotation ? (
                  <span className="text-xs">...</span>
                ) : (
                  <ArrowUpIcon />
                )}
              </button>
            ) : (
              <span className="flex size-8 shrink-0 items-center justify-center text-zinc-400">
                <MicIcon />
              </span>
            )}
          </div>
          {annotationError ? (
            <p className="mt-2 px-2 text-xs text-red-700">
              {annotationError}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
