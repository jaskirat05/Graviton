/**
 * Server Store - Available ComfyUI servers and validation
 */

import { create } from "zustand";

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:8001";

// =============================================================================
// Types
// =============================================================================

export interface ServerInfo {
  id: string;
  name: string;
  provider: string;
  address: string;
  port: number | null;
  ssl: boolean;
  status: string;
  tags: Record<string, unknown>;
  weight: number;
}

export interface CreateServerRequest {
  name: string;
  provider?: string;
  address: string;
  port?: number;
  ssl?: boolean;
  tags?: Record<string, unknown>;
  weight?: number;
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

export type DataPlaneMode = "local" | "orchestrator" | "s3" | "cloudinary";
export interface ServerHealth {
  server_id: string;
  health_state: string;
  reason: string;
  last_seen_at: string | null;
}

export interface WorkerControlSecretResponse {
  server_id: string;
  server_name: string;
  worker_id: string;
  secret_version: number;
  shared_secret: string;
  created_at: string;
  rotated_at: string | null;
}

export interface CreateServerResult {
  server: ServerInfo;
  controlSecret?: WorkerControlSecretResponse;
  controlSecretError?: string;
}

export interface ServerControlPlaneStatus {
  server_id: string;
  server_name: string;
  desired_hash: string;
  observed_hash: string | null;
  desired_mode: string | null;
  observed_mode: string | null;
  is_outdated: boolean;
  reachable: boolean;
  error: string | null;
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
  createServer: (payload: CreateServerRequest) => Promise<CreateServerResult>;
  syncServerWorkflows: (serverId: string, force?: boolean) => Promise<void>;
  syncServerObjectInfo: (serverId: string) => Promise<void>;
  setDataPlaneMode: (mode: DataPlaneMode) => Promise<void>;
  syncDataPlaneConfig: (force?: boolean) => Promise<void>;
  syncServerDataPlaneConfig: (serverId: string, force?: boolean) => Promise<void>;
  fetchServerHealth: (serverId: string) => Promise<ServerHealth>;
  fetchServerControlPlaneStatus: (serverId: string) => Promise<ServerControlPlaneStatus>;
  deleteServer: (serverId: string) => Promise<void>;
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
      const response = await fetch(`${GATEWAY_URL}/api/registry/v1/servers`);
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

  createServer: async (payload: CreateServerRequest) => {
    set({ error: null });

    const response = await fetch(`${GATEWAY_URL}/api/registry/v1/servers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: "comfyui",
        ssl: false,
        tags: {},
        weight: 1,
        ...payload,
      }),
    });

    if (!response.ok) {
      let detail = response.statusText;
      try {
        const errorBody = await response.json();
        if (typeof errorBody?.detail === "string") {
          detail = errorBody.detail;
        }
      } catch {
        // Keep fallback statusText when response body is not JSON.
      }
      const message = `Failed to create server: ${detail}`;
      set({ error: message });
      throw new Error(message);
    }

    const created: ServerInfo = await response.json();
    let controlSecret: WorkerControlSecretResponse | undefined;
    let controlSecretError: string | undefined;
    try {
      const secretResponse = await fetch(
        `${GATEWAY_URL}/api/registry/v1/servers/${encodeURIComponent(created.id)}/control-secret`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ rotate: false }),
        }
      );
      if (!secretResponse.ok) {
        let detail = secretResponse.statusText;
        try {
          const errorBody = await secretResponse.json();
          if (typeof errorBody?.detail === "string") {
            detail = errorBody.detail;
          }
        } catch {
          // Keep fallback statusText.
        }
        controlSecretError = detail;
      } else {
        controlSecret = await secretResponse.json();
      }
    } catch (error) {
      controlSecretError = error instanceof Error ? error.message : "Unknown secret registration error";
    }
    await get().fetchServers();
    return {
      server: created,
      controlSecret,
      controlSecretError,
    };
  },

  syncServerWorkflows: async (serverId: string, force = false) => {
    set({ error: null });
    const query = force ? "?force=true" : "";
    const response = await fetch(
      `${GATEWAY_URL}/api/registry/v1/servers/${encodeURIComponent(serverId)}:sync-workflows${query}`,
      { method: "POST" }
    );
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const errorBody = await response.json();
        if (typeof errorBody?.detail === "string") {
          detail = errorBody.detail;
        }
      } catch {
        // Keep fallback statusText.
      }
      const message = `Failed to sync workflows: ${detail}`;
      set({ error: message });
      throw new Error(message);
    }
  },

  syncServerObjectInfo: async (serverId: string) => {
    set({ error: null });
    const response = await fetch(
      `${GATEWAY_URL}/api/registry/v1/servers/${encodeURIComponent(serverId)}:sync-object-info`,
      { method: "POST" }
    );
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const errorBody = await response.json();
        if (typeof errorBody?.detail === "string") {
          detail = errorBody.detail;
        }
      } catch {
        // Keep fallback statusText.
      }
      const message = `Failed to sync object info: ${detail}`;
      set({ error: message });
      throw new Error(message);
    }
  },

  setDataPlaneMode: async (mode: DataPlaneMode) => {
    set({ error: null });
    const response = await fetch(`${GATEWAY_URL}/api/registry/v1/dataplane/mode`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const errorBody = await response.json();
        if (typeof errorBody?.detail === "string") {
          detail = errorBody.detail;
        }
      } catch {
        // Keep fallback statusText.
      }
      const message = `Failed to set data plane mode: ${detail}`;
      set({ error: message });
      throw new Error(message);
    }
  },

  syncDataPlaneConfig: async (force = true) => {
    set({ error: null });
    const response = await fetch(`${GATEWAY_URL}/api/registry/v1/control-plane/sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force }),
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const errorBody = await response.json();
        if (typeof errorBody?.detail === "string") {
          detail = errorBody.detail;
        }
      } catch {
        // Keep fallback statusText.
      }
      const message = `Failed to sync data plane config: ${detail}`;
      set({ error: message });
      throw new Error(message);
    }
  },

  syncServerDataPlaneConfig: async (serverId: string, force = true) => {
    set({ error: null });
    const response = await fetch(
      `${GATEWAY_URL}/api/registry/v1/servers/${encodeURIComponent(serverId)}:sync-dataplane`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force }),
      }
    );
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const errorBody = await response.json();
        if (typeof errorBody?.detail === "string") {
          detail = errorBody.detail;
        }
      } catch {
        // Keep fallback statusText.
      }
      const message = `Failed to sync server data plane config: ${detail}`;
      set({ error: message });
      throw new Error(message);
    }
  },

  fetchServerHealth: async (serverId: string) => {
    set({ error: null });
    const response = await fetch(
      `${GATEWAY_URL}/api/registry/v1/servers/${encodeURIComponent(serverId)}/health`
    );
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const errorBody = await response.json();
        if (typeof errorBody?.detail === "string") {
          detail = errorBody.detail;
        }
      } catch {
        // Keep fallback statusText.
      }
      const message = `Failed to fetch server health: ${detail}`;
      set({ error: message });
      throw new Error(message);
    }
    const health: ServerHealth = await response.json();
    return health;
  },

  fetchServerControlPlaneStatus: async (serverId: string) => {
    set({ error: null });
    const response = await fetch(
      `${GATEWAY_URL}/api/registry/v1/servers/${encodeURIComponent(serverId)}/control-plane-status`
    );
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const errorBody = await response.json();
        if (typeof errorBody?.detail === "string") {
          detail = errorBody.detail;
        }
      } catch {
        // Keep fallback statusText.
      }
      const message = `Failed to fetch server control-plane status: ${detail}`;
      set({ error: message });
      throw new Error(message);
    }
    const status: ServerControlPlaneStatus = await response.json();
    return status;
  },

  deleteServer: async (serverId: string) => {
    set({ error: null });
    const response = await fetch(
      `${GATEWAY_URL}/api/registry/v1/servers/${encodeURIComponent(serverId)}`,
      { method: "DELETE" }
    );
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const errorBody = await response.json();
        if (typeof errorBody?.detail === "string") {
          detail = errorBody.detail;
        }
      } catch {
        // Keep fallback statusText.
      }
      const message = `Failed to delete server: ${detail}`;
      set({ error: message });
      throw new Error(message);
    }
    await get().fetchServers();
  },

  validateWorkflowServer: async (workflowName: string, serverName: string) => {
    // Check cache first
    const cached = get().validationCache[workflowName]?.[serverName];
    if (cached) {
      return cached;
    }

    try {
      const response = await fetch(`${GATEWAY_URL}/api/registry/v1/workflows/validate-server`, {
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
    } catch {
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
