import {
  autosaveStateLabel,
  type AutosaveState,
} from "../workspace-model";

export function AutosaveBadge({ state }: { state: AutosaveState }) {
  const styles: Record<AutosaveState, string> = {
    saving: "border-amber-200 bg-amber-50 text-amber-700",
    saved: "border-teal-200 bg-teal-50 text-teal-700",
    error: "border-red-200 bg-red-50 text-red-700",
  };

  return (
    <span
      className={`shrink-0 rounded border px-2 py-1 text-xs font-medium ${styles[state]}`}
    >
      {autosaveStateLabel(state)}
    </span>
  );
}
