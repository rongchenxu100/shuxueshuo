import { useCallback, useEffect, useRef, useState } from "react";

import type { AutosaveState } from "./workspace-model";

export function useAutoFadeSavedBadge({
  autosaveState,
  durationMs = 2400,
  onAutosaveStateChange,
  showAutosave,
}: {
  autosaveState: AutosaveState;
  durationMs?: number;
  onAutosaveStateChange: (state: AutosaveState) => void;
  showAutosave: boolean;
}) {
  const savedFeedbackTimeoutRef = useRef<number | null>(null);
  const [showSavedFeedback, setShowSavedFeedback] = useState(false);

  useEffect(() => {
    return () => {
      if (savedFeedbackTimeoutRef.current !== null) {
        window.clearTimeout(savedFeedbackTimeoutRef.current);
      }
    };
  }, []);

  const handleAutosaveStateChange = useCallback(
    (nextState: AutosaveState) => {
      onAutosaveStateChange(nextState);

      if (savedFeedbackTimeoutRef.current !== null) {
        window.clearTimeout(savedFeedbackTimeoutRef.current);
        savedFeedbackTimeoutRef.current = null;
      }

      if (nextState !== "saved") {
        setShowSavedFeedback(false);
        return;
      }

      setShowSavedFeedback(true);
      savedFeedbackTimeoutRef.current = window.setTimeout(() => {
        setShowSavedFeedback(false);
        savedFeedbackTimeoutRef.current = null;
      }, durationMs);
    },
    [durationMs, onAutosaveStateChange],
  );

  return {
    onAutosaveStateChange: handleAutosaveStateChange,
    shouldShowAutosaveBadge:
      showAutosave && (autosaveState !== "saved" || showSavedFeedback),
  };
}
