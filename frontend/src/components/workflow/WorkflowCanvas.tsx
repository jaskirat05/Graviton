"use client";

/**
 * WorkflowCanvas - Main workflow editor component using ReactFlow
 */

import { useCallback, useRef, useEffect, useMemo } from "react";
import {
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type NodeTypes,
  type EdgeTypes,
  type OnSelectionChangeParams,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { WorkflowNode } from "./WorkflowNode";
import { WorkflowEdge } from "./WorkflowEdge";
import { WorkflowToolbar } from "./WorkflowToolbar";
import { WorkflowGraph } from "./WorkflowGraph";
import { WorkflowSidePanels } from "./WorkflowSidePanels";
import { WorkflowOverlays } from "./WorkflowOverlays";
import { ChainsSidebar } from "../chains/ChainsSidebar";
import { LevelWaitBar } from "./LevelWaitBar";
import { useNodeStore } from "@/stores/nodeStore";
import { useExecutionStore } from "@/stores/executionStore";
import { useChainStore } from "@/stores/chainStore";
import { useServerStore } from "@/stores/serverStore";
import { useChainExecutionStore } from "@/stores/chainExecutionStore";
import { useChainEvents } from "@/hooks/useChainEvents";
import { useComfyServerUrl } from "@/hooks/useComfyServerUrl";
import { useRegistryEvents } from "@/hooks/useRegistryEvents";
import { useWorkflowEditorStore } from "@/stores/workflowEditorStore";
import { toChainDefinition, fromChainDefinition } from "./chainUtils";
import { sanitizeWorkflowStepId, isConnectionTypeCompatible } from "./canvasUtils";
import { useNewWorkflowBridge } from "./hooks/useNewWorkflowBridge";
import type { WorkflowNode as WorkflowNodeType, WorkflowEdge as WorkflowEdgeType, ChainDefinition } from "./types";

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
const WORKFLOW_DRAFT_STORAGE_KEY = "graviton.workflowCanvasDraft.v1";
const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:8001";

function toErrorText(value: unknown): string | undefined {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return undefined;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function collectRerunStepIds(fromStepId: string, edges: WorkflowEdgeType[]): Set<string> {
  const rerunStepIds = new Set<string>([fromStepId]);
  const queue: string[] = [fromStepId];

  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) continue;
    for (const edge of edges) {
      if (edge.source !== current) continue;
      const next = edge.target;
      if (!next || rerunStepIds.has(next)) continue;
      rerunStepIds.add(next);
      queue.push(next);
    }
  }

  return rerunStepIds;
}

export function WorkflowCanvas() {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Node store
  const nodeStore = useNodeStore();
  const { fetchWorkflows, getNodeDefinition, nodeDefinitions, isLoading, error } = nodeStore;

  // Execution store
  const execution = useExecutionStore((state) => state.execution);
  const startExecution = useExecutionStore((state) => state.startExecution);
  const markStepsCached = useExecutionStore((state) => state.markStepsCached);
  const clearExecution = useExecutionStore((state) => state.clearExecution);
  const cancelChain = useExecutionStore((state) => state.cancelChain);
  const abortAllChains = useExecutionStore((state) => state.abortAllChains);
  const updateModeNodeId = useExecutionStore((state) => state.updateModeNodeId);
  const clearUpdateMode = useExecutionStore((state) => state.clearUpdateMode);
  const updateStepParameters = useExecutionStore((state) => state.updateStepParameters);
  const fatalExecutionError = useExecutionStore((state) => state.fatalError);
  const closeFatalExecutionError = useExecutionStore((state) => state.closeFatalError);
  const servers = useServerStore((state) => state.servers);
  const fetchServers = useServerStore((state) => state.fetchServers);
  const getComfyServerUrl = useComfyServerUrl();

  // Chain store
  const currentChainName = useChainStore((state) => state.currentChainName);
  const setCurrentChainName = useChainStore((state) => state.setCurrentChainName);
  const fetchChainNames = useChainStore((state) => state.fetchChainNames);
  const selectVersion = useChainStore((state) => state.selectVersion);

  // Workflow editor UI store
  const selectedNodeId = useWorkflowEditorStore((state) => state.selectedNodeId);
  const setSelectedNodeId = useWorkflowEditorStore((state) => state.setSelectedNodeId);
  const updateMode = useWorkflowEditorStore((state) => state.updateMode);
  const setUpdateMode = useWorkflowEditorStore((state) => state.setUpdateMode);
  const showDashboard = useWorkflowEditorStore((state) => state.showDashboard);
  const setShowDashboard = useWorkflowEditorStore((state) => state.setShowDashboard);
  const showSettings = useWorkflowEditorStore((state) => state.showSettings);
  const setShowSettings = useWorkflowEditorStore((state) => state.setShowSettings);
  const waitEnabled = useWorkflowEditorStore((state) => state.waitEnabled);
  const setWaitEnabled = useWorkflowEditorStore((state) => state.setWaitEnabled);
  const waitSeconds = useWorkflowEditorStore((state) => state.waitSeconds);
  const setWaitSeconds = useWorkflowEditorStore((state) => state.setWaitSeconds);
  const chainId = useWorkflowEditorStore((state) => state.chainId);
  const setChainId = useWorkflowEditorStore((state) => state.setChainId);
  const definitionSignature = useWorkflowEditorStore((state) => state.definitionSignature);
  const setDefinitionSignature = useWorkflowEditorStore((state) => state.setDefinitionSignature);
  const contextMenu = useWorkflowEditorStore((state) => state.contextMenu);
  const setContextMenu = useWorkflowEditorStore((state) => state.setContextMenu);
  const exportOutput = useWorkflowEditorStore((state) => state.exportOutput);
  const setExportOutput = useWorkflowEditorStore((state) => state.setExportOutput);
  const resetForNewChain = useWorkflowEditorStore((state) => state.resetForNewChain);
  const isNewWorkflowEditorOpen = useWorkflowEditorStore((state) => state.isNewWorkflowEditorOpen);
  const setIsNewWorkflowEditorOpen = useWorkflowEditorStore((state) => state.setIsNewWorkflowEditorOpen);
  const isOpeningNewWorkflowEditor = useWorkflowEditorStore((state) => state.isOpeningNewWorkflowEditor);
  const setIsOpeningNewWorkflowEditor = useWorkflowEditorStore((state) => state.setIsOpeningNewWorkflowEditor);
  const isSavingNewWorkflow = useWorkflowEditorStore((state) => state.isSavingNewWorkflow);
  const setIsSavingNewWorkflow = useWorkflowEditorStore((state) => state.setIsSavingNewWorkflow);
  const newWorkflowError = useWorkflowEditorStore((state) => state.newWorkflowError);
  const setNewWorkflowError = useWorkflowEditorStore((state) => state.setNewWorkflowError);
  const newWorkflowBridgeStatus = useWorkflowEditorStore((state) => state.newWorkflowBridgeStatus);
  const setNewWorkflowBridgeStatus = useWorkflowEditorStore((state) => state.setNewWorkflowBridgeStatus);
  const newWorkflowBaseUrl = useWorkflowEditorStore((state) => state.newWorkflowBaseUrl);
  const setNewWorkflowBaseUrl = useWorkflowEditorStore((state) => state.setNewWorkflowBaseUrl);
  const newWorkflowName = useWorkflowEditorStore((state) => state.newWorkflowName);
  const setNewWorkflowName = useWorkflowEditorStore((state) => state.setNewWorkflowName);
  const newWorkflowServerName = useWorkflowEditorStore((state) => state.newWorkflowServerName);
  const setNewWorkflowServerName = useWorkflowEditorStore((state) => state.setNewWorkflowServerName);
  const resetNewWorkflowEditor = useWorkflowEditorStore((state) => state.resetNewWorkflowEditor);
  const executeWithCache = useChainExecutionStore((state) => state.executeWithCache);

  // Subscribe to SSE events for execution updates
  const { disconnect } = useChainEvents(chainId);
  useRegistryEvents(fetchWorkflows);

  // Fetch workflows on mount
  useEffect(() => {
    fetchWorkflows();
  }, [fetchWorkflows]);

  // Reconcile existing canvas nodes whenever registry node definitions change.
  // This keeps edited/deleted template nodes in sync without manual re-add.
  useEffect(() => {
    setNodes((currentNodes) => {
      let changed = false;

      const reconciled = currentNodes.map((node) => {
        const data = node.data as WorkflowNodeData;
        if (!data?.type) return node;

        const latest = getNodeDefinition(data.type);
        if (!latest) {
          const missingError = `Template '${data.type}' no longer exists in registry.`;
          const alreadyMissing =
            data.definition?.category === "invalid" &&
            data.serverValidation?.valid === false &&
            data.serverValidation?.error === missingError;

          if (alreadyMissing) {
            return node;
          }

          changed = true;
          return {
            ...node,
            data: {
              ...data,
              definition: {
                ...data.definition,
                category: "invalid",
                description: missingError,
              },
              serverValidation: {
                valid: false,
                error: missingError,
              },
            },
          };
        }

        const currentParams = data.parameters || {};
        const nextParams: Record<string, string | number> = {};
        for (const param of latest.inputParameters) {
          const currentValue = currentParams[param.id];
          if (typeof currentValue === "string" || typeof currentValue === "number") {
            nextParams[param.id] = currentValue;
          } else if (param.default !== undefined) {
            nextParams[param.id] = param.default;
          }
        }

        const prevKeys = Object.keys(currentParams).sort();
        const nextKeys = Object.keys(nextParams).sort();
        const paramsChanged =
          prevKeys.length !== nextKeys.length ||
          prevKeys.some((key, index) => key !== nextKeys[index]) ||
          nextKeys.some((key) => currentParams[key] !== nextParams[key]);

        const definitionChanged =
          data.definition.type !== latest.type ||
          data.definition.label !== latest.label ||
          data.definition.color !== latest.color ||
          data.definition.category !== latest.category ||
          data.definition.description !== latest.description ||
          data.definition.inputParameters.length !== latest.inputParameters.length ||
          data.definition.inputs.length !== latest.inputs.length ||
          data.definition.outputs.length !== latest.outputs.length;

        const labelChanged = data.label !== latest.label;
        const colorChanged = data.color !== latest.color;

        if (!paramsChanged && !definitionChanged && !labelChanged && !colorChanged) {
          return node;
        }

        changed = true;
        return {
          ...node,
          data: {
            ...data,
            label: latest.label,
            color: latest.color,
            definition: latest,
            parameters: nextParams,
          },
        };
      });

      return changed ? reconciled : currentNodes;
    });
  }, [getNodeDefinition, nodeDefinitions, setNodes]);

  // Restore workflow draft after refresh.
  useEffect(() => {
    if (draftHydratedRef.current) return;
    try {
      const raw = window.localStorage.getItem(WORKFLOW_DRAFT_STORAGE_KEY);
      if (!raw) {
        draftHydratedRef.current = true;
        return;
      }

      const parsed = JSON.parse(raw) as {
        chainName?: string;
        definitionSignature?: string | null;
        nodes?: WorkflowNodeType[];
        edges?: WorkflowEdgeType[];
        waitEnabled?: boolean;
        waitSeconds?: number;
      };

      if (typeof parsed.chainName === "string" && parsed.chainName.trim()) {
        setCurrentChainName(parsed.chainName);
      }
      if (
        parsed.definitionSignature === null ||
        (typeof parsed.definitionSignature === "string" && parsed.definitionSignature.trim())
      ) {
        setDefinitionSignature(parsed.definitionSignature ?? null);
      }
      if (Array.isArray(parsed.nodes)) {
        setNodes(parsed.nodes);
      }
      if (Array.isArray(parsed.edges)) {
        setEdges(parsed.edges);
      }
      if (typeof parsed.waitEnabled === "boolean") {
        setWaitEnabled(parsed.waitEnabled);
      }
      if (typeof parsed.waitSeconds === "number" && Number.isFinite(parsed.waitSeconds)) {
        setWaitSeconds(Math.max(0, parsed.waitSeconds));
      }
    } catch (error) {
      console.error("Failed to restore workflow draft from localStorage:", error);
    } finally {
      draftHydratedRef.current = true;
    }
  }, [setCurrentChainName, setDefinitionSignature, setEdges, setNodes, setWaitEnabled, setWaitSeconds]);

  // Persist workflow draft during edits.
  useEffect(() => {
    if (!draftHydratedRef.current) return;
    if (persistTimerRef.current !== null) {
      window.clearTimeout(persistTimerRef.current);
    }

    persistTimerRef.current = window.setTimeout(() => {
      try {
        const payload = {
          chainName: currentChainName,
          definitionSignature,
          nodes,
          edges,
          waitEnabled,
          waitSeconds,
        };
        window.localStorage.setItem(WORKFLOW_DRAFT_STORAGE_KEY, JSON.stringify(payload));
      } catch (error) {
        console.error("Failed to persist workflow draft to localStorage:", error);
      }
    }, 250);

    return () => {
      if (persistTimerRef.current !== null) {
        window.clearTimeout(persistTimerRef.current);
      }
    };
  }, [currentChainName, definitionSignature, edges, nodes, waitEnabled, waitSeconds]);

  useEffect(() => {
    if (servers.length === 0) {
      void fetchServers();
    }
  }, [servers.length, fetchServers]);

  useEffect(() => {
    if (!newWorkflowServerName && servers.length > 0) {
      setNewWorkflowServerName(servers[0].name);
    }
  }, [newWorkflowServerName, servers, setNewWorkflowServerName]);

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
  }, [updateModeNodeId, clearUpdateMode, selectedNodeId, updateMode, setSelectedNodeId, setUpdateMode]);

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
    return nodes.find((n) => n.id === selectedNodeId) ?? null;
  }, [selectedNodeId, nodes]);

  const newWorkflowIframeRef = useRef<HTMLIFrameElement | null>(null);
  const newWorkflowPingTimerRef = useRef<number | null>(null);
  const draftHydratedRef = useRef(false);
  const persistTimerRef = useRef<number | null>(null);

  const selectedNewWorkflowServer = useMemo(
    () => servers.find((server) => server.name === newWorkflowServerName) || null,
    [servers, newWorkflowServerName]
  );
  const newWorkflowOrigin = useMemo(() => {
    if (!newWorkflowBaseUrl) return null;
    try {
      return new URL(newWorkflowBaseUrl).origin;
    } catch {
      return null;
    }
  }, [newWorkflowBaseUrl]);

  useEffect(() => {
    if (!isNewWorkflowEditorOpen || !selectedNewWorkflowServer) {
      return;
    }
    setNewWorkflowError(null);
    setNewWorkflowBridgeStatus("waiting-iframe-ready");
    setNewWorkflowBaseUrl(getComfyServerUrl(selectedNewWorkflowServer));
  }, [
    getComfyServerUrl,
    isNewWorkflowEditorOpen,
    selectedNewWorkflowServer,
    setNewWorkflowBaseUrl,
    setNewWorkflowBridgeStatus,
    setNewWorkflowError,
  ]);

  // Handle selection change
  const onSelectionChange = useCallback(({ nodes: selectedNodes }: OnSelectionChangeParams) => {
    if (selectedNodes.length === 1) {
      setSelectedNodeId(selectedNodes[0].id);
      setUpdateMode(false); // Reset update mode on selection change
    } else {
      setSelectedNodeId(null);
      setUpdateMode(false);
    }
  }, [setSelectedNodeId, setUpdateMode]);

  const isValidConnection = useCallback(
    (connection: Connection | { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null }) => {
      return isConnectionTypeCompatible(nodes, connection);
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

  // Handle pane click to deselect and close context menu
  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
    setContextMenu((prev) => ({ ...prev, show: false }));
    if (showSettings) {
      setShowSettings(false);
    }
  }, [setContextMenu, setSelectedNodeId, setShowSettings, showSettings]);

  const onRequestContextMenu = useCallback(
    (position: { screen: { x: number; y: number }; flow: { x: number; y: number } }) => {
      setContextMenu({
        show: true,
        position: position.screen,
        flowPosition: position.flow,
      });
    },
    [setContextMenu]
  );

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

      const sanitizedName = sanitizeWorkflowStepId(workflow);

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
    [contextMenu.flowPosition, setNodes, getNodeDefinition, setContextMenu, setSelectedNodeId]
  );

  // Handle export button click
  const handleExport = useCallback(() => {
    const chain = toChainDefinition(nodes, edges, currentChainName);
    setExportOutput(JSON.stringify(chain, null, 2));
  }, [nodes, edges, currentChainName, setExportOutput]);

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
      setDefinitionSignature(null);
    } catch (err) {
      console.error("Failed to import chain:", err);
      alert("Failed to import chain. Check the JSON format.");
    }
  }, [nodeStore, setNodes, setEdges, setExportOutput, setDefinitionSignature]);

  // Handle loading chain from sidebar
  const handleLoadChain = useCallback((
    chainId: string,
    definition: Record<string, unknown>,
    artifacts: { status: string; steps: Array<{ step_id: string; status: string; error_message?: string | null; artifacts: Array<{ id: string; url: string }> }> },
    loadedDefinitionHash?: string | null
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
      setDefinitionSignature(loadedDefinitionHash ?? null);

      // Load artifacts into execution store to show on nodes
      const historicalSteps = artifacts.steps.map((step) => ({
        stepId: step.step_id,
        status: step.status,
        artifactUrl: step.artifacts[0]?.url,
        artifactId: step.artifacts[0]?.id,
        error: toErrorText(step.error_message),
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
  }, [
    nodeStore,
    setNodes,
    setEdges,
    setCurrentChainName,
    setExportOutput,
    setSelectedNodeId,
    setDefinitionSignature,
  ]);

  // Handle execute button click
  const handleExecute = useCallback(async () => {
    const invalidNodes = nodes.filter((n) => {
      const data = n.data as { definition?: { category?: string } };
      return data.definition?.category === "invalid";
    });
    if (invalidNodes.length > 0) {
      alert(
        `Cannot execute chain: ${invalidNodes.length} invalid template node(s) must be fixed and revalidated first.`
      );
      return;
    }

    const chain = toChainDefinition(nodes, edges, currentChainName);

    try {
      const levelWaitSeconds = waitEnabled && waitSeconds > 0 ? waitSeconds : 0;
      const result = await executeWithCache(chain as unknown as Record<string, unknown>, {
        signature: definitionSignature,
        force: false,
        levelWaitSeconds,
      });
      setDefinitionSignature(result.signature);

      // Get step IDs from the chain
      const stepIds = nodes.map((n) => n.id);

      const payload = result.result;
      const resolvedChainId = String(payload.chain_id || "");
      const resolvedJobId = String(payload.job_id || resolvedChainId);
      if (!resolvedChainId) {
        throw new Error("Execution response missing chain_id");
      }

      if (result.mode === "cached" || payload.cached) {
        await selectVersion(resolvedChainId);
        const historical = useChainStore.getState().chainArtifacts;
        if (historical) {
          const historicalSteps = historical.steps.map((step) => ({
            stepId: step.step_id,
            status: step.status,
            artifactUrl: step.artifacts[0]?.url,
            artifactId: step.artifacts[0]?.id,
            error: toErrorText(step.error_message),
          }));
          const loadFromHistory = useExecutionStore.getState().loadFromHistory;
          loadFromHistory(
            resolvedChainId,
            historical.status === "completed" ? "completed" : "failed",
            historicalSteps
          );
        }
        setChainId(null);
        fetchChainNames();
        return;
      }

      // Start tracking execution
      startExecution(resolvedChainId, resolvedJobId, stepIds);

      if (result.mode === "regenerate" && result.changedSteps.length > 0) {
        const fromStepId = result.changedSteps[0].stepId;
        const rerunStepIds = collectRerunStepIds(fromStepId, edges);
        const cachedStepIds = stepIds.filter((stepId) => !rerunStepIds.has(stepId));

        let cachedArtifactByStepId: Record<string, { artifactId?: string; artifactUrl?: string }> = {};
        const sourceChainId = payload.cached_from_chain_id;
        if (typeof sourceChainId === "string" && sourceChainId.trim().length > 0) {
          try {
            const response = await fetch(`${GATEWAY_URL}/chains/${encodeURIComponent(sourceChainId)}/artifacts`);
            if (response.ok) {
              const sourceArtifacts = await response.json();
              const entries = Array.isArray(sourceArtifacts?.steps) ? sourceArtifacts.steps : [];
              cachedArtifactByStepId = Object.fromEntries(
                entries.map((step: { step_id?: unknown; artifacts?: Array<{ id?: unknown; url?: unknown }> }) => {
                  const stepId = typeof step.step_id === "string" ? step.step_id : "";
                  const artifact = Array.isArray(step.artifacts) ? step.artifacts[0] : undefined;
                  const artifactId = typeof artifact?.id === "string" ? artifact.id : undefined;
                  const artifactUrl = typeof artifact?.url === "string" ? artifact.url : undefined;
                  return [stepId, { artifactId, artifactUrl }];
                })
              );
            }
          } catch (error) {
            console.warn("Failed to load cached artifacts for regenerate:", error);
          }
        }

        markStepsCached(
          cachedStepIds.map((stepId) => {
            const artifact = cachedArtifactByStepId[stepId] || {};
            const artifactUrl =
              artifact.artifactId && !artifact.artifactUrl
                ? `${GATEWAY_URL}/artifact-service/artifacts/${artifact.artifactId}/download`
                : artifact.artifactUrl;
            return {
              stepId,
              artifactId: artifact.artifactId,
              artifactUrl,
            };
          })
        );
      }

      // Subscribe to SSE events
      setChainId(resolvedChainId);

      // Refresh chain sidebar to show new execution
      fetchChainNames();
    } catch (err) {
      console.error("Failed to execute:", err);
      alert("Failed to execute chain. Is the backend running?");
    }
  }, [
    nodes,
    edges,
    currentChainName,
    definitionSignature,
    executeWithCache,
    setDefinitionSignature,
    startExecution,
    markStepsCached,
    selectVersion,
    setChainId,
    fetchChainNames,
    waitEnabled,
    waitSeconds,
  ]);

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
  }, [execution, cancelChain, disconnect, clearExecution, setChainId]);

  const handleAbortAllExecution = useCallback(async () => {
    try {
      const result = await abortAllChains();
      if (execution?.status === "running") {
        disconnect();
        setChainId(null);
        clearExecution();
      }
      fetchChainNames();
      alert(`Abort requested for ${result.requested_count} chains. Cancelled: ${result.cancelled_count}.`);
    } catch (err) {
      console.error("Failed to abort all chains:", err);
      alert(`Failed to abort all chains: ${err instanceof Error ? err.message : "Unknown error"}`);
    }
  }, [abortAllChains, execution, disconnect, setChainId, clearExecution, fetchChainNames]);

  // Handle clear execution (just clear the UI state)
  const handleClearExecution = useCallback(() => {
    disconnect();
    setChainId(null);
    clearExecution();
  }, [disconnect, clearExecution, setChainId]);

  // Handle new chain creation - clear the canvas
  const handleNewChain = useCallback(() => {
    setNodes([]);
    setEdges([]);
    resetForNewChain();
    handleClearExecution();
    try {
      window.localStorage.removeItem(WORKFLOW_DRAFT_STORAGE_KEY);
    } catch (error) {
      console.error("Failed to clear workflow draft from localStorage:", error);
    }
  }, [setNodes, setEdges, resetForNewChain, handleClearExecution]);

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
  }, [execution, updateStepParameters, setUpdateMode, setSelectedNodeId]);

  const { openEditor: handleOpenNewWorkflowEditor, saveWorkflow: handleSaveNewWorkflow } =
    useNewWorkflowBridge({
      isOpen: isNewWorkflowEditorOpen,
      origin: newWorkflowOrigin,
      workflowName: newWorkflowName,
      selectedServer: selectedNewWorkflowServer,
      iframeRef: newWorkflowIframeRef,
      pingTimerRef: newWorkflowPingTimerRef,
      fetchServers,
      fetchWorkflows,
      getComfyServerUrl,
      setServerName: setNewWorkflowServerName,
      setBaseUrl: setNewWorkflowBaseUrl,
      setOpening: setIsOpeningNewWorkflowEditor,
      setSaving: setIsSavingNewWorkflow,
      setError: setNewWorkflowError,
      setStatus: setNewWorkflowBridgeStatus,
      setOpen: setIsNewWorkflowEditorOpen,
      setCurrentChainName,
    });

  return (
    <div className="flex h-screen bg-[var(--bg)]">
      {/* Chains sidebar */}
      <ChainsSidebar
        onViewDashboard={() => setShowDashboard(true)}
        onLoadChain={handleLoadChain}
        onNewChain={handleNewChain}
      />

      {/* Main content area */}
      <div className="relative flex-1 flex flex-col overflow-hidden">
        {/* Toolbar */}
        <WorkflowToolbar
          currentChainName={currentChainName}
          onChainNameChange={setCurrentChainName}
          onImport={handleImport}
          onExport={handleExport}
          onOpenNewWorkflow={handleOpenNewWorkflowEditor}
          isOpeningNewWorkflow={isOpeningNewWorkflowEditor}
          waitEnabled={waitEnabled}
          onWaitEnabledChange={setWaitEnabled}
          waitSeconds={waitSeconds}
          onWaitSecondsChange={setWaitSeconds}
          execution={execution}
          hasNodes={nodes.length > 0}
          onExecute={handleExecute}
          onCancelExecution={handleCancelExecution}
          onAbortAllExecution={handleAbortAllExecution}
          onClearExecution={handleClearExecution}
          onToggleSettings={() => setShowSettings(!showSettings)}
          isLoading={isLoading}
          error={error}
        />

        {/* Level wait progress bar */}
        <LevelWaitBar />

        {/* Main content */}
        <div className="flex-1 flex overflow-hidden">
          <WorkflowGraph
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onSelectionChange={onSelectionChange}
            onPaneClick={onPaneClick}
            isValidConnection={isValidConnection}
            onRequestContextMenu={onRequestContextMenu}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
          />

          <WorkflowSidePanels
            selectedNode={selectedNode}
            updateMode={updateMode}
            setNodes={setNodes}
            onCloseNodePanel={() => {
              setSelectedNodeId(null);
              setUpdateMode(false);
            }}
            onUpdateParameters={handleUpdateParameters}
            exportOutput={exportOutput}
            onCloseExport={() => setExportOutput("")}
          />
        </div>

        <WorkflowOverlays
          showSettings={showSettings}
          onCloseSettings={() => setShowSettings(false)}
          contextMenu={{ show: contextMenu.show, position: contextMenu.position }}
          onContextSelect={addNode}
          onContextClose={() => setContextMenu((prev) => ({ ...prev, show: false }))}
          showDashboard={showDashboard}
          onCloseDashboard={() => setShowDashboard(false)}
          isNewWorkflowEditorOpen={isNewWorkflowEditorOpen}
          newWorkflowBaseUrl={newWorkflowBaseUrl}
          selectedNewWorkflowServerName={selectedNewWorkflowServer?.name || null}
          newWorkflowBridgeStatus={newWorkflowBridgeStatus}
          newWorkflowName={newWorkflowName}
          onChangeNewWorkflowName={setNewWorkflowName}
          newWorkflowServerName={newWorkflowServerName}
          onChangeNewWorkflowServerName={setNewWorkflowServerName}
          servers={servers}
          isSavingNewWorkflow={isSavingNewWorkflow}
          onSaveNewWorkflow={handleSaveNewWorkflow}
          onCloseNewWorkflow={resetNewWorkflowEditor}
          newWorkflowError={newWorkflowError}
          newWorkflowIframeRef={newWorkflowIframeRef}
          fatalExecutionError={fatalExecutionError}
          onCloseFatalExecutionError={closeFatalExecutionError}
        />
      </div>
    </div>
  );
}
