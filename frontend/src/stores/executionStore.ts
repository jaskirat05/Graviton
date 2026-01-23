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
  currentNode?: string;     // ComfyUI node being executed
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

// =============================================================================
// Store
// =============================================================================

interface ExecutionStore {
  // Current chain execution (null if not executing)
  execution: ChainExecution | null;

  // Actions
  startExecution: (chainId: string, jobId: string, stepIds: string[]) => void;
  clearExecution: () => void;

  // Event handlers (called by SSE hook)
  onStepExecuting: (stepId: string, workflow: string, server: string) => void;
  onStepNode: (stepId: string, nodeId: string, progress?: number) => void;
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
}

export const useExecutionStore = create<ExecutionStore>((set, get) => ({
  execution: null,

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

  onStepNode: (stepId, nodeId, progress) => {
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
}));
