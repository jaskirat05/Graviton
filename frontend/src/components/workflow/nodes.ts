/**
 * Node Registry - Definitions for all available node types
 */

import type { BaseNodeDefinition, NodeCategory } from "./types";

// Node definitions
export const nodeDefinitions: BaseNodeDefinition[] = [
  {
    type: "image_generate",
    label: "Image Generate",
    description: "Generate an image from a text prompt",
    category: "image",
    color: "#22c55e",
    inputs: [],
    outputs: [{ id: "image", label: "Image", type: "image" }],
    inputParameters: [
      {
        id: "prompt",
        type: "textarea",
        label: "Prompt",
        placeholder: "Describe the image...",
      },
      {
        id: "seed",
        type: "number",
        label: "Seed",
        default: -1,
      },
    ],
    workflows: [
      { label: "Flux", value: "flux_dev" },
      { label: "SDXL", value: "sdxl" },
    ],
  },
  {
    type: "image_edit",
    label: "Image Edit",
    description: "Edit an image with a text prompt",
    category: "image",
    color: "#f59e0b",
    inputs: [{ id: "image", label: "Image", type: "image" }],
    outputs: [{ id: "image", label: "Image", type: "image" }],
    inputParameters: [
      {
        id: "prompt",
        type: "textarea",
        label: "Prompt",
        placeholder: "Describe the edit...",
      },
      {
        id: "strength",
        type: "number",
        label: "Strength",
        default: 0.75,
      },
    ],
    workflows: [
      { label: "Flux Redux", value: "flux_redux" },
      { label: "IP Adapter", value: "ip_adapter" },
    ],
  },
  {
    type: "image_to_video",
    label: "Image to Video",
    description: "Animate an image into a video",
    category: "video",
    color: "#3b82f6",
    inputs: [{ id: "image", label: "Image", type: "image" }],
    outputs: [{ id: "video", label: "Video", type: "video" }],
    inputParameters: [
      {
        id: "prompt",
        type: "textarea",
        label: "Motion Prompt",
        placeholder: "Describe the motion...",
      },
      {
        id: "frames",
        type: "number",
        label: "Frames",
        default: 24,
      },
    ],
    workflows: [
      { label: "Wan I2V", value: "wan_i2v" },
      { label: "SVD", value: "svd" },
    ],
  },
  {
    type: "video_generate",
    label: "Video Generate",
    description: "Generate a video from text",
    category: "video",
    color: "#8b5cf6",
    inputs: [],
    outputs: [{ id: "video", label: "Video", type: "video" }],
    inputParameters: [
      {
        id: "prompt",
        type: "textarea",
        label: "Prompt",
        placeholder: "Describe the video...",
      },
      {
        id: "frames",
        type: "number",
        label: "Frames",
        default: 24,
      },
    ],
    workflows: [{ label: "Wan T2V", value: "wan_t2v" }],
  },
];

// =============================================================================
// Workflow → NodeType lookup (O(1) via pre-built index)
// =============================================================================

const workflowToNodeType = new Map<string, string>();

for (const def of nodeDefinitions) {
  for (const w of def.workflows) {
    workflowToNodeType.set(w.value, def.type);
  }
}

/** Get node type from workflow ID (O(1) lookup) */
export function getNodeTypeFromWorkflow(workflow: string): string | undefined {
  return workflowToNodeType.get(workflow);
}

// Get node definition by type
export function getNodeDefinition(type: string): BaseNodeDefinition | undefined {
  return nodeDefinitions.find((n) => n.type === type);
}

// Get nodes grouped by category
export function getNodesByCategory(): Record<NodeCategory, BaseNodeDefinition[]> {
  const groups: Record<NodeCategory, BaseNodeDefinition[]> = {
    image: [],
    video: [],
    utility: [],
  };

  for (const node of nodeDefinitions) {
    groups[node.category].push(node);
  }

  return groups;
}

// Category display names
export const categoryLabels: Record<NodeCategory, string> = {
  image: "Image",
  video: "Video",
  utility: "Utility",
};
