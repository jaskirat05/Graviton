/**
 * Chain Import/Export Utilities
 * Convert between ReactFlow state and chain definitions
 */

import type {
  WorkflowNode,
  WorkflowEdge,
  WorkflowNodeData,
  ChainDefinition,
  ChainStep,
} from "./types";
import type { useNodeStore } from "@/stores/nodeStore";

// =============================================================================
// Helpers
// =============================================================================

/**
 * Sanitize a string for use as a step ID
 * Step IDs must be alphanumeric with underscores or hyphens only
 */
export function sanitizeStepId(name: string): string {
  return name
    .replace(/[()]/g, '')           // Remove parentheses
    .replace(/\s+/g, '_')           // Replace spaces with underscores
    .replace(/[^a-zA-Z0-9_-]/g, '') // Remove any other invalid chars
    .replace(/_+/g, '_')            // Collapse multiple underscores
    .replace(/^_|_$/g, '');         // Trim leading/trailing underscores
}

// =============================================================================
// Export: ReactFlow State -> Chain Definition
// =============================================================================

export function toChainDefinition(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  chainName: string = "chain-from-editor",
  chainDescription: string = "Chain created in visual editor"
): ChainDefinition {
  const steps: ChainStep[] = nodes.map((node) => {
    const data = node.data as WorkflowNodeData;

    // Find incoming edges (connections to this node's inputs)
    const incomingEdges = edges.filter((e) => e.target === node.id);

    // Get dependencies (unique source node IDs)
    const dependencies = [
      ...new Set(incomingEdges.map((e) => e.source)),
    ];

    // Build parameters - start with node's parameter values
    const parameters: Record<string, unknown> = { ...data.parameters };

    // Add input mappings from connections
    // e.g., "78.image": "{{ source_node_id.output.image }}"
    for (const edge of incomingEdges) {
      const targetHandle = edge.targetHandle || "input";
      const sourceHandle = edge.sourceHandle || "output";
      parameters[targetHandle] = `{{ ${edge.source}.output.${sourceHandle} }}`;
    }

    return {
      id: node.id,
      workflow: data.type, // type IS the workflow name
      ...(dependencies.length > 0 && { depends_on: dependencies }),
      parameters,
      ...(data.server && { server: data.server }), // Include server if specified
      position: { x: node.position.x, y: node.position.y },
    };
  });

  return {
    name: chainName,
    description: chainDescription,
    steps,
  };
}

// =============================================================================
// Import: Chain Definition -> ReactFlow State
// =============================================================================

// Regex to match {{ step_id.output.socket_name }}
const REFERENCE_REGEX = /\{\{\s*([\w-]+)\.output\.(\w+)\s*\}\}/;

interface ImportResult {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  errors: string[];
}

export function fromChainDefinition(
  chain: ChainDefinition,
  nodeStore: ReturnType<typeof useNodeStore>
): ImportResult {
  const nodes: WorkflowNode[] = [];
  const edges: WorkflowEdge[] = [];
  const errors: string[] = [];

  const { getNodeDefinition } = nodeStore;

  // Auto-layout: position nodes in a grid if no positions saved
  const AUTO_SPACING_X = 300;
  const AUTO_SPACING_Y = 200;
  const NODES_PER_ROW = 3;

  for (let i = 0; i < chain.steps.length; i++) {
    const step = chain.steps[i];

    // workflow name IS the node type now
    const definition = getNodeDefinition(step.workflow);
    if (!definition) {
      errors.push(`Unknown workflow: ${step.workflow}`);
      continue;
    }

    // Calculate position
    const position = step.position || {
      x: 100 + (i % NODES_PER_ROW) * AUTO_SPACING_X,
      y: 100 + Math.floor(i / NODES_PER_ROW) * AUTO_SPACING_Y,
    };

    // Extract non-reference parameters (actual values)
    const parameters: Record<string, string | number> = {};

    for (const [key, value] of Object.entries(step.parameters)) {
      if (typeof value === "string" && REFERENCE_REGEX.test(value)) {
        // This is a reference - will create an edge instead
        const match = value.match(REFERENCE_REGEX);
        if (match) {
          const [, sourceStepId, sourceSocket] = match;
          edges.push({
            id: `${sourceStepId}-${sourceSocket}-${step.id}-${key}`,
            source: sourceStepId,
            sourceHandle: sourceSocket,
            target: step.id,
            targetHandle: key,
            type: "workflow",
          });
        }
      } else {
        // Regular parameter value
        parameters[key] = value as string | number;
      }
    }

    // Create the node
    const node: WorkflowNode = {
      id: step.id,
      type: "workflow",
      position,
      data: {
        type: step.workflow, // workflow name is the type
        label: definition.label,
        color: definition.color,
        parameters,
        definition,
        ...(step.server && { server: step.server }), // Include server if specified
      },
    };

    nodes.push(node);
  }

  return { nodes, edges, errors };
}
