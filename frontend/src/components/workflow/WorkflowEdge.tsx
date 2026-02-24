"use client";

/**
 * WorkflowEdge - Custom edge component with smooth step path
 * Inspired by SimStudio's edge styling
 */

import { memo } from "react";
import { BaseEdge, getSmoothStepPath, type EdgeProps } from "@xyflow/react";
import { getEdgeColor } from "./edgeColors";

function WorkflowEdgeComponent({
  id,
  source,
  target,
  sourceHandle,
  targetHandle,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  selected,
}: EdgeProps) {
  const color = getEdgeColor({ id, source, sourceHandle, target, targetHandle });
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
        strokeWidth: selected ? 3 : 2.2,
        stroke: color,
        opacity: selected ? 1 : 0.9,
      }}
    />
  );
}

export const WorkflowEdge = memo(WorkflowEdgeComponent);
