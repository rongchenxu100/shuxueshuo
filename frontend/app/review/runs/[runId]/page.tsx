import { ReviewDetail } from "../review-ui";
import { ProductDetail } from "../product-ui";
export default async function Page({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return process.env.REVIEW_BACKEND === 'legacy' ? <ReviewDetail key={runId} runId={runId} /> : <ProductDetail key={runId} runId={runId} />;
}
