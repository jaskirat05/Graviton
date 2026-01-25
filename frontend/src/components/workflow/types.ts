/**
 * Workflow Types - Node and edge definitions for the visual editor
 */

import type { Node, Edge } from "@xyflow/react";

// =============================================================================
// Base Types
// =============================================================================

export type NodeCategory = "image" | "video" | "utility";

// Explicit socket types
export type InputSocketType = "image" | "video" | "any";
export type OutputSocketType = "image" | "video" | "any";

// Input parameter types (form controls)
export type InputParameterType = "text" | "number" | "select" | "textarea";

// =============================================================================
// Socket Definitions (Connection Handles)
// =============================================================================

/**
 * Input Socket - Left side handle that receives data from other nodes
 */
export interface InputSocketDefinition {
  id: string;
  label: string;
  type: InputSocketType;
}

/**
 * Output Socket - Right side handle that sends data to other nodes
 */
export interface OutputSocketDefinition {
  id: string;
  label: string;
  type: OutputSocketType;
}

// =============================================================================
// Input Parameter Definition (Form Controls)
// =============================================================================

/**
 * Input Parameter - A form control on the node (text input, dropdown, etc.)
 */
export interface InputParameterDefinition {
  id: string;
  type: InputParameterType;
  label: string;
  default?: string | number;
  options?: { label: string; value: string }[];
  placeholder?: string;
}

// =============================================================================
// Base Node Definition - One per workflow
// =============================================================================

/**
 * Base Node Definition - Each workflow is its own node type
 */
export interface BaseNodeDefinition {
  // Identity - type is the workflow_name
  readonly type: string;
  readonly label: string;
  readonly description: string;

  // Appearance
  readonly category: NodeCategory;
  readonly color: string;

  // Grouping for context menu (e.g., "Image Generate" groups flux_dev, sdxl)
  readonly group?: string;

  // Sockets (connection handles) - fixed per workflow
  readonly inputs: InputSocketDefinition[];
  readonly outputs: OutputSocketDefinition[];

  // Input parameters (form controls on the node) - fixed per workflow
  readonly inputParameters: InputParameterDefinition[];
}

// =============================================================================
// Runtime Types - Used by ReactFlow
// =============================================================================

/**
 * Data stored in each ReactFlow node instance
 */
export interface WorkflowNodeData {
  type: string;        // workflow_name (e.g., "flux_dev")
  label: string;       // display label (e.g., "Flux Dev")
  color: string;
  parameters: Record<string, string | number>;
  definition: BaseNodeDefinition;
  server?: string;     // Optional server name to execute on
  serverValidation?: {  // Validation result for selected server
    valid: boolean;
    error?: string;
  };
}

/**
 * ReactFlow node with our custom data
 * (& Record<string, unknown> satisfies ReactFlow's loose typing requirement)
 */
export type WorkflowNode = Node<WorkflowNodeData & Record<string, unknown>>;

/**
 * ReactFlow edge
 */
export type WorkflowEdge = Edge;

// =============================================================================
// Chain Export Types - Match the backend format
// =============================================================================

export interface ChainStep {
  id: string;
  workflow: string;
  depends_on?: string[];
  requires_approval?: boolean;
  parameters: Record<string, unknown>;
  server?: string;  // Optional server name to execute on

  // UI-only field (stripped before sending to backend)
  position?: { x: number; y: number };
}

export interface ChainDefinition {
  name: string;
  description: string;
  steps: ChainStep[];
}
