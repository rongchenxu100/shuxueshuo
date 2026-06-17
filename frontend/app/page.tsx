import Link from "next/link";

export default function Home() {
  const links = [
    { href: "/api/nav", label: "Mock API：导航数据" },
    {
      href: "/preview-fixtures/problems/hongqiao-25.html",
      label: "题目预览 fixture",
    },
    {
      href: "/preview-fixtures/topics/tianjin-sanmo-25.html",
      label: "专题预览 fixture",
    },
    { href: "/preview-fixtures/site/home.html", label: "首页预览 fixture" },
  ];

  return (
    <main className="min-h-screen bg-slate-50 px-8 py-10 text-slate-950">
      <section className="mx-auto max-w-3xl rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        <p className="text-sm font-medium uppercase tracking-wide text-teal-700">
          Phase 0
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">
          创作后台前端
        </h1>
        <p className="mt-4 max-w-2xl text-base leading-7 text-slate-600">
          Phase 0 已建立独立的前端子项目、接口契约、fixture 数据和最小
          mock API，后续页面会沿真实接口路径继续演进。
        </p>
        <div className="mt-8 grid gap-3">
          {links.map((link) => (
            <Link
              className="rounded-md border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-teal-300 hover:bg-teal-50 hover:text-teal-900"
              href={link.href}
              key={link.href}
            >
              {link.label}
            </Link>
          ))}
        </div>
      </section>
    </main>
  );
}
