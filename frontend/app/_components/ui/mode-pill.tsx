export function ModePill({
  active = false,
  label,
}: {
  active?: boolean;
  label: string;
}) {
  return (
    <div
      className={`rounded-md border px-4 py-3 text-center text-sm font-medium ${
        active
          ? "border-teal-300 bg-teal-50 text-teal-900"
          : "border-zinc-200 bg-white text-zinc-500"
      }`}
    >
      {label}
    </div>
  );
}
