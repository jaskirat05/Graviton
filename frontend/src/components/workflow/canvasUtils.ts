import type { Connection } from "@xyflow/react";
import type { WorkflowNode as WorkflowNodeType, WorkflowNodeData } from "./types";

export function sanitizeWorkflowStepId(name: string): string {
  return name
    .replace(/[()]/g, "")
    .replace(/\s+/g, "_")
    .replace(/[^a-zA-Z0-9_-]/g, "")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");
}

export function isConnectionTypeCompatible(
  nodes: WorkflowNodeType[],
  connection: Connection | { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null }
): boolean {
  const sourceNode = nodes.find((n) => n.id === connection.source);
  const targetNode = nodes.find((n) => n.id === connection.target);

  if (!sourceNode || !targetNode) return false;

  const sourceData = sourceNode.data as WorkflowNodeData;
  const targetData = targetNode.data as WorkflowNodeData;

  const outputSocket = sourceData.definition.outputs.find((o) => o.id === connection.sourceHandle);
  const inputSocket = targetData.definition.inputs.find((i) => i.id === connection.targetHandle);

  if (!outputSocket || !inputSocket) return false;
  if (outputSocket.type === "any" || inputSocket.type === "any") return true;
  return outputSocket.type === inputSocket.type;
}
