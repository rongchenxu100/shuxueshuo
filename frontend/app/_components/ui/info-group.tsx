export function InfoGroup({ items }: { items: Array<[string, string]> }) {
  return (
    <dl className="grid gap-3">
      {items.map(([label, value]) => (
        <div
          className="rounded-md border border-zinc-200 bg-white px-4 py-3"
          key={label}
        >
          <dt className="text-xs font-medium text-zinc-500">{label}</dt>
          <dd className="mt-1 text-sm text-zinc-800">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
