import type { PublishStatus } from "@/lib/contracts";

import { publishStatusLabel } from "../workspace-model";

export function HeaderBlock({
  description,
  status,
  title,
}: {
  description: string;
  status: PublishStatus;
  title: string;
}) {
  return (
    <header>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-2xl font-semibold tracking-tight">{title}</h3>
          <p className="mt-2 text-sm leading-6 text-zinc-600">{description}</p>
        </div>
        <span className="shrink-0 rounded border border-zinc-200 bg-white px-2 py-1 text-xs text-zinc-600">
          {publishStatusLabel(status)}
        </span>
      </div>
    </header>
  );
}
