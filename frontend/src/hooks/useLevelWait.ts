/**
 * useLevelWait - Hook to track level wait state from SSE events
 */

import { create } from "zustand";

interface LevelWaitState {
  isWaiting: boolean;
  levelNum: number | null;
  waitSeconds: number;
  startedAt: number | null; // timestamp

  // Actions
  startWait: (levelNum: number, waitSeconds: number) => void;
  endWait: () => void;
  clear: () => void;
}

export const useLevelWaitStore = create<LevelWaitState>((set) => ({
  isWaiting: false,
  levelNum: null,
  waitSeconds: 0,
  startedAt: null,

  startWait: (levelNum, waitSeconds) => {
    set({
      isWaiting: true,
      levelNum,
      waitSeconds,
      startedAt: Date.now(),
    });
  },

  endWait: () => {
    set({
      isWaiting: false,
      levelNum: null,
      waitSeconds: 0,
      startedAt: null,
    });
  },

  clear: () => {
    set({
      isWaiting: false,
      levelNum: null,
      waitSeconds: 0,
      startedAt: null,
    });
  },
}));
