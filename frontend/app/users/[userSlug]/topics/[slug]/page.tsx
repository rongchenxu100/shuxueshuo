import { MockPublicPage } from "../../../_components/mock-public-page";

export default async function MockTopicPublicPage({
  params,
}: {
  params: Promise<{ slug: string; userSlug: string }>;
}) {
  const { slug, userSlug } = await params;

  return (
    <MockPublicPage
      description="这是本地开发使用的 mock 公开专题页，用于验证专题发布路径。真实发布仍会落到静态站点产物。"
      path={`/users/${userSlug}/topics/${slug}/`}
      title="公开专题页"
    />
  );
}
