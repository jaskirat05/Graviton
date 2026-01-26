/**
 * LevelWaitBar - Shows a shrinking progress bar during level wait
 */

import { useEffect, useState } from "react";
import { useLevelWaitStore } from "@/hooks/useLevelWait";

export function LevelWaitBar() {
  const { isWaiting, waitSeconds, startedAt } = useLevelWaitStore();
  const [progress, setProgress] = useState(100);

  useEffect(() => {
    if (!isWaiting || !startedAt || waitSeconds <= 0) {
      setProgress(100);
      return;
    }

    // Update progress every 50ms for smooth animation
    const interval = setInterval(() => {
      const elapsed = (Date.now() - startedAt) / 1000;
      const remaining = Math.max(0, 1 - elapsed / waitSeconds);
      setProgress(remaining * 100);

      if (remaining <= 0) {
        clearInterval(interval);
      }
    }, 50);

    return () => clearInterval(interval);
  }, [isWaiting, startedAt, waitSeconds]);

  if (!isWaiting) {
    return null;
  }

  return (
    <div className="w-full h-1 bg-[var(--surface-3)]">
      <div
        className="h-full bg-green-500 transition-none"
        style={{ width: `${progress}%` }}
      />
    </div>
  );
}
