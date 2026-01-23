"use client";

/**
 * WorkflowCanvas - Main workflow editor component using ReactFlow
 */

import { useCallback, useState, useRef, useEffect, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type NodeTypes,
  type EdgeTypes,
  BackgroundVariant,
  Panel,
  type OnSelectionChangeParams,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { WorkflowNode } from "./WorkflowNode";
import { WorkflowEdge } from "./WorkflowEdge";
import { ContextMenu } from "./ContextMenu";
import { NodePropertiesPanel } from "./NodePropertiesPanel";
import { useNodeStore } from "@/stores/nodeStore";
import { useExecutionStore } from "@/stores/executionStore";
import { useChainEvents } from "@/hooks/useChainEvents";
import { toChainDefinition, fromChainDefinition } from "./chainUtils";
import type { WorkflowNode as WorkflowNodeType, WorkflowEdge as WorkflowEdgeType, WorkflowNodeData, ChainDefinition } from "./types";

// Register custom node and edge types
const nodeTypes: NodeTypes = {
  workflow: WorkflowNode,
};

const edgeTypes: EdgeTypes = {
  workflow: WorkflowEdge,
};

// Initial empty state
const initialNodes: WorkflowNodeType[] = [];
const initialEdges: WorkflowEdgeType[] = [];

export function WorkflowCanvas() {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Selected node for properties panel
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // Node store
  const nodeStore = useNodeStore();
  const { fetchWorkflows, getNodeDefinition, isLoading, error } = nodeStore;

  // Execution store
  const execution = useExecutionStore((state) => state.execution);
  const startExecution = useExecutionStore((state) => state.startExecution);
  const clearExecution = useExecutionStore((state) => state.clearExecution);

  // Track chain ID for SSE subscription
  const [chainId, setChainId] = useState<string | null>(null);

  // Subscribe to SSE events for execution updates
  const { disconnect } = useChainEvents(chainId);

  // Fetch workflows on mount
  useEffect(() => {
    fetchWorkflows();
  }, [fetchWorkflows]);

  // Get selected node data
  const selectedNode = useMemo(() => {
    if (!selectedNodeId) return null;
    return nodes.find((n) => n.id === selectedNodeId);
  }, [selectedNodeId, nodes]);

  // Context menu state
  const [contextMenu, setContextMenu] = useState<{
    show: boolean;
    position: { x: number; y: number };
    flowPosition: { x: number; y: number };
  }>({ show: false, position: { x: 0, y: 0 }, flowPosition: { x: 0, y: 0 } });

  // Export output state
  const [exportOutput, setExportOutput] = useState<string>("");

  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [reactFlowInstance, setReactFlowInstance] = useState<any>(null);

  // Handle selection change
  const onSelectionChange = useCallback(({ nodes: selectedNodes }: OnSelectionChangeParams) => {
    if (selectedNodes.length === 1) {
      setSelectedNodeId(selectedNodes[0].id);
    } else {
      setSelectedNodeId(null);
    }
  }, []);

  // Validate connections - check socket type compatibility
  const isValidConnection = useCallback(
    (connection: Connection | { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null }) => {
      const sourceNode = nodes.find((n) => n.id === connection.source);
      const targetNode = nodes.find((n) => n.id === connection.target);

      if (!sourceNode || !targetNode) return false;

      const sourceData = sourceNode.data as WorkflowNodeData;
      const targetData = targetNode.data as WorkflowNodeData;

      // Find the output socket on source node
      const outputSocket = sourceData.definition.outputs.find(
        (o) => o.id === connection.sourceHandle
      );

      // Find the input socket on target node
      const inputSocket = targetData.definition.inputs.find(
        (i) => i.id === connection.targetHandle
      );

      if (!outputSocket || !inputSocket) return false;

      // "any" type connects to anything
      if (outputSocket.type === "any" || inputSocket.type === "any") {
        return true;
      }

      // Otherwise types must match (image->image, video->video)
      return outputSocket.type === inputSocket.type;
    },
    [nodes]
  );

  // Handle new connections
  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) =>
        addEdge(
          {
            ...connection,
            type: "workflow",
          },
          eds
        )
      );
    },
    [setEdges]
  );

  // Handle double-click to open context menu
  const onDoubleClick = useCallback(
    (event: React.MouseEvent) => {
      event.preventDefault();

      if (!reactFlowInstance) return;

      const bounds = reactFlowWrapper.current?.getBoundingClientRect();
      if (!bounds) return;

      // Get flow coordinates from screen position
      const flowPosition = reactFlowInstance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      setContextMenu({
        show: true,
        position: { x: event.clientX, y: event.clientY },
        flowPosition,
      });
    },
    [reactFlowInstance]
  );

  // Handle right-click context menu
  const onContextMenu = useCallback(
    (event: React.MouseEvent) => {
      event.preventDefault();
      onDoubleClick(event);
    },
    [onDoubleClick]
  );

  // Handle pane click to deselect
  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  // Add a node from context menu (nodeType is the workflow name)
  const addNode = useCallback(
    (workflow: string) => {
      const definition = getNodeDefinition(workflow);
      if (!definition) return;

      // Create default parameter values
      const parameters: Record<string, string | number> = {};
      for (const param of definition.inputParameters) {
        if (param.default !== undefined) {
          parameters[param.id] = param.default;
        }
      }

      const newNode: WorkflowNodeType = {
        id: `${workflow}_${Date.now()}`,
        type: "workflow",
        position: contextMenu.flowPosition,
        data: {
          type: workflow, // workflow name is the node type
          label: definition.label,
          icon: definition.icon,
          color: definition.color,
          parameters,
          definition,
        },
      };

      setNodes((nds) => [...nds, newNode]);
      setContextMenu((prev) => ({ ...prev, show: false }));

      // Select the new node
      setSelectedNodeId(newNode.id);
    },
    [contextMenu.flowPosition, setNodes, getNodeDefinition]
  );

  // Handle export button click
  const handleExport = useCallback(() => {
    const chain = toChainDefinition(nodes, edges);
    setExportOutput(JSON.stringify(chain, null, 2));
  }, [nodes, edges]);

  // Handle import from JSON
  const handleImport = useCallback((jsonString: string) => {
    try {
      const chain: ChainDefinition = JSON.parse(jsonString);
      const { nodes: importedNodes, edges: importedEdges, errors } = fromChainDefinition(chain, nodeStore);

      if (errors.length > 0) {
        console.warn("Import warnings:", errors);
        alert(`Import completed with warnings:\n${errors.join("\n")}`);
      }

      setNodes(importedNodes);
      setEdges(importedEdges);
      setExportOutput("");
    } catch (err) {
      console.error("Failed to import chain:", err);
      alert("Failed to import chain. Check the JSON format.");
    }
  }, [nodeStore, setNodes, setEdges]);

  // Handle execute button click
  const handleExecute = useCallback(async () => {
    const chain = toChainDefinition(nodes, edges);

    try {
      const response = await fetch("http://localhost:8001/chains/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chain }),
      });
      const result = await response.json();

      // Get step IDs from the chain
      const stepIds = nodes.map((n) => n.id);

      console.log("[Execute] Chain ID:", result.chain_id);
      console.log("[Execute] Step IDs:", stepIds);
      console.log("[Execute] Full response:", result);

      // Start tracking execution
      startExecution(result.chain_id, result.job_id || result.chain_id, stepIds);

      // Subscribe to SSE events
      setChainId(result.chain_id);
    } catch (err) {
      console.error("Failed to execute:", err);
      alert("Failed to execute chain. Is the backend running?");
    }
  }, [nodes, edges, startExecution]);

  // Handle stop/clear execution
  const handleStopExecution = useCallback(() => {
    disconnect();
    setChainId(null);
    clearExecution();
  }, [disconnect, clearExecution]);

  return (
    <div className="flex flex-col h-screen bg-[var(--bg)]">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 bg-[var(--surface-1)] border-b border-[var(--border)]">
        <div className="flex items-center gap-4">
          <h1 className="text-base font-semibold text-[var(--text-primary)]">
            Chain Editor
          </h1>
          <div className="flex items-center gap-2">
            <input
              type="file"
              accept=".json"
              className="hidden"
              id="import-file"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) {
                  const reader = new FileReader();
                  reader.onload = (event) => {
                    handleImport(event.target?.result as string);
                  };
                  reader.readAsText(file);
                  e.target.value = ""; // Reset for re-import
                }
              }}
            />
            <button
              onClick={() => document.getElementById("import-file")?.click()}
              className="px-3 py-1.5 text-sm bg-[var(--surface-4)] hover:bg-[var(--surface-5)] text-[var(--text-primary)] rounded-md transition-colors"
            >
              Import
            </button>
            <button
              onClick={handleExport}
              className="px-3 py-1.5 text-sm bg-[var(--surface-4)] hover:bg-[var(--surface-5)] text-[var(--text-primary)] rounded-md transition-colors"
            >
              Export
            </button>
            {!execution ? (
              <button
                onClick={handleExecute}
                disabled={nodes.length === 0}
                className="px-3 py-1.5 text-sm bg-[var(--brand-success)] hover:opacity-90 text-white rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Execute
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <span className={`text-xs px-2 py-1 rounded ${
                  execution.status === "running" ? "bg-blue-500/20 text-blue-400" :
                  execution.status === "completed" ? "bg-green-500/20 text-green-400" :
                  "bg-red-500/20 text-red-400"
                }`}>
                  {execution.status === "running" ? "Running..." :
                   execution.status === "completed" ? "Completed" : "Failed"}
                </span>
                <button
                  onClick={handleStopExecution}
                  className="px-3 py-1.5 text-sm bg-red-600 hover:bg-red-700 text-white rounded-md transition-colors"
                >
                  {execution.status === "running" ? "Stop" : "Clear"}
                </button>
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-4">
          {isLoading && (
            <span className="text-xs text-[var(--text-muted)]">Loading nodes...</span>
          )}
          {error && (
            <span className="text-xs text-red-500">Error: {error}</span>
          )}
          <span className="text-xs text-[var(--text-muted)]">
            Double-click to add nodes • Click node to edit
          </span>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Properties panel (left side) */}
        {selectedNode && (
          <NodePropertiesPanel
            nodeId={selectedNode.id}
            data={selectedNode.data as WorkflowNodeData}
            onClose={() => setSelectedNodeId(null)}
            setNodes={setNodes}
          />
        )}

        {/* Canvas */}
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
            onDoubleClick={onDoubleClick}
            onContextMenu={onContextMenu}
            onInit={setReactFlowInstance}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            defaultEdgeOptions={{ type: "workflow" }}
            fitView
            snapToGrid
            snapGrid={[16, 16]}
            connectionLineStyle={{ stroke: "var(--brand-secondary)", strokeWidth: 2 }}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={16}
              size={1}
              color="var(--border)"
            />
            <Controls
              className="!bg-[var(--surface-2)] !border-[var(--border-1)] !shadow-lg [&>button]:!bg-[var(--surface-3)] [&>button]:!border-[var(--border)] [&>button]:!text-[var(--text-primary)] [&>button:hover]:!bg-[var(--surface-4)]"
            />
            <MiniMap
              className="!bg-[var(--surface-2)] !border-[var(--border-1)]"
              nodeColor={(node) => (node.data as unknown as WorkflowNodeData)?.color || "#666"}
              maskColor="rgba(0, 0, 0, 0.8)"
            />

            {/* Hint panel */}
            <Panel position="bottom-center" className="!mb-4">
              <div className="px-3 py-1.5 bg-[var(--surface-2)] border border-[var(--border-1)] rounded-full text-xs text-[var(--text-muted)]">
                Double-click to add nodes
              </div>
            </Panel>
          </ReactFlow>
        </div>

        {/* Export output panel (right side) */}
        {exportOutput && (
          <div className="w-96 bg-[var(--surface-1)] border-l border-[var(--border)] overflow-auto">
            <div className="p-4">
              <div className="flex items-center justify-between mb-2">
                <h2 className="text-sm font-medium text-[var(--text-primary)]">Chain Output</h2>
                <button
                  onClick={() => setExportOutput("")}
                  className="text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                >
                  Close
                </button>
              </div>
              <pre className="text-xs text-[var(--text-secondary)] bg-[var(--surface-3)] p-4 rounded-md overflow-auto">
                {exportOutput}
              </pre>
            </div>
          </div>
        )}
      </div>

      {/* Context menu */}
      {contextMenu.show && (
        <ContextMenu
          position={contextMenu.position}
          onSelect={addNode}
          onClose={() => setContextMenu((prev) => ({ ...prev, show: false }))}
        />
      )}
    </div>
  );
}
