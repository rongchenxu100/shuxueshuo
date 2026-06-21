import { describe, expect, it } from "vitest";

import {
  getAnnotationMarkerPositions,
  getPreviewOrigin,
  isPreviewBridgeMessage,
  targetRectToMarkerPosition,
} from "./preview-bridge";
import type { WebAnnotation } from "@/lib/contracts";

const annotation: WebAnnotation = {
  comment: "填充更明显",
  createdAt: "2026-06-16T09:05:00.000Z",
  id: "ann_1",
  label: "第4步 · 图形",
  problemId: "problem_hongqiao_25",
  stepId: "q2s4",
  targetId: "step.q2s4.figure",
  targetType: "step_figure",
};

describe("preview bridge helpers", () => {
  it("resolves preview origin from relative and absolute URLs", () => {
    expect(
      getPreviewOrigin(
        "/preview-fixtures/problems/hongqiao-25.html?v=1",
        "http://localhost:3000",
      ),
    ).toBe("http://localhost:3000");
    expect(
      getPreviewOrigin(
        "https://preview.example.com/problems/1.html",
        "http://localhost:3000",
      ),
    ).toBe("https://preview.example.com");
  });

  it("converts target rects to marker center positions", () => {
    expect(
      targetRectToMarkerPosition({
        height: 40,
        left: 10,
        targetId: "step.q2s4.figure",
        top: 20,
        width: 80,
      }),
    ).toEqual({ x: 50, y: 40 });
  });

  it("ignores annotations without current target rects", () => {
    expect(
      getAnnotationMarkerPositions([annotation], [
        {
          height: 30,
          left: 1,
          targetId: "problem.text",
          top: 2,
          width: 40,
        },
      ]),
    ).toEqual([]);
  });

  it("maps annotations to overlay marker positions", () => {
    expect(
      getAnnotationMarkerPositions([annotation], [
        {
          height: 30,
          left: 5,
          targetId: "step.q2s4.figure",
          top: 10,
          width: 40,
        },
      ]),
    ).toEqual([{ annotation, x: 25, y: 25 }]);
  });

  it("recognizes preview bridge messages", () => {
    expect(isPreviewBridgeMessage({ type: "preview-ready" })).toBe(true);
    expect(isPreviewBridgeMessage({ type: "unrelated" })).toBe(false);
  });
});
