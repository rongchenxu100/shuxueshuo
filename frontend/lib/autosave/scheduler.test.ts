import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AUTOSAVE_DEBOUNCE_MS,
  AUTOSAVE_MAX_INTERVAL_MS,
  getAutosaveDelayMs,
} from "./scheduler";

describe("autosave scheduler", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("uses debounce delay when there has not been a save", () => {
    vi.useFakeTimers();
    vi.setSystemTime(1000);

    expect(getAutosaveDelayMs(null, Date.now())).toBe(AUTOSAVE_DEBOUNCE_MS);
  });

  it("uses debounce delay before max interval is close", () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);

    expect(getAutosaveDelayMs(0, Date.now())).toBe(AUTOSAVE_DEBOUNCE_MS);
  });

  it("caps delay at the remaining max interval", () => {
    vi.useFakeTimers();
    vi.setSystemTime(AUTOSAVE_MAX_INTERVAL_MS - 500);

    expect(getAutosaveDelayMs(0, Date.now())).toBe(500);
  });

  it("fires immediately once max interval elapsed", () => {
    vi.useFakeTimers();
    vi.setSystemTime(AUTOSAVE_MAX_INTERVAL_MS + 1);

    expect(getAutosaveDelayMs(0, Date.now())).toBe(0);
  });
});
