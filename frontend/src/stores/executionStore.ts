/**
 * Execution Store - Track chain execution state
 */

import { create } from "zustand";

// =============================================================================
// Types
// =============================================================================

export type StepStatus =
  | "idle"
  | "executing"
  | "waiting_approval"
  | "completed"
  | "failed";

export interface StepExecution {
  status: StepStatus;
  progress?: number;        // 0-1 during execution
  currentNode?: string;     // ComfyUI node ID being executed
  currentNodeName?: string; // ComfyUI node name being executed
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

export interface HistoricalStep {
  stepId: string;
  status: string;
  artifactUrl?: string;
  artifactId?: string;
  error?: string;
}

// =============================================================================
// Store
// =============================================================================

interface ExecutionStore {
  // Current chain execution (null if not executing)
  execution: ChainExecution | null;

  // Update mode state - node ID that is requesting parameter update
  updateModeNodeId: string | null;

  // Actions
  startExecution: (chainId: string, jobId: string, stepIds: string[]) => void;
  loadFromHistory: (chainId: string, status: "completed" | "failed", steps: HistoricalStep[]) => void;
  clearExecution: () => void;

  // Update mode actions
  requestUpdateMode: (nodeId: string) => void;
  clearUpdateMode: () => void;

  // Event handlers (called by SSE hook)
  onStepExecuting: (stepId: string, workflow: string, server: string) => void;
  onStepNode: (stepId: string, nodeId: string, nodeName?: string, progress?: number) => void;
  onStepWorkflowComplete: (stepId: string, outputCount: number) => void;
  onStepWorkflowFailed: (stepId: string, error: string) => void;
  onStepValidationFailed: (stepId: string, errorType: string, errorMessage: string) => void;
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
}

export const useExecutionStore = create<ExecutionStore>((set, get) => ({
  execution: null,
  updateModeNodeId: null,

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

  loadFromHistory: (chainId, status, steps) => {
    const stepExecution: Record<string, StepExecution> = {};
    for (const step of steps) {
      stepExecution[step.stepId] = {
        status: step.status === "completed" ? "completed" : step.status === "failed" ? "failed" : "idle",
        progress: step.status === "completed" ? 1 : 0,
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

  onStepExecuting: (stepId, workflow, server) => {
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

  onStepWorkflowFailed: (stepId, error) => {
    set((state) => {
      if (!state.execution) return state;
      return {
        execution: {
          ...state.execution,
          steps: {
            ...state.execution.steps,
            [stepId]: {
              ...state.execution.steps[stepId],
              status: "failed",
              error,
            },
          },
        },
      };
    });
  },

  onStepValidationFailed: (stepId, errorType, errorMessage) => {
    set((state) => {
      if (!state.execution) return state;
      return {
        execution: {
          ...state.execution,
          steps: {
            ...state.execution.steps,
            [stepId]: {
              ...state.execution.steps[stepId],
              status: "failed",
              error: `${errorType}: ${errorMessage}`,
            },
          },
        },
      };
    });
  },

  onStepCompleted: (stepId, artifactId) => {
    set((state) => {
      if (!state.execution) return state;
      const gatewayUrl = "http://localhost:8001"; // TODO: Make configurable
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
              artifactUrl: artifactId ? `${gatewayUrl}/artifacts/${artifactId}` : undefined,
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
      return {
        execution: {
          ...state.execution,
          status: "completed",
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
    const GATEWAY_URL = "http://localhost:8001";
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
    const GATEWAY_URL = "http://localhost:8001";
    const response = await fetch(`${GATEWAY_URL}/chains/${chainId}/pending-steps`);
    if (!response.ok) {
      throw new Error("Failed to get pending steps");
    }
    const data = await response.json();
    return data.pending_steps || [];
  },

  skipLevelWait: async (chainId, levelNum) => {
    const GATEWAY_URL = "http://localhost:8001";
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
    const GATEWAY_URL = "http://localhost:8001";
    const response = await fetch(`${GATEWAY_URL}/chains/${chainId}/cancel`, {
      method: "POST",
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(error.detail || "Failed to cancel chain");
    }
  },
}));
