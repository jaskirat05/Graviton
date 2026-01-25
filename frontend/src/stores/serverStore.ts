/**
 * Server Store - Available ComfyUI servers and validation
 */

import { create } from "zustand";

// =============================================================================
// Types
// =============================================================================

export interface ServerInfo {
  name: string;
  url: string;
  node_count: number;
  template_count: number;
  last_sync: string | null;
  sync_error: string | null;
}

export interface ValidationResult {
  valid: boolean;
  workflow_name: string;
  server_name: string;
  already_validated: boolean;
  missing_nodes?: string[];
  invalid_inputs?: {
    node_id: string;
    class_type: string;
    input_name: string;
    value: string;
    available_count: number;
  }[];
}

// =============================================================================
// Store
// =============================================================================

interface ServerStore {
  servers: ServerInfo[];
  isLoading: boolean;
  error: string | null;

  // Validation cache: workflow_name -> server_name -> result
  validationCache: Record<string, Record<string, ValidationResult>>;

  fetchServers: () => Promise<void>;
  validateWorkflowServer: (workflowName: string, serverName: string) => Promise<ValidationResult>;
  getValidation: (workflowName: string, serverName: string) => ValidationResult | undefined;
}

export const useServerStore = create<ServerStore>((set, get) => ({
  servers: [],
  isLoading: false,
  error: null,
  validationCache: {},

  fetchServers: async () => {
    set({ isLoading: true, error: null });

    try {
      const response = await fetch("http://localhost:8001/servers");
      if (!response.ok) throw new Error(response.statusText);

      const data = await response.json();
      set({
        servers: data.servers,
        isLoading: false,
      });
    } catch (error) {
      set({ error: String(error), isLoading: false });
    }
  },

  validateWorkflowServer: async (workflowName: string, serverName: string) => {
    // Check cache first
    const cached = get().validationCache[workflowName]?.[serverName];
    if (cached) {
      return cached;
    }

    try {
      const response = await fetch("http://localhost:8001/workflows/validate-server", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workflow_name: workflowName,
          server_name: serverName,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || response.statusText);
      }

      const result: ValidationResult = await response.json();

      // Cache the result
      set((state) => ({
        validationCache: {
          ...state.validationCache,
          [workflowName]: {
            ...state.validationCache[workflowName],
            [serverName]: result,
          },
        },
      }));

      return result;
    } catch (error) {
      // Return error result
      const errorResult: ValidationResult = {
        valid: false,
        workflow_name: workflowName,
        server_name: serverName,
        already_validated: false,
        missing_nodes: [],
        invalid_inputs: [],
      };
      return errorResult;
    }
  },

  getValidation: (workflowName: string, serverName: string) => {
    return get().validationCache[workflowName]?.[serverName];
  },
}));
