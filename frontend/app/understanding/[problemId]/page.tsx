import { UnderstandingWorkspace } from '../../_components/understanding-workspace';
export default async function Page({ params }: { params: Promise<{ problemId: string }> }) {
  const { problemId } = await params;
  return <UnderstandingWorkspace problemId={problemId} />;
}
