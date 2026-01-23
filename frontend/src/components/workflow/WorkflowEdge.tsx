"use client";

/**
 * WorkflowEdge - Custom edge component with smooth step path
 * Inspired by SimStudio's edge styling
 */

import { memo } from "react";
import { BaseEdge, getSmoothStepPath, type EdgeProps } from "@xyflow/react";

function WorkflowEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  selected,
}: EdgeProps) {
  const [edgePath] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 8,
    offset: 30,
  });

  return (
    <BaseEdge
      id={id}
      path={edgePath}
      style={{
        strokeWidth: selected ? 2.5 : 2,
        stroke: selected ? "var(--brand-secondary)" : "var(--workflow-edge)",
      }}
    />
  );
}

export const WorkflowEdge = memo(WorkflowEdgeComponent);
