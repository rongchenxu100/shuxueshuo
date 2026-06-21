export function MockPublicPage({
  description,
  path,
  title,
}: {
  description: string;
  path: string;
  title: string;
}) {
  return (
    <main className="min-h-full bg-zinc-50 text-zinc-950">
      <section className="mx-auto flex min-h-full max-w-3xl flex-col justify-center px-6 py-20">
        <p className="mb-3 text-sm font-medium text-teal-700">Phase 5 mock</p>
        <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-4 text-base leading-7 text-zinc-600">
          {description}
        </p>
        <p className="mt-8 rounded-md border border-zinc-200 bg-white px-4 py-3 font-mono text-sm text-zinc-600">
          {path}
        </p>
      </section>
    </main>
  );
}
