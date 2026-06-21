import type { AnnotationTargetType, WebAnnotation } from "@/lib/contracts";

export type PreviewTargetRect = {
  height: number;
  left: number;
  targetId: string;
  top: number;
  width: number;
};

export type PreviewTargetSelectedMessage = {
  type: "preview-target-selected";
  clientX: number;
  clientY: number;
  label: string;
  problemId?: string;
  screenshotRecommended?: boolean;
  stepId?: string;
  targetId: string;
  targetType: AnnotationTargetType;
};

export type PreviewTargetRectsMessage = {
  type: "preview-target-rects";
  rects: PreviewTargetRect[];
};

export type PreviewBridgeMessage =
  | { type: "preview-layout-changed" }
  | { type: "preview-ready" }
  | PreviewTargetSelectedMessage
  | PreviewTargetRectsMessage;

export type PreviewCommandMessage =
  | { enabled: boolean; type: "preview-set-annotation-mode" }
  | { enabled: boolean; type: "preview-set-tutor-target-mode" }
  | { targetIds?: string[]; type: "preview-request-target-rects" }
  | { stepId: string; type: "preview-scroll-to-step" }
  | { targetId: string; type: "preview-highlight-target" };

export type AnnotationMarkerPosition = {
  annotation: WebAnnotation;
  x: number;
  y: number;
};

export function getPreviewOrigin(
  previewSrc: string,
  fallbackOrigin: string,
): string {
  return new URL(previewSrc, fallbackOrigin).origin;
}

export function isPreviewBridgeMessage(
  value: unknown,
): value is PreviewBridgeMessage {
  return (
    typeof value === "object" &&
    value !== null &&
    "type" in value &&
    typeof value.type === "string" &&
    value.type.startsWith("preview-")
  );
}

export function canAcceptPreviewMessage({
  eventOrigin,
  eventSource,
  expectedOrigin,
  iframeWindow,
}: {
  eventOrigin: string;
  eventSource: MessageEventSource | null;
  expectedOrigin: string;
  iframeWindow: Window | null;
}): boolean {
  return eventSource === iframeWindow && eventOrigin === expectedOrigin;
}

export function targetRectToMarkerPosition(rect: PreviewTargetRect) {
  return {
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2,
  };
}

export function getAnnotationMarkerPositions(
  annotations: WebAnnotation[],
  targetRects: PreviewTargetRect[],
): AnnotationMarkerPosition[] {
  const rectsByTargetId = new Map(
    targetRects.map((rect) => [rect.targetId, rect]),
  );

  return annotations.flatMap((annotation) => {
    const rect = rectsByTargetId.get(annotation.targetId);

    if (!rect) {
      return [];
    }

    return [
      {
        annotation,
        ...targetRectToMarkerPosition(rect),
      },
    ];
  });
}
