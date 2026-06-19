import { NextResponse } from "next/server";

import {
  CreateProblemRequestSchema,
  CreateProblemResponseSchema,
} from "@/lib/contracts";
import { createMockProblemFromText } from "@/lib/mock/problem-factory";

const MOCK_SCENARIOS = new Set(["success", "rejected", "failed", "disconnect"]);

export async function POST(request: Request) {
  const payload = CreateProblemRequestSchema.parse(await request.json());
  const scenarioHeader = request.headers.get("x-mock-scenario") ?? "success";
  const mockScenario = MOCK_SCENARIOS.has(scenarioHeader)
    ? scenarioHeader
    : "success";

  if (mockScenario === "rejected") {
    return NextResponse.json(
      {
        error: {
          code: "mock_not_problem",
          message: "没有识别到完整题目",
          retryable: true,
        },
      },
      { status: 422 },
    );
  }

  if (mockScenario === "failed") {
    return NextResponse.json(
      {
        error: {
          code: "mock_generation_failed",
          message: "生成题目失败，请重试。",
          retryable: true,
        },
      },
      { status: 500 },
    );
  }

  if (mockScenario === "disconnect") {
    return NextResponse.json(
      {
        error: {
          code: "mock_request_disconnected",
          message: "创建连接中断，请重试",
          retryable: true,
        },
      },
      { status: 503 },
    );
  }

  const response = CreateProblemResponseSchema.parse(
    createMockProblemFromText(payload.text),
  );

  return NextResponse.json(response);
}
