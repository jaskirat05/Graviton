/**
 * Execution Store - Track chain execution state
 */

import { create } from "zustand";

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:8001";

// =============================================================================
// Types
// =============================================================================

export type StepStatus =
  | "idle"
  | "executing"
  | "waiting_approval"
  | "completed"
  | "cached"
  | "failed";

export interface StepExecution {
  status: StepStatus;
  progress?: number;        // 0-1 during execution
  currentNode?: string;     // ComfyUI node ID being executed
  currentNodeName?: string; // ComfyUI node name being executed
  failedNodeId?: string;    // ComfyUI node ID that caused failure
  failedNodeName?: string;  // ComfyUI node name that caused failure
  error?: string;           // Error message if failed
  outputCount?: number;     // Number of outputs
  artifactUrl?: string;     // URL to view output
  artifactId?: string;      // Artifact ID
}

export interface PendingApproval {
  stepId: string;
  token: string;
  workflow: string;
  artifactUrl: string;
  artifactId: string;
}

export interface ChainExecution {
  chainId: string;
  jobId: string;
  status: "running" | "completed" | "failed";
  steps: Record<string, StepExecution>;
  pendingApprovals: PendingApproval[];
  error?: string;
}

export interface FatalExecutionError {
  isOpen: boolean;
  message: string;
  stepId?: string;
}

export interface HistoricalStep {
  stepId: string;
  status: string;
  artifactUrl?: string;
  artifactId?: string;
  error?: string;
}

export interface CachedStepUpdate {
  stepId: string;
  artifactUrl?: string;
  artifactId?: string;
}

// =============================================================================
// Store
// =============================================================================

interface ExecutionStore {
  // Current chain execution (null if not executing)
  execution: ChainExecution | null;

  // Update mode state - node ID that is requesting parameter update
  updateModeNodeId: string | null;
  fatalError: FatalExecutionError | null;

  // Actions
  startExecution: (chainId: string, jobId: string, stepIds: string[]) => void;
  loadFromHistory: (chainId: string, status: "completed" | "failed", steps: HistoricalStep[]) => void;
  markStepsCached: (steps: CachedStepUpdate[]) => void;
  clearExecution: () => void;
  closeFatalError: () => void;

  // Update mode actions
  requestUpdateMode: (nodeId: string) => void;
  clearUpdateMode: () => void;

  // Event handlers (called by SSE hook)
  onStepExecuting: (stepId: string, workflow: string, server: string) => void;
  onStepNode: (stepId: string, nodeId: string, nodeName?: string, progress?: number) => void;
  onStepWorkflowComplete: (stepId: string, outputCount: number) => void;
  onStepWorkflowFailed: (stepId: string, error: string, nodeId?: string, nodeName?: string) => void;
  onStepValidationFailed: (stepId: string, errorType: string, errorMessage: string) => void;
  onStepCached: (stepId: string, artifactId?: string, artifactUrl?: string) => void;
  onStepCompleted: (stepId: string, artifactId?: string) => void;
  onApprovalRequested: (stepId: string, token: string, workflow: string, artifactUrl: string, artifactId: string) => void;
  onApprovalResolved: (stepId: string) => void;
  onChainCompleted: () => void;
  onChainFailed: (error: string) => void;

  // Approval actions
  getStepExecution: (stepId: string) => StepExecution | undefined;
  getPendingApproval: (stepId: string) => PendingApproval | undefined;

  // Parameter update actions
  updateStepParameters: (
    chainId: string,
    stepId: string,
    parameters: Record<string, unknown>
  ) => Promise<void>;
  getPendingSteps: (chainId: string) => Promise<string[]>;
  skipLevelWait: (chainId: string, levelNum?: number) => Promise<void>;
  cancelChain: (chainId: string) => Promise<void>;
  abortAllChains: () => Promise<{ requested_count: number; cancelled_count: number }>;
}

export const useExecutionStore = create<ExecutionStore>((set, get) => ({
  execution: null,
  updateModeNodeId: null,
  fatalError: null,

  requestUpdateMode: (nodeId) => set({ updateModeNodeId: nodeId }),
  clearUpdateMode: () => set({ updateModeNodeId: null }),

  startExecution: (chainId, jobId, stepIds) => {
    const steps: Record<string, StepExecution> = {};
    for (const stepId of stepIds) {
      steps[stepId] = { status: "idle" };
    }
    set({
      execution: {
        chainId,
        jobId,
        status: "running",
        steps,
        pendingApprovals: [],
      },
    });
  },

  clearExecution: () => set({ execution: null }),
  closeFatalError: () => set({ fatalError: null }),

  loadFromHistory: (chainId, status, steps) => {
    const stepExecution: Record<string, StepExecution> = {};
    for (const step of steps) {
      const normalizedStatus: StepStatus =
        step.status === "completed"
          ? "completed"
          : step.status === "failed"
            ? "failed"
            : step.status === "cached"
              ? "cached"
              : "idle";
      stepExecution[step.stepId] = {
        status: normalizedStatus,
        progress: normalizedStatus === "completed" || normalizedStatus === "cached" ? 1 : 0,
        artifactUrl: step.artifactUrl,
        artifactId: step.artifactId,
        error: step.error,
      };
    }
    set({
      execution: {
        chainId,
        jobId: chainId, // Use chainId as jobId for historical
        status,
        steps: stepExecution,
        pendingApprovals: [],
      },
    });
  },

  markStepsCached: (steps) => {
    set((state) => {
      if (!state.execution || steps.length === 0) return state;
      const nextSteps = { ...state.execution.steps };
      for (const step of steps) {
        const existing = nextSteps[step.stepId] || { status: "idle" as StepStatus };
        if (existing.status === "failed") {
          continue;
        }
        nextSteps[step.stepId] = {
          ...existing,
          status: "cached",
          progress: 1,
          artifactUrl: step.artifactUrl ?? existing.artifactUrl,
          artifactId: step.artifactId ?? existing.artifactId,
        };
      }
      return {
        execution: {
          ...state.execution,
          steps: nextSteps,
        },
      };
    });
  },

  onStepExecuting: (stepId) => {
    set((state) => {
      if (!state.execution) return state;
      return {
        execution: {
          ...state.execution,
          steps: {
            ...state.execution.steps,
            [stepId]: {
              ...state.execution.steps[stepId],
              status: "executing",
              progress: 0,
              error: undefined,
            },
          },
        },
      };
    });
  },

  onStepNode: (stepId, nodeId, nodeName, progress) => {
    set((state) => {
      if (!state.execution) return state;
      return {
        execution: {
          ...state.execution,
          steps: {
            ...state.execution.steps,
            [stepId]: {
              ...state.execution.steps[stepId],
              currentNode: nodeId,
              currentNodeName: nodeName,
              progress: progress ?? state.execution.steps[stepId]?.progress,
            },
          },
        },
      };
    });
  },

  onStepWorkflowComplete: (stepId, outputCount) => {
    set((state) => {
      if (!state.execution) return state;
      return {
        execution: {
          ...state.execution,
          steps: {
            ...state.execution.steps,
            [stepId]: {
              ...state.execution.steps[stepId],
              progress: 1,
              outputCount,
            },
          },
        },
      };
    });
  },

  onStepWorkflowFailed: (stepId, error, nodeId, nodeName) => {
    set((state) => {
      if (!state.execution) return state;
      return {
        execution: {
          ...state.execution,
          status: "failed",
          error,
          steps: {
            ...state.execution.steps,
            [stepId]: {
              ...state.execution.steps[stepId],
              status: "failed",
              failedNodeId: nodeId,
              failedNodeName: nodeName,
              currentNode: nodeId || state.execution.steps[stepId]?.currentNode,
              currentNodeName: nodeName || state.execution.steps[stepId]?.currentNodeName,
              error,
            },
          },
        },
        fatalError: {
          isOpen: true,
          message: error,
          stepId,
        },
      };
    });
  },

  onStepValidationFailed: (stepId, errorType, errorMessage) => {
    set((state) => {
      if (!state.execution) return state;
      const message = `${errorType}: ${errorMessage}`;
      return {
        execution: {
          ...state.execution,
          status: "failed",
          error: message,
          steps: {
            ...state.execution.steps,
            [stepId]: {
              ...state.execution.steps[stepId],
              status: "failed",
              error: message,
            },
          },
        },
        fatalError: {
          isOpen: true,
          message,
          stepId,
        },
      };
    });
  },

  onStepCached: (stepId, artifactId, artifactUrl) => {
    set((state) => {
      if (!state.execution) return state;
      const normalizedUrl =
        typeof artifactUrl === "string" && artifactUrl.startsWith("/")
          ? `${GATEWAY_URL}${artifactUrl}`
          : artifactUrl;
      const resolvedUrl =
        normalizedUrl ||
        (artifactId ? `${GATEWAY_URL}/artifact-service/artifacts/${artifactId}/download` : undefined);
      return {
        execution: {
          ...state.execution,
          steps: {
            ...state.execution.steps,
            [stepId]: {
              ...state.execution.steps[stepId],
              status: "cached",
              progress: 1,
              artifactId: artifactId ?? state.execution.steps[stepId]?.artifactId,
              artifactUrl: resolvedUrl ?? state.execution.steps[stepId]?.artifactUrl,
            },
          },
        },
      };
    });
  },

  onStepCompleted: (stepId, artifactId) => {
    set((state) => {
      if (!state.execution) return state;
      const currentStep = state.execution.steps[stepId];
      if (currentStep?.status === "failed") {
        return state;
      }
      return {
        execution: {
          ...state.execution,
          steps: {
            ...state.execution.steps,
            [stepId]: {
              ...state.execution.steps[stepId],
              status: "completed",
              progress: 1,
              artifactId,
              artifactUrl: artifactId
                ? `${GATEWAY_URL}/artifact-service/artifacts/${artifactId}/download`
                : undefined,
            },
          },
        },
      };
    });
  },

  onApprovalRequested: (stepId, token, workflow, artifactUrl, artifactId) => {
    set((state) => {
      if (!state.execution) return state;
      return {
        execution: {
          ...state.execution,
          steps: {
            ...state.execution.steps,
            [stepId]: {
              ...state.execution.steps[stepId],
              status: "waiting_approval",
              artifactUrl,
              artifactId,
            },
          },
          pendingApprovals: [
            ...state.execution.pendingApprovals,
            { stepId, token, workflow, artifactUrl, artifactId },
          ],
        },
      };
    });
  },

  onApprovalResolved: (stepId) => {
    set((state) => {
      if (!state.execution) return state;
      return {
        execution: {
          ...state.execution,
          pendingApprovals: state.execution.pendingApprovals.filter(
            (a) => a.stepId !== stepId
          ),
        },
      };
    });
  },

  onChainCompleted: () => {
    set((state) => {
      if (!state.execution) return state;
      const hasFailedStep = Object.values(state.execution.steps).some((step) => step.status === "failed");
      return {
        execution: {
          ...state.execution,
          status: hasFailedStep ? "failed" : "completed",
        },
      };
    });
  },

  onChainFailed: (error) => {
    set((state) => {
      if (!state.execution) return state;
      return {
        execution: {
          ...state.execution,
          status: "failed",
          error,
        },
      };
    });
  },

  getStepExecution: (stepId) => get().execution?.steps[stepId],

  getPendingApproval: (stepId) =>
    get().execution?.pendingApprovals.find((a) => a.stepId === stepId),

  updateStepParameters: async (chainId, stepId, parameters) => {
    const response = await fetch(
      `${GATEWAY_URL}/chains/${chainId}/steps/${stepId}/update-parameters`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parameters }),
      }
    );
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(error.detail || "Failed to update parameters");
    }
  },

  getPendingSteps: async (chainId) => {
    const response = await fetch(`${GATEWAY_URL}/chains/${chainId}/pending-steps`);
    if (!response.ok) {
      throw new Error("Failed to get pending steps");
    }
    const data = await response.json();
    return data.pending_steps || [];
  },

  skipLevelWait: async (chainId, levelNum) => {
    const url = new URL(`${GATEWAY_URL}/chains/${chainId}/skip-level-wait`);
    if (levelNum !== undefined) {
      url.searchParams.set("level_num", levelNum.toString());
    }
    const response = await fetch(url.toString(), { method: "POST" });
    if (!response.ok) {
      throw new Error("Failed to skip level wait");
    }
  },

  cancelChain: async (chainId) => {
    const response = await fetch(`${GATEWAY_URL}/chains/${chainId}/cancel`, {
      method: "POST",
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(error.detail || "Failed to cancel chain");
    }
  },

  abortAllChains: async () => {
    const response = await fetch(`${GATEWAY_URL}/chains/abort-all`, {
      method: "POST",
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(error.detail || "Failed to abort all chains");
    }
    const payload = await response.json();
    return {
      requested_count: Number(payload?.requested_count || 0),
      cancelled_count: Number(payload?.cancelled_count || 0),
    };
  },
}));
