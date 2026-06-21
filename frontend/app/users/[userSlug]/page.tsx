import { MockPublicPage } from "../_components/mock-public-page";

export default async function MockUserHomePage({
  params,
}: {
  params: Promise<{ userSlug: string }>;
}) {
  const { userSlug } = await params;

  return (
    <MockPublicPage
      description="这是本地开发使用的 mock 公开首页，用于验证发布后的站点路径。真实发布仍会落到静态站点产物。"
      path={`/users/${userSlug}/`}
      title="数学可视化题库"
    />
  );
}
