/**
 * Node Store - Workflow definitions from backend
 * Each workflow is its own node type, grouped by category for the UI
 */

import { create } from "zustand";
import type {
  BaseNodeDefinition,
  InputParameterDefinition,
  InputSocketDefinition,
  OutputSocketDefinition,
  NodeCategory,
  WorkflowStructureMetadata,
  SubgraphPairGroup,
} from "@/components/workflow/types";

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:8001";
const NODE_STRUCTURE_CACHE_KEY = "graviton.node-structure-cache.v1";

// =============================================================================
// Backend Response Types
// =============================================================================

interface BackendSocketDefinition {
  id: string;
  type: "image" | "video" | "text" | "audio" | "3d" | "file" | "any";
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
  workflow_hash?: string;
  nodeType: string;
  label: string;
  color: string;
  category: "image" | "video" | "utility" | "invalid";
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
      if (p.category === "bridge_input") return false;
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

function parseParameterId(id: string): { nodeId: string; inputKey: string; instanceKey: string; innerNodeId: string } | null {
  const idx = id.lastIndexOf(".");
  if (idx <= 0 || idx >= id.length - 1) return null;
  const nodeId = id.slice(0, idx);
  const inputKey = id.slice(idx + 1);
  const colon = nodeId.indexOf(":");
  const instanceKey = colon >= 0 ? nodeId.slice(0, colon) : "main";
  const innerNodeId = colon >= 0 ? nodeId.slice(colon + 1) : nodeId;
  return { nodeId, inputKey, instanceKey, innerNodeId };
}

function isPromptLike(param: InputParameterDefinition): boolean {
  const parsed = parseParameterId(param.id);
  const inputKey = (parsed?.inputKey || param.id).toLowerCase();
  const haystack = `${param.label} ${inputKey} ${param.id}`.toLowerCase();
  return (
    haystack.includes("prompt") ||
    inputKey === "text" ||
    haystack.includes("positive") ||
    haystack.includes("negative")
  );
}

function sortStrings(values: Iterable<string>): string[] {
  return Array.from(values).sort((a, b) => a.localeCompare(b));
}

function hashFNV1a(input: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i);
    hash += (hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24);
  }
  return `fnv1a:${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

function computeStructureHash(workflow: BackendWorkflowDefinition): string {
  const normalized = {
    workflow_name: workflow.workflow_name,
    nodeType: workflow.nodeType,
    inputSockets: workflow.inputSockets
      .map((s) => ({ id: s.id, type: s.type, label: s.label }))
      .sort((a, b) => `${a.id}:${a.type}:${a.label}`.localeCompare(`${b.id}:${b.type}:${b.label}`)),
    outputSockets: workflow.outputSockets
      .map((s) => ({ id: s.id, type: s.type, label: s.label }))
      .sort((a, b) => `${a.id}:${a.type}:${a.label}`.localeCompare(`${b.id}:${b.type}:${b.label}`)),
    parameters: workflow.parameters
      .map((p) => ({
        key: p.key,
        input_key: p.input_key,
        type: p.type,
        category: p.category,
      }))
      .sort((a, b) =>
        `${a.key}:${a.input_key}:${a.type}:${a.category}`.localeCompare(
          `${b.key}:${b.input_key}:${b.type}:${b.category}`
        )
      ),
  };
  return hashFNV1a(JSON.stringify(normalized));
}

function buildSubgraphPairs(inputParameters: InputParameterDefinition[]): SubgraphPairGroup[] {
  const byInstance = new Map<string, Set<string>>();
  for (const param of inputParameters) {
    const parsed = parseParameterId(param.id);
    if (!parsed) continue;
    if (!byInstance.has(parsed.instanceKey)) byInstance.set(parsed.instanceKey, new Set<string>());
    byInstance.get(parsed.instanceKey)!.add(`${parsed.innerNodeId}.${parsed.inputKey}`);
  }

  const signatureToInstances = new Map<string, string[]>();
  for (const [instanceKey, signatures] of byInstance.entries()) {
    if (instanceKey === "main") continue;
    const signature = sortStrings(signatures).join("|");
    if (!signatureToInstances.has(signature)) signatureToInstances.set(signature, []);
    signatureToInstances.get(signature)!.push(instanceKey);
  }

  const pairs: SubgraphPairGroup[] = [];
  let index = 1;
  for (const instances of signatureToInstances.values()) {
    if (instances.length < 2) continue;
    const sortedInstances = instances.sort((a, b) => {
      const an = Number(a);
      const bn = Number(b);
      if (!Number.isNaN(an) && !Number.isNaN(bn)) return an - bn;
      return a.localeCompare(b);
    });
    pairs.push({
      key: `pair_${index}`,
      instances: sortedInstances,
    });
    index += 1;
  }

  return pairs;
}

function buildStructureMetadata(
  inputParameters: InputParameterDefinition[],
  structureHash: string
): WorkflowStructureMetadata {
  const instanceSet = new Set<string>(["main"]);
  const promptParameterIds: string[] = [];

  for (const param of inputParameters) {
    const parsed = parseParameterId(param.id);
    if (parsed) instanceSet.add(parsed.instanceKey);
    if (isPromptLike(param)) promptParameterIds.push(param.id);
  }

  return {
    structureHash,
    subgraphInstances: sortStrings(instanceSet),
    subgraphPairs: buildSubgraphPairs(inputParameters),
    promptParameterIds: sortStrings(promptParameterIds),
  };
}

interface StructureCacheEntry {
  workflowHash?: string;
  structureHash: string;
  metadata: WorkflowStructureMetadata;
}

type StructureCache = Record<string, StructureCacheEntry>;

function loadStructureCache(): StructureCache {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(NODE_STRUCTURE_CACHE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as StructureCache;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveStructureCache(cache: StructureCache): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(NODE_STRUCTURE_CACHE_KEY, JSON.stringify(cache));
  } catch {
    // Ignore storage failures, cache can always be recomputed.
  }
}

// =============================================================================
// Store
// =============================================================================

export interface NodeStore {
  // All node definitions (one per workflow)
  nodeDefinitions: BaseNodeDefinition[];
  isLoading: boolean;
  error: string | null;

  fetchWorkflows: () => Promise<void>;
  getNodeDefinition: (workflow: string) => BaseNodeDefinition | undefined;
  getStructureMetadata: (workflow: string) => WorkflowStructureMetadata | undefined;
  getNodesByCategory: () => Record<NodeCategory, Record<string, BaseNodeDefinition[]>>;
}

export const useNodeStore = create<NodeStore>((set, get) => ({
  nodeDefinitions: [],
  isLoading: false,
  error: null,

  fetchWorkflows: async () => {
    set({ isLoading: true, error: null });

    try {
      const response = await fetch(`${GATEWAY_URL}/api/registry/v1/node-definitions`, {
        cache: "no-store",
      });
      if (!response.ok) throw new Error(response.statusText);

      const workflows: BackendWorkflowDefinition[] = await response.json();
      const cache = loadStructureCache();
      const nextCache: StructureCache = {};

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
        const structureHash = computeStructureHash(w);
        const cached = cache[w.workflow_name];
        const structureMetadata =
          cached && cached.structureHash === structureHash
            ? cached.metadata
            : buildStructureMetadata(inputParameters, structureHash);

        nextCache[w.workflow_name] = {
          workflowHash: w.workflow_hash,
          structureHash,
          metadata: structureMetadata,
        };

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
          workflowHash: w.workflow_hash,
          structureMetadata,
        };
      });

      saveStructureCache(nextCache);

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

  getStructureMetadata: (workflow) =>
    get().nodeDefinitions.find((n) => n.type === workflow)?.structureMetadata,

  // Group nodes by category, then by group (nodeType label)
  // Returns: { image: { "Image Generate": [node1, node2], "Image Edit": [node3] }, ... }
  getNodesByCategory: () => {
    const result: Record<NodeCategory, Record<string, BaseNodeDefinition[]>> = {
      image: {},
      video: {},
      utility: {},
      invalid: {},
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
