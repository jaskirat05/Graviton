/**
 * Node Store - Workflow definitions from backend
 * Each workflow is its own node type, grouped by category for the UI
 */

import { create } from "zustand";
import type { BaseNodeDefinition, InputParameterDefinition, InputSocketDefinition, OutputSocketDefinition, NodeCategory } from "@/components/workflow/types";

// =============================================================================
// Backend Response Types
// =============================================================================

interface BackendSocketDefinition {
  id: string;
  type: "image" | "video" | "any";
  label: string;
}

interface BackendParameterDefinition {
  key: string;
  input_key: string;
  default_value: string | number | boolean;
  type: "str" | "int" | "float" | "bool";
  description: string;
  category: string;
}

export interface BackendWorkflowDefinition {
  workflow_name: string;
  nodeType: string;
  label: string;
  color: string;
  category: "image" | "video" | "utility";
  inputSockets: BackendSocketDefinition[];
  outputSockets: BackendSocketDefinition[];
  parameters: BackendParameterDefinition[];
}

// =============================================================================
// Helper: Convert nodeType to human-readable group label
// =============================================================================

function nodeTypeToLabel(nodeType: string): string {
  // "image_generate" -> "Image Generate"
  return nodeType
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

// =============================================================================
// Helper: Transform backend params to frontend InputParameterDefinition
// =============================================================================

function transformParameters(params: BackendParameterDefinition[]): InputParameterDefinition[] {
  return params
    .filter((p) => {
      const key = p.input_key.toLowerCase();
      return !key.includes("image") && !key.includes("video");
    })
    .map((p) => {
      // Determine control type
      let controlType: "text" | "number" | "textarea" | "select" = "text";
      if (p.type === "int" || p.type === "float") {
        controlType = "number";
      } else if (p.input_key === "text" || p.input_key === "prompt") {
        controlType = "textarea";
      }

      return {
        id: p.key, // Use full key (e.g., "6.text") as id
        type: controlType,
        label: p.description || p.input_key,
        default: p.default_value as string | number,
        placeholder: p.description,
      };
    });
}

// =============================================================================
// Store
// =============================================================================

interface NodeStore {
  // All node definitions (one per workflow)
  nodeDefinitions: BaseNodeDefinition[];
  isLoading: boolean;
  error: string | null;

  fetchWorkflows: () => Promise<void>;
  getNodeDefinition: (workflow: string) => BaseNodeDefinition | undefined;
  getNodesByCategory: () => Record<NodeCategory, Record<string, BaseNodeDefinition[]>>;
}

export const useNodeStore = create<NodeStore>((set, get) => ({
  nodeDefinitions: [],
  isLoading: false,
  error: null,

  fetchWorkflows: async () => {
    set({ isLoading: true, error: null });

    try {
      const response = await fetch("http://localhost:8001/node-definitions");
      if (!response.ok) throw new Error(response.statusText);

      const workflows: BackendWorkflowDefinition[] = await response.json();

      // Each workflow becomes its own node definition
      const nodeDefinitions: BaseNodeDefinition[] = workflows.map((w) => {
        const inputs: InputSocketDefinition[] = w.inputSockets.map((s) => ({
          id: s.id,
          label: s.label,
          type: s.type,
        }));

        const outputs: OutputSocketDefinition[] = w.outputSockets.map((s) => ({
          id: s.id,
          label: s.label,
          type: s.type,
        }));

        const inputParameters = transformParameters(w.parameters);

        return {
          type: w.workflow_name, // workflow_name is the node type
          label: w.label,
          description: `${w.category} workflow`,
          category: w.category as NodeCategory,
          color: w.color,
          group: nodeTypeToLabel(w.nodeType), // For menu grouping (e.g., "Image Generate")
          inputs,
          outputs,
          inputParameters,
        };
      });

      set({
        nodeDefinitions,
        isLoading: false,
      });
    } catch (error) {
      set({ error: String(error), isLoading: false });
    }
  },

  getNodeDefinition: (workflow) =>
    get().nodeDefinitions.find((n) => n.type === workflow),

  // Group nodes by category, then by group (nodeType label)
  // Returns: { image: { "Image Generate": [node1, node2], "Image Edit": [node3] }, ... }
  getNodesByCategory: () => {
    const result: Record<NodeCategory, Record<string, BaseNodeDefinition[]>> = {
      image: {},
      video: {},
      utility: {},
    };

    for (const node of get().nodeDefinitions) {
      const category = result[node.category];
      const group = node.group || "Other";

      if (!category[group]) {
        category[group] = [];
      }
      category[group].push(node);
    }

    return result;
  },
}));

// Selectors
export const selectNodeDefinitions = (state: NodeStore) => state.nodeDefinitions;
export const selectIsLoading = (state: NodeStore) => state.isLoading;
