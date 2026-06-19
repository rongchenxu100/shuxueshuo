import { formatSseEvent } from "@/lib/api/sse";
import { createMockProblemFromUpload } from "@/lib/mock/problem-factory";

const encoder = new TextEncoder();

const progressEvents = [
  { stage: "stored", message: "图片已上传" },
  { stage: "detecting", message: "正在识别题目" },
  { stage: "ocr", message: "正在提取题干" },
  { stage: "generating", message: "正在生成解题方案" },
  { stage: "compiling", message: "正在编译网页" },
] as const;

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const scenario = searchParams.get("scenario") ?? "success";
  const stream = new ReadableStream({
    async start(controller) {
      for (const [index, event] of progressEvents.entries()) {
        controller.enqueue(encoder.encode(formatSseEvent("progress", event)));
        await delay(350);

        if (scenario === "disconnect" && index === 2) {
          controller.close();
          return;
        }
      }

      if (scenario === "rejected") {
        controller.enqueue(
          encoder.encode(
            formatSseEvent("rejected", {
              message: "没有识别到完整题目",
            }),
          ),
        );
        controller.close();
        return;
      }

      if (scenario === "failed") {
        controller.enqueue(
          encoder.encode(
            formatSseEvent("failed", {
              error: {
                code: "mock_generation_failed",
                message: "生成解题方案失败，请重试。",
                retryable: true,
              },
            }),
          ),
        );
        controller.close();
        return;
      }

      controller.enqueue(
        encoder.encode(
          formatSseEvent("done", {
            result: "created",
            ...createMockProblemFromUpload(),
          }),
        ),
      );
      controller.close();
    },
  });

  return new Response(stream, {
    headers: {
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "Content-Type": "text/event-stream",
    },
  });
}

function delay(ms: number) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
