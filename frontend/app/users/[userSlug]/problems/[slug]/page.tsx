import { MockPublicPage } from "../../../_components/mock-public-page";

export default async function MockProblemPublicPage({
  params,
}: {
  params: Promise<{ slug: string; userSlug: string }>;
}) {
  const { slug, userSlug } = await params;

  return (
    <MockPublicPage
      description="这是本地开发使用的 mock 公开题目页，用于验证发布、发布更新和打开页面。真实发布仍会落到静态站点产物。"
      path={`/users/${userSlug}/problems/${slug}/`}
      title="公开题目页"
    />
  );
}
