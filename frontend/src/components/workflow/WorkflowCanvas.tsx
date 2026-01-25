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
import { ChainsSidebar } from "../chains/ChainsSidebar";
import { ChainDashboard } from "../chains/ChainDashboard";
import { useNodeStore } from "@/stores/nodeStore";
import { useExecutionStore } from "@/stores/executionStore";
import { useChainStore } from "@/stores/chainStore";
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
  // Update mode - when true, the properties panel shows "Update Parameters" button
  const [updateMode, setUpdateMode] = useState(false);

  // Node store
  const nodeStore = useNodeStore();
  const { fetchWorkflows, getNodeDefinition, isLoading, error } = nodeStore;

  // Execution store
  const execution = useExecutionStore((state) => state.execution);
  const startExecution = useExecutionStore((state) => state.startExecution);
  const clearExecution = useExecutionStore((state) => state.clearExecution);
  const cancelChain = useExecutionStore((state) => state.cancelChain);
  const updateModeNodeId = useExecutionStore((state) => state.updateModeNodeId);
  const clearUpdateMode = useExecutionStore((state) => state.clearUpdateMode);
  const updateStepParameters = useExecutionStore((state) => state.updateStepParameters);

  // Chain store
  const sidebarOpen = useChainStore((state) => state.sidebarOpen);
  const currentChainName = useChainStore((state) => state.currentChainName);
  const setCurrentChainName = useChainStore((state) => state.setCurrentChainName);
  const fetchChainNames = useChainStore((state) => state.fetchChainNames);

  // Dashboard state
  const [showDashboard, setShowDashboard] = useState(false);

  // Wait before execution state
  const [waitEnabled, setWaitEnabled] = useState(false);
  const [waitSeconds, setWaitSeconds] = useState(0);

  // Track chain ID for SSE subscription
  const [chainId, setChainId] = useState<string | null>(null);

  // Subscribe to SSE events for execution updates
  const { disconnect } = useChainEvents(chainId);

  // Fetch workflows on mount
  useEffect(() => {
    fetchWorkflows();
  }, [fetchWorkflows]);

  // Watch for update mode requests from nodes
  useEffect(() => {
    if (updateModeNodeId) {
      // Toggle: if already selected in update mode, close it
      if (selectedNodeId === updateModeNodeId && updateMode) {
        setSelectedNodeId(null);
        setUpdateMode(false);
      } else {
        setSelectedNodeId(updateModeNodeId);
        setUpdateMode(true);
      }
      clearUpdateMode(); // Clear the request after handling
    }
  }, [updateModeNodeId, clearUpdateMode, selectedNodeId, updateMode]);

  // Listen for server change events from nodes
  useEffect(() => {
    const handleServerChange = (e: CustomEvent<{ nodeId: string; server: string | undefined }>) => {
      const { nodeId, server } = e.detail;
      setNodes((nds) =>
        nds.map((node) =>
          node.id === nodeId
            ? { ...node, data: { ...node.data, server, serverValidation: undefined } }
            : node
        )
      );
    };

    const handleServerValidation = (e: CustomEvent<{ nodeId: string; validation: { valid: boolean; missing_nodes?: string[]; invalid_inputs?: unknown[] } }>) => {
      const { nodeId, validation } = e.detail;
      const error = !validation.valid
        ? validation.missing_nodes?.length
          ? `Missing nodes: ${validation.missing_nodes.join(", ")}`
          : validation.invalid_inputs?.length
            ? `Invalid inputs detected`
            : "Validation failed"
        : undefined;

      setNodes((nds) =>
        nds.map((node) =>
          node.id === nodeId
            ? { ...node, data: { ...node.data, serverValidation: { valid: validation.valid, error } } }
            : node
        )
      );
    };

    window.addEventListener("nodeServerChange", handleServerChange as EventListener);
    window.addEventListener("nodeServerValidation", handleServerValidation as EventListener);

    return () => {
      window.removeEventListener("nodeServerChange", handleServerChange as EventListener);
      window.removeEventListener("nodeServerValidation", handleServerValidation as EventListener);
    };
  }, [setNodes]);

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
      setUpdateMode(false); // Reset update mode on selection change
    } else {
      setSelectedNodeId(null);
      setUpdateMode(false);
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

  // Handle pane click to deselect and close context menu
  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
    setContextMenu((prev) => ({ ...prev, show: false }));
  }, []);

  // Sanitize workflow name for use in step IDs (must be alphanumeric with _ or -)
  const sanitizeForId = (name: string): string => {
    return name
      .replace(/[()]/g, '')      // Remove parentheses
      .replace(/\s+/g, '_')       // Replace spaces with underscores
      .replace(/[^a-zA-Z0-9_-]/g, '') // Remove any other invalid chars
      .replace(/_+/g, '_')        // Collapse multiple underscores
      .replace(/^_|_$/g, '');     // Trim leading/trailing underscores
  };

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

      // Sanitize workflow name for step ID (must be alphanumeric with _ or -)
      const sanitizedName = sanitizeForId(workflow);

      const newNode: WorkflowNodeType = {
        id: `${sanitizedName}_${Date.now()}`,
        type: "workflow",
        position: contextMenu.flowPosition,
        data: {
          type: workflow, // workflow name is the node type
          label: definition.label,
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
    const chain = toChainDefinition(nodes, edges, currentChainName);
    setExportOutput(JSON.stringify(chain, null, 2));
  }, [nodes, edges, currentChainName]);

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

  // Handle loading chain from sidebar
  const handleLoadChain = useCallback((
    chainId: string,
    definition: Record<string, unknown>,
    artifacts: { status: string; steps: Array<{ step_id: string; status: string; error_message?: string | null; artifacts: Array<{ id: string; url: string }> }> }
  ) => {
    try {
      const chain = definition as unknown as ChainDefinition;
      const { nodes: importedNodes, edges: importedEdges, errors } = fromChainDefinition(chain, nodeStore);

      if (errors.length > 0) {
        console.warn("Load warnings:", errors);
      }

      // Set the chain name from the loaded definition
      if (chain.name) {
        setCurrentChainName(chain.name);
      }

      setNodes(importedNodes);
      setEdges(importedEdges);
      setExportOutput("");
      setSelectedNodeId(null);

      // Load artifacts into execution store to show on nodes
      const historicalSteps = artifacts.steps.map((step) => ({
        stepId: step.step_id,
        status: step.status,
        artifactUrl: step.artifacts[0]?.url,
        artifactId: step.artifacts[0]?.id,
        error: step.error_message || undefined,
      }));

      const loadFromHistory = useExecutionStore.getState().loadFromHistory;
      loadFromHistory(
        chainId,
        artifacts.status === "completed" ? "completed" : "failed",
        historicalSteps
      );
    } catch (err) {
      console.error("Failed to load chain:", err);
      alert("Failed to load chain definition.");
    }
  }, [nodeStore, setNodes, setEdges, setCurrentChainName]);

  // Handle execute button click
  const handleExecute = useCallback(async () => {
    const chain = toChainDefinition(nodes, edges, currentChainName);

    try {
      const requestBody: { chain: typeof chain; wait_seconds?: number } = { chain };
      if (waitEnabled && waitSeconds > 0) {
        requestBody.wait_seconds = waitSeconds;
      }

      const response = await fetch("http://localhost:8001/chains/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
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

      // Refresh chain sidebar to show new execution
      fetchChainNames();
    } catch (err) {
      console.error("Failed to execute:", err);
      alert("Failed to execute chain. Is the backend running?");
    }
  }, [nodes, edges, currentChainName, startExecution, fetchChainNames, waitEnabled, waitSeconds]);

  // Handle cancel execution (terminate the workflow)
  const handleCancelExecution = useCallback(async () => {
    if (execution?.chainId && execution.status === "running") {
      try {
        await cancelChain(execution.chainId);
      } catch (err) {
        console.error("Failed to cancel chain:", err);
      }
    }
    disconnect();
    setChainId(null);
    clearExecution();
  }, [execution, cancelChain, disconnect, clearExecution]);

  // Handle clear execution (just clear the UI state)
  const handleClearExecution = useCallback(() => {
    disconnect();
    setChainId(null);
    clearExecution();
  }, [disconnect, clearExecution]);

  // Handle new chain creation - clear the canvas
  const handleNewChain = useCallback(() => {
    setNodes([]);
    setEdges([]);
    setSelectedNodeId(null);
    setExportOutput("");
    handleClearExecution();
  }, [setNodes, setEdges, handleClearExecution]);

  // Handle update parameters for a running chain step
  const handleUpdateParameters = useCallback(async (nodeId: string, parameters: Record<string, unknown>) => {
    if (!execution?.chainId) return;

    try {
      await updateStepParameters(execution.chainId, nodeId, parameters);
      setUpdateMode(false);
      setSelectedNodeId(null);
    } catch (err) {
      console.error("Failed to update parameters:", err);
      alert(`Failed to update parameters: ${err instanceof Error ? err.message : "Unknown error"}`);
    }
  }, [execution, updateStepParameters]);

  return (
    <div className="flex h-screen bg-[var(--bg)]">
      {/* Chains sidebar */}
      <ChainsSidebar
        onViewDashboard={() => setShowDashboard(true)}
        onLoadChain={handleLoadChain}
        onNewChain={handleNewChain}
      />

      {/* Main content area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center justify-between px-4 py-2 bg-[var(--surface-1)] border-b border-[var(--border)]">
        <div className="flex items-center gap-4">
          <h1 className="text-base font-semibold text-[var(--text-primary)]">
            Graviton
          </h1>
          <div className="h-4 w-px bg-[var(--border)]" />
          <input
            type="text"
            value={currentChainName}
            onChange={(e) => setCurrentChainName(e.target.value)}
            className="px-2 py-1 bg-transparent border border-transparent hover:border-[var(--border)] focus:border-[var(--brand-primary)] rounded text-sm text-[var(--text-secondary)] focus:outline-none transition-colors"
            placeholder="Chain name..."
          />
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
            {/* Wait before execution */}
            <div className="flex items-center gap-2 px-2 py-1 bg-[var(--surface-3)] rounded-md">
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={waitEnabled}
                  onChange={(e) => setWaitEnabled(e.target.checked)}
                  className="w-3.5 h-3.5 rounded border-[var(--border)] bg-[var(--surface-4)] text-[var(--brand-primary)] focus:ring-0 focus:ring-offset-0 cursor-pointer"
                />
                <span className="text-xs text-[var(--text-secondary)]">Wait</span>
              </label>
              {waitEnabled && (
                <div className="flex items-center gap-1">
                  <input
                    type="number"
                    min={0}
                    value={waitSeconds}
                    onChange={(e) => setWaitSeconds(Math.max(0, parseInt(e.target.value) || 0))}
                    className="w-14 px-1.5 py-0.5 text-xs text-center bg-[var(--surface-4)] border border-[var(--border)] rounded text-[var(--text-primary)] focus:outline-none focus:border-[var(--brand-secondary)]"
                  />
                  <span className="text-xs text-[var(--text-muted)]">sec</span>
                </div>
              )}
            </div>

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
                {execution.status === "running" ? (
                  <button
                    onClick={handleCancelExecution}
                    className="px-3 py-1.5 text-sm bg-red-600 hover:bg-red-700 text-white rounded-md transition-colors"
                  >
                    Cancel
                  </button>
                ) : (
                  <button
                    onClick={handleClearExecution}
                    className="px-3 py-1.5 text-sm bg-[var(--surface-4)] hover:bg-[var(--surface-5)] text-[var(--text-primary)] rounded-md transition-colors"
                  >
                    Clear
                  </button>
                )}
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

        {/* Properties panel (right side) */}
        {selectedNode && (
          <NodePropertiesPanel
            nodeId={selectedNode.id}
            data={selectedNode.data as WorkflowNodeData}
            onClose={() => {
              setSelectedNodeId(null);
              setUpdateMode(false);
            }}
            setNodes={setNodes}
            updateMode={updateMode}
            onUpdateParameters={handleUpdateParameters}
          />
        )}

        {/* Export output panel (right side) */}
        {exportOutput && !selectedNode && (
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

      {/* Chain dashboard modal */}
      {showDashboard && (
        <ChainDashboard onClose={() => setShowDashboard(false)} />
      )}
    </div>
  );
}
