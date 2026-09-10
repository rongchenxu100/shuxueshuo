import { ReviewDetail } from "../review-ui";
export default async function Page({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return <ReviewDetail key={runId} runId={runId} />;
}
