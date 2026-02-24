"use client";

import { useCallback, useRef } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type ReactFlowInstance,
  type OnSelectionChangeParams,
  type Connection,
  type OnNodesChange,
  type OnEdgesChange,
  type NodeTypes,
  type EdgeTypes,
  BackgroundVariant,
  Panel,
} from "@xyflow/react";
import type { WorkflowNode as WorkflowNodeType, WorkflowEdge as WorkflowEdgeType, WorkflowNodeData } from "./types";

interface WorkflowGraphProps {
  nodes: WorkflowNodeType[];
  edges: WorkflowEdgeType[];
  onNodesChange: OnNodesChange<WorkflowNodeType>;
  onEdgesChange: OnEdgesChange<WorkflowEdgeType>;
  onConnect: (connection: Connection) => void;
  onSelectionChange: (params: OnSelectionChangeParams) => void;
  onPaneClick: () => void;
  isValidConnection: (
    connection:
      | Connection
      | { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null }
  ) => boolean;
  onRequestContextMenu: (position: {
    screen: { x: number; y: number };
    flow: { x: number; y: number };
  }) => void;
  nodeTypes: NodeTypes;
  edgeTypes: EdgeTypes;
}

export function WorkflowGraph({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onSelectionChange,
  onPaneClick,
  isValidConnection,
  onRequestContextMenu,
  nodeTypes,
  edgeTypes,
}: WorkflowGraphProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const reactFlowInstanceRef = useRef<ReactFlowInstance<WorkflowNodeType, WorkflowEdgeType> | null>(null);

  const onCanvasContextMenu = useCallback(
    (event: React.MouseEvent) => {
      event.preventDefault();

      const reactFlowInstance = reactFlowInstanceRef.current;
      if (!reactFlowInstance) return;
      const bounds = reactFlowWrapper.current?.getBoundingClientRect();
      if (!bounds) return;

      const flowPosition = reactFlowInstance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      onRequestContextMenu({
        screen: { x: event.clientX, y: event.clientY },
        flow: flowPosition,
      });
    },
    [onRequestContextMenu]
  );

  return (
    <div ref={reactFlowWrapper} className="flex-1">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onSelectionChange={onSelectionChange}
        onPaneClick={onPaneClick}
        isValidConnection={isValidConnection}
        onDoubleClick={onCanvasContextMenu}
        onContextMenu={onCanvasContextMenu}
        onInit={(instance) => {
          reactFlowInstanceRef.current = instance;
        }}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        defaultEdgeOptions={{ type: "workflow" }}
        fitView
        snapToGrid
        snapGrid={[16, 16]}
        connectionLineStyle={{ stroke: "var(--brand-secondary)", strokeWidth: 2 }}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="var(--border)" />
        <Controls className="!bg-[var(--surface-2)] !border-[var(--border-1)] !shadow-lg [&>button]:!bg-[var(--surface-3)] [&>button]:!border-[var(--border)] [&>button]:!text-[var(--text-primary)] [&>button:hover]:!bg-[var(--surface-4)]" />
        <MiniMap
          className="!bg-[var(--surface-2)] !border-[var(--border-1)]"
          nodeColor={(node) => (node.data as unknown as WorkflowNodeData)?.color || "#666"}
          maskColor="rgba(0, 0, 0, 0.8)"
        />
        <Panel position="bottom-center" className="!mb-4">
          <div className="px-3 py-1.5 bg-[var(--surface-2)] border border-[var(--border-1)] rounded-full text-xs text-[var(--text-muted)]">
            Double-click to add nodes
          </div>
        </Panel>
      </ReactFlow>
    </div>
  );
}
