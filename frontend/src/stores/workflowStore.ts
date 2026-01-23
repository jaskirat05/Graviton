/**
 * Workflow Store - Zustand store for workflow state management
 *
 * Architecture:
 * - ChainDefinition is the source of truth (persisted to localStorage)
 * - ReactFlow reconstructs nodes/edges from chain on load
 * - Outputs are fetched from backend on reconnect
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ChainDefinition, ChainStep } from "@/components/workflow/types";

// =============================================================================
// Types
// =============================================================================

export type NodeStatus = "idle" | "pending" | "running" | "completed" | "error";

export interface NodeOutput {
  status: NodeStatus;
  image?: string;       // base64 or URL
  video?: string;       // base64 or URL
  error?: string;
  startedAt?: number;
  completedAt?: number;
}

export interface ExecutionState {
  chainId: string | null;
  sseEndpoint: string | null;
  startedAt: number | null;
  status: "idle" | "running" | "completed" | "failed";
}

export interface UIState {
  selectedNodeId: string | null;
  isPanelOpen: boolean;
  contextMenu: {
    show: boolean;
    position: { x: number; y: number };
    flowPosition: { x: number; y: number };
  };
}

export interface WorkflowStore {
  // ==========================================================================
  // State
  // ==========================================================================

  /** The chain definition - source of truth for the workflow */
  chain: ChainDefinition;

  /** Outputs/previews for each node, keyed by step ID */
  nodeOutputs: Record<string, NodeOutput>;

  /** Current execution state */
  execution: ExecutionState;

  /** UI state */
  ui: UIState;

  // ==========================================================================
  // Chain Actions
  // ==========================================================================

  /** Set the entire chain */
  setChain: (chain: ChainDefinition) => void;

  /** Add a step to the chain */
  addStep: (step: ChainStep) => void;

  /** Update a step in the chain */
  updateStep: (stepId: string, updates: Partial<ChainStep>) => void;

  /** Remove a step from the chain */
  removeStep: (stepId: string) => void;

  /** Update step parameters */
  updateStepParameters: (stepId: string, parameters: Record<string, unknown>) => void;

  /** Update step position */
  updateStepPosition: (stepId: string, position: { x: number; y: number }) => void;

  /** Add dependency between steps */
  addDependency: (stepId: string, dependsOnId: string) => void;

  /** Remove dependency between steps */
  removeDependency: (stepId: string, dependsOnId: string) => void;

  /** Get chain ready for execution (strips UI-only fields) */
  getExecutableChain: () => ChainDefinition;

  // ==========================================================================
  // Output Actions
  // ==========================================================================

  /** Set output/preview for a step */
  setNodeOutput: (stepId: string, output: Partial<NodeOutput>) => void;

  /** Set node status */
  setNodeStatus: (stepId: string, status: NodeStatus) => void;

  /** Clear output for a step */
  clearNodeOutput: (stepId: string) => void;

  /** Clear all outputs */
  clearAllOutputs: () => void;

  // ==========================================================================
  // Execution Actions
  // ==========================================================================

  /** Start a new execution */
  startExecution: (chainId: string, sseEndpoint: string) => void;

  /** Update execution status */
  setExecutionStatus: (status: ExecutionState["status"]) => void;

  /** Complete execution */
  completeExecution: (status: "completed" | "failed") => void;

  /** Clear execution state */
  clearExecution: () => void;

  /** Check if there's an active execution to reconnect to */
  hasActiveExecution: () => boolean;

  // ==========================================================================
  // UI Actions
  // ==========================================================================

  /** Select a node */
  selectNode: (nodeId: string | null) => void;

  /** Toggle panel */
  togglePanel: (open?: boolean) => void;

  /** Show context menu */
  showContextMenu: (position: { x: number; y: number }, flowPosition: { x: number; y: number }) => void;

  /** Hide context menu */
  hideContextMenu: () => void;

  // ==========================================================================
  // Workflow Actions
  // ==========================================================================

  /** Clear entire workflow state */
  clearWorkflow: () => void;
}

// =============================================================================
// Initial States
// =============================================================================

const initialChain: ChainDefinition = {
  name: "untitled",
  description: "",
  steps: [],
};

const initialExecutionState: ExecutionState = {
  chainId: null,
  sseEndpoint: null,
  startedAt: null,
  status: "idle",
};

const initialUIState: UIState = {
  selectedNodeId: null,
  isPanelOpen: false,
  contextMenu: {
    show: false,
    position: { x: 0, y: 0 },
    flowPosition: { x: 0, y: 0 },
  },
};

// =============================================================================
// Store Implementation (with localStorage persistence)
// =============================================================================

export const useWorkflowStore = create<WorkflowStore>()(
  persist(
    (set, get) => ({
      // Initial state
      chain: initialChain,
      nodeOutputs: {},
      execution: initialExecutionState,
      ui: initialUIState,

      // ========================================================================
      // Chain Actions
      // ========================================================================

      setChain: (chain) => {
        set({ chain });
      },

      addStep: (step) => {
        set((state) => ({
          chain: {
            ...state.chain,
            steps: [...state.chain.steps, step],
          },
        }));
      },

      updateStep: (stepId, updates) => {
        set((state) => ({
          chain: {
            ...state.chain,
            steps: state.chain.steps.map((step) =>
              step.id === stepId ? { ...step, ...updates } : step
            ),
          },
        }));
      },

      removeStep: (stepId) => {
        set((state) => ({
          chain: {
            ...state.chain,
            steps: state.chain.steps.filter((step) => step.id !== stepId),
          },
        }));
      },

      updateStepParameters: (stepId, parameters) => {
        set((state) => ({
          chain: {
            ...state.chain,
            steps: state.chain.steps.map((step) =>
              step.id === stepId
                ? { ...step, parameters: { ...step.parameters, ...parameters } }
                : step
            ),
          },
        }));
      },

      updateStepPosition: (stepId, position) => {
        set((state) => ({
          chain: {
            ...state.chain,
            steps: state.chain.steps.map((step) =>
              step.id === stepId ? { ...step, position } : step
            ),
          },
        }));
      },

      addDependency: (stepId, dependsOnId) => {
        set((state) => ({
          chain: {
            ...state.chain,
            steps: state.chain.steps.map((step) => {
              if (step.id !== stepId) return step;
              const depends_on = step.depends_on || [];
              if (depends_on.includes(dependsOnId)) return step;
              return { ...step, depends_on: [...depends_on, dependsOnId] };
            }),
          },
        }));
      },

      removeDependency: (stepId, dependsOnId) => {
        set((state) => ({
          chain: {
            ...state.chain,
            steps: state.chain.steps.map((step) => {
              if (step.id !== stepId) return step;
              return {
                ...step,
                depends_on: step.depends_on?.filter((id) => id !== dependsOnId),
              };
            }),
          },
        }));
      },

      getExecutableChain: () => {
        const { chain } = get();
        return {
          ...chain,
          steps: chain.steps.map((step) => {
            // Strip UI-only fields
            const { position, ...executableStep } = step;
            return executableStep;
          }),
        };
      },

      // ========================================================================
      // Output Actions
      // ========================================================================

      setNodeOutput: (stepId, output) => {
        set((state) => ({
          nodeOutputs: {
            ...state.nodeOutputs,
            [stepId]: {
              ...state.nodeOutputs[stepId],
              ...output,
            },
          },
        }));
      },

      setNodeStatus: (stepId, status) => {
        set((state) => ({
          nodeOutputs: {
            ...state.nodeOutputs,
            [stepId]: {
              ...state.nodeOutputs[stepId],
              status,
              ...(status === "running" && { startedAt: Date.now() }),
              ...(status === "completed" && { completedAt: Date.now() }),
            },
          },
        }));
      },

      clearNodeOutput: (stepId) => {
        set((state) => {
          const { [stepId]: _, ...rest } = state.nodeOutputs;
          return { nodeOutputs: rest };
        });
      },

      clearAllOutputs: () => {
        set({ nodeOutputs: {} });
      },

      // ========================================================================
      // Execution Actions
      // ========================================================================

      startExecution: (chainId, sseEndpoint) => {
        set({
          execution: {
            chainId,
            sseEndpoint,
            startedAt: Date.now(),
            status: "running",
          },
        });
      },

      setExecutionStatus: (status) => {
        set((state) => ({
          execution: {
            ...state.execution,
            status,
          },
        }));
      },

      completeExecution: (status) => {
        set((state) => ({
          execution: {
            ...state.execution,
            status,
          },
        }));
      },

      clearExecution: () => {
        set({
          execution: initialExecutionState,
        });
      },

      hasActiveExecution: () => {
        const { execution } = get();
        return execution.status === "running" && execution.chainId !== null;
      },

      // ========================================================================
      // UI Actions
      // ========================================================================

      selectNode: (nodeId) => {
        set((state) => ({
          ui: { ...state.ui, selectedNodeId: nodeId },
        }));
      },

      togglePanel: (open) => {
        set((state) => ({
          ui: { ...state.ui, isPanelOpen: open ?? !state.ui.isPanelOpen },
        }));
      },

      showContextMenu: (position, flowPosition) => {
        set((state) => ({
          ui: {
            ...state.ui,
            contextMenu: { show: true, position, flowPosition },
          },
        }));
      },

      hideContextMenu: () => {
        set((state) => ({
          ui: {
            ...state.ui,
            contextMenu: { ...state.ui.contextMenu, show: false },
          },
        }));
      },

      // ========================================================================
      // Workflow Actions
      // ========================================================================

      clearWorkflow: () => {
        set({
          chain: initialChain,
          nodeOutputs: {},
          execution: initialExecutionState,
          ui: initialUIState,
        });
      },
    }),
    {
      name: "comfyautomate-workflow",

      // Only persist these fields to localStorage
      partialize: (state) => ({
        chain: state.chain,
        execution: state.execution,
        // NOTE: nodeOutputs are NOT persisted - fetched from backend on reconnect
      }),
    }
  )
);

// =============================================================================
// Selectors (for optimized re-renders)
// =============================================================================

export const selectChain = (state: WorkflowStore) => state.chain;

export const selectSteps = (state: WorkflowStore) => state.chain.steps;

export const selectStep = (stepId: string) => (state: WorkflowStore) =>
  state.chain.steps.find((s) => s.id === stepId);

export const selectNodeOutput = (stepId: string) => (state: WorkflowStore) =>
  state.nodeOutputs[stepId];

export const selectSelectedNodeId = (state: WorkflowStore) =>
  state.ui.selectedNodeId;

export const selectExecution = (state: WorkflowStore) =>
  state.execution;

export const selectIsExecuting = (state: WorkflowStore) =>
  state.execution.status === "running";

export const selectContextMenu = (state: WorkflowStore) =>
  state.ui.contextMenu;

// =============================================================================
// SSE Reconnection Helper
// =============================================================================

/**
 * Call this on app mount to check for and reconnect to active executions
 */
export async function reconnectToActiveExecution(): Promise<void> {
  const store = useWorkflowStore.getState();

  if (!store.hasActiveExecution()) {
    return;
  }

  const { chainId } = store.execution;

  try {
    // Fetch current execution status from backend
    const response = await fetch(`http://localhost:8001/chains/${chainId}/status`);

    if (!response.ok) {
      // Execution no longer exists, clear state
      store.clearExecution();
      return;
    }

    const status = await response.json();

    // Update node outputs from backend state
    if (status.nodes) {
      for (const [stepId, nodeState] of Object.entries(status.nodes)) {
        store.setNodeOutput(stepId, nodeState as NodeOutput);
      }
    }

    // If still running, reconnect to SSE
    if (status.status === "running" && store.execution.sseEndpoint) {
      console.log("Active execution found, ready to reconnect to SSE");
    } else {
      // Execution completed while we were away
      store.completeExecution(status.status);
    }
  } catch (error) {
    console.error("Failed to reconnect to execution:", error);
    store.clearExecution();
  }
}
