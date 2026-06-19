import { NextResponse } from "next/server";

import { StartProblemUploadResponseSchema } from "@/lib/contracts";

export async function POST(request: Request) {
  const formData = await request.formData();
  const scenario = String(formData.get("scenario") ?? "success");
  const jobId = `job_upload_${Date.now()}`;
  const query = new URLSearchParams({ scenario });
  const response = StartProblemUploadResponseSchema.parse({
    jobId,
    streamUrl: `/api/problem-upload-jobs/${jobId}/events?${query.toString()}`,
  });

  return NextResponse.json(response);
}
