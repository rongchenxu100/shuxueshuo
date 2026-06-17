export function PlaceholderContent({
  description,
  title,
}: {
  description: string;
  title: string;
}) {
  return (
    <section className="rounded-md border border-dashed border-zinc-300 bg-white px-4 py-5">
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="mt-2 text-sm leading-6 text-zinc-500">{description}</p>
    </section>
  );
}
