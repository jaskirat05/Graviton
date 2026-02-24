/**
 * Chain Store - Manages chains, versions, and artifacts
 */

import { create } from "zustand";

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:8001";

// =============================================================================
// Types
// =============================================================================

export interface ChainName {
  name: string;
  run_count: number;
  latest_version: number;
  last_run: string | null;
}

export interface ChainVersion {
  id: string;
  version: number;
  definition_hash?: string | null;
  status: "running" | "completed" | "failed" | "starting" | "cancelled";
  job_id: string;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
}

export interface Artifact {
  id: string;
  filename: string;
  file_type: "image" | "video" | "audio" | "unknown";
  file_format: string;
  file_size: number;
  created_at: string | null;
  url: string;
}

export interface ChainStep {
  step_id: string;
  workflow_name: string;
  status: string;
  error_message: string | null;
  artifacts: Artifact[];
}

export interface ChainArtifacts {
  chain_id: string;
  chain_name: string;
  version: number;
  status: string;
  error_message: string | null;
  steps: ChainStep[];
}

export interface ChainDefinitionResponse {
  chain_id: string;
  chain_name: string;
  version: number;
  definition_hash?: string | null;
  definition: Record<string, unknown>;
  executed_definition: Record<string, unknown> | null;
}

// =============================================================================
// Store
// =============================================================================

interface ChainStore {
  // Data
  chainNames: ChainName[];
  selectedChainName: string | null;
  chainVersions: ChainVersion[];
  selectedVersionId: string | null;
  chainArtifacts: ChainArtifacts | null;

  // Current editor chain name
  currentChainName: string;

  // UI state
  isLoading: boolean;
  isLoadingVersions: boolean;
  isLoadingArtifacts: boolean;
  error: string | null;
  sidebarOpen: boolean;

  // Actions
  fetchChainNames: () => Promise<void>;
  selectChain: (chainName: string) => Promise<void>;
  selectVersion: (chainId: string) => Promise<void>;
  fetchChainDefinition: (chainId: string) => Promise<ChainDefinitionResponse | null>;
  deleteChain: (chainId: string) => Promise<boolean>;
  clearSelection: () => void;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;

  // Editor chain name actions
  setCurrentChainName: (name: string) => void;
  createNewChain: (name: string) => void;
}

export const useChainStore = create<ChainStore>((set, get) => ({
  // Initial state
  chainNames: [],
  selectedChainName: null,
  chainVersions: [],
  selectedVersionId: null,
  chainArtifacts: null,
  currentChainName: "Untitled Chain",
  isLoading: false,
  isLoadingVersions: false,
  isLoadingArtifacts: false,
  error: null,
  sidebarOpen: true,

  // Fetch unique chain names
  fetchChainNames: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await fetch(`${GATEWAY_URL}/chains/names`);
      if (!response.ok) throw new Error("Failed to fetch chains");

      const data = await response.json();
      set({ chainNames: data.chain_names, isLoading: false });
    } catch (e) {
      set({
        error: e instanceof Error ? e.message : "Failed to fetch chains",
        isLoading: false,
      });
    }
  },

  // Select a chain name and fetch its versions
  selectChain: async (chainName: string) => {
    set({
      selectedChainName: chainName,
      selectedVersionId: null,
      chainArtifacts: null,
      isLoadingVersions: true,
      error: null,
    });

    try {
      const response = await fetch(
        `${GATEWAY_URL}/chains/by-name/${encodeURIComponent(chainName)}`
      );
      if (!response.ok) throw new Error("Failed to fetch chain versions");

      const data = await response.json();
      set({ chainVersions: data.versions, isLoadingVersions: false });
    } catch (e) {
      set({
        error: e instanceof Error ? e.message : "Failed to fetch versions",
        isLoadingVersions: false,
      });
    }
  },

  // Select a version and fetch its artifacts
  selectVersion: async (chainId: string) => {
    set({
      selectedVersionId: chainId,
      isLoadingArtifacts: true,
      error: null,
    });

    try {
      const response = await fetch(`${GATEWAY_URL}/chains/${chainId}/artifacts`);
      if (!response.ok) throw new Error("Failed to fetch artifacts");

      const data = await response.json();

      // Fix artifact URLs - prepend gateway URL if relative
      if (data.steps) {
        for (const step of data.steps) {
          if (step.artifacts) {
            for (const artifact of step.artifacts) {
              if (artifact.url && artifact.url.startsWith("/")) {
                artifact.url = `${GATEWAY_URL}${artifact.url}`;
              }
            }
          }
        }
      }

      set({ chainArtifacts: data, isLoadingArtifacts: false });
    } catch (e) {
      set({
        error: e instanceof Error ? e.message : "Failed to fetch artifacts",
        isLoadingArtifacts: false,
      });
    }
  },

  // Fetch chain definition for loading into editor
  fetchChainDefinition: async (chainId: string) => {
    try {
      const response = await fetch(`${GATEWAY_URL}/chains/${chainId}/definition`);
      if (!response.ok) {
        if (response.status === 404) {
          set({ error: "Chain definition not found" });
          return null;
        }
        throw new Error("Failed to fetch chain definition");
      }

      const data = await response.json();
      return data as ChainDefinitionResponse;
    } catch (e) {
      set({
        error: e instanceof Error ? e.message : "Failed to fetch chain definition",
      });
      return null;
    }
  },

  // Delete a chain version
  deleteChain: async (chainId: string) => {
    try {
      const response = await fetch(`${GATEWAY_URL}/chains/${chainId}`, {
        method: "DELETE",
      });

      if (!response.ok) throw new Error("Failed to delete chain");

      // Refresh the versions list
      const { chainVersions } = get();
      const newVersions = chainVersions.filter((v) => v.id !== chainId);
      set({ chainVersions: newVersions });

      // If no more versions, refresh chain names
      if (newVersions.length === 0) {
        get().fetchChainNames();
        set({ selectedChainName: null, chainArtifacts: null });
      }

      // Clear artifacts if deleted version was selected
      if (get().selectedVersionId === chainId) {
        set({ selectedVersionId: null, chainArtifacts: null });
      }

      return true;
    } catch (e) {
      set({
        error: e instanceof Error ? e.message : "Failed to delete chain",
      });
      return false;
    }
  },

  // Clear selection
  clearSelection: () => {
    set({
      selectedChainName: null,
      chainVersions: [],
      selectedVersionId: null,
      chainArtifacts: null,
    });
  },

  // Toggle sidebar
  toggleSidebar: () => {
    set((state) => ({ sidebarOpen: !state.sidebarOpen }));
  },

  setSidebarOpen: (open: boolean) => {
    set({ sidebarOpen: open });
  },

  setCurrentChainName: (name: string) => {
    set({ currentChainName: name });
  },

  createNewChain: (name: string) => {
    set({
      currentChainName: name,
      selectedChainName: null,
      selectedVersionId: null,
      chainArtifacts: null,
      chainVersions: [],
    });
  },
}));
