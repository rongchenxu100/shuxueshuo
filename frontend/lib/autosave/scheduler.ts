export const AUTOSAVE_DEBOUNCE_MS = 1500;
export const AUTOSAVE_MAX_INTERVAL_MS = 30000;

export function getAutosaveDelayMs(
  lastSaveStartedAt: number | null,
  now: number,
): number {
  if (lastSaveStartedAt === null) {
    return AUTOSAVE_DEBOUNCE_MS;
  }

  const elapsed = now - lastSaveStartedAt;
  const maxIntervalRemaining = AUTOSAVE_MAX_INTERVAL_MS - elapsed;

  return Math.max(0, Math.min(AUTOSAVE_DEBOUNCE_MS, maxIntervalRemaining));
}
