"use client";

/**
 * NodePropertiesPanel - Side panel for editing selected node's parameters
 * Shows dropdowns for parameters with available options from the server
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useServerStore } from "@/stores/serverStore";
import { useNodeStore } from "@/stores/nodeStore";
import { useComfyServerUrl } from "@/hooks/useComfyServerUrl";
import type { WorkflowNodeData, InputParameterDefinition } from "./types";

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:8001";

type ComfyPromptNode = {
  class_type: string;
  inputs: Record<string, unknown>;
};

type ComfyPrompt = Record<string, ComfyPromptNode>;

type ParameterSectionId =
  | "prompts"
  | "core_generation"
  | "models"
  | "resolution_timing"
  | "bridge_inputs"
  | "other";

type ParameterSection = {
  id: ParameterSectionId;
  label: string;
  params: InputParameterDefinition[];
  editedCount: number;
};

type SubgraphGroup = {
  key: string;
  label: string;
  pairKey: string | null;
  params: InputParameterDefinition[];
  editedCount: number;
};

const PARAMETER_SECTION_ORDER: Array<{ id: ParameterSectionId; label: string }> = [
  { id: "prompts", label: "Prompts" },
  { id: "core_generation", label: "Core Generation" },
  { id: "models", label: "Models" },
  { id: "resolution_timing", label: "Resolution & Timing" },
  { id: "bridge_inputs", label: "Bridge Inputs" },
  { id: "other", label: "Other" },
];

function parseParameterKey(key: string): { nodeId: string; inputKey: string; innerNodeId: string } | null {
  const idx = key.lastIndexOf(".");
  if (idx <= 0 || idx >= key.length - 1) return null;
  const nodeId = key.slice(0, idx);
  const inputKey = key.slice(idx + 1);
  const innerNodeId = nodeId.includes(":") ? nodeId.split(":", 2)[1] : nodeId;
  return { nodeId, inputKey, innerNodeId };
}

function resolveOptionsForParam(
  paramId: string,
  optionsMap: Record<string, string[]>
): string[] | undefined {
  const exact = optionsMap[paramId];
  if (exact && exact.length > 0) return exact;

  const parsed = parseParameterKey(paramId);
  if (!parsed) return undefined;

  // Fallback for subgraph-expanded ids:
  // if options are keyed by a sibling instance id, match by inner node id + input key.
  for (const [candidateKey, candidateOptions] of Object.entries(optionsMap)) {
    if (!candidateOptions || candidateOptions.length === 0) continue;
    const candidate = parseParameterKey(candidateKey);
    if (!candidate) continue;
    if (candidate.inputKey === parsed.inputKey && candidate.innerNodeId === parsed.innerNodeId) {
      return candidateOptions;
    }
  }

  // Last fallback: same input key regardless of node id.
  for (const [candidateKey, candidateOptions] of Object.entries(optionsMap)) {
    if (!candidateOptions || candidateOptions.length === 0) continue;
    const candidate = parseParameterKey(candidateKey);
    if (!candidate) continue;
    if (candidate.inputKey === parsed.inputKey) {
      return candidateOptions;
    }
  }
  return undefined;
}

function getParameterInputKey(paramId: string): string {
  const parsed = parseParameterKey(paramId);
  return parsed?.inputKey || paramId;
}

function getSubgraphInstanceKey(paramId: string): string {
  const parsed = parseParameterKey(paramId);
  if (!parsed) return "main";
  if (!parsed.nodeId.includes(":")) return "main";
  return parsed.nodeId.split(":", 1)[0] || "main";
}

function getSubgraphInstanceLabel(instanceKey: string): string {
  if (instanceKey === "main") return "Main Graph";
  return `Subgraph ${instanceKey}`;
}

function classifyParameter(
  param: InputParameterDefinition,
  promptParameterIds: Set<string>
): ParameterSectionId {
  if (promptParameterIds.has(param.id)) return "prompts";

  const inputKey = getParameterInputKey(param.id).toLowerCase();
  const haystack = `${param.label} ${inputKey} ${param.id}`.toLowerCase();

  if (inputKey === "asset_ref" || haystack.includes("bridge input")) return "bridge_inputs";
  if (
    haystack.includes("prompt") ||
    inputKey === "text" ||
    haystack.includes("positive") ||
    haystack.includes("negative")
  ) {
    return "prompts";
  }
  if (
    haystack.includes("seed") ||
    haystack.includes("steps") ||
    haystack.includes("cfg") ||
    haystack.includes("sampler") ||
    haystack.includes("scheduler") ||
    haystack.includes("denoise") ||
    haystack.includes("strength")
  ) {
    return "core_generation";
  }
  if (
    haystack.includes("checkpoint") ||
    haystack.includes("ckpt") ||
    haystack.includes("model") ||
    haystack.includes("unet") ||
    haystack.includes("clip") ||
    haystack.includes("vae") ||
    haystack.includes("lora")
  ) {
    return "models";
  }
  if (
    haystack.includes("width") ||
    haystack.includes("height") ||
    haystack.includes("fps") ||
    haystack.includes("frame") ||
    haystack.includes("length") ||
    haystack.includes("duration") ||
    haystack.includes("batch")
  ) {
    return "resolution_timing";
  }
  return "other";
}

function isParameterEdited(
  param: InputParameterDefinition,
  currentValue: string | number | undefined
): boolean {
  if (currentValue === undefined || param.default === undefined) return false;
  if (typeof currentValue === "number" || typeof param.default === "number") {
    return Number(currentValue) !== Number(param.default);
  }
  return String(currentValue) !== String(param.default);
}

function isSameWorkflowStructure(
  original: ComfyPrompt,
  edited: ComfyPrompt
): { valid: boolean; reason?: string } {
  const originalIds = Object.keys(original).sort();
  const editedIds = Object.keys(edited).sort();
  if (originalIds.length !== editedIds.length) {
    return { valid: false, reason: "Workflow changed: node count differs." };
  }
  for (let i = 0; i < originalIds.length; i += 1) {
    if (originalIds[i] !== editedIds[i]) {
      return { valid: false, reason: "Workflow changed: node IDs differ." };
    }
    const nodeId = originalIds[i];
    if (original[nodeId]?.class_type !== edited[nodeId]?.class_type) {
      return { valid: false, reason: `Workflow changed: node type differs for ${nodeId}.` };
    }
  }
  return { valid: true };
}

function diffParameterUpdates(
  original: ComfyPrompt,
  edited: ComfyPrompt,
  currentParameters: Record<string, string | number>
): Record<string, string | number> {
  const updates: Record<string, string | number> = {};
  const nodeIds = Object.keys(original);
  for (const nodeId of nodeIds) {
    const beforeInputs = original[nodeId]?.inputs || {};
    const afterInputs = edited[nodeId]?.inputs || {};
    const inputKeys = new Set([...Object.keys(beforeInputs), ...Object.keys(afterInputs)]);
    for (const inputKey of inputKeys) {
      const beforeValue = beforeInputs[inputKey];
      const afterValue = afterInputs[inputKey];
      if (JSON.stringify(beforeValue) === JSON.stringify(afterValue)) continue;

      const paramKey = `${nodeId}.${inputKey}`;
      if (!(paramKey in currentParameters)) continue;

      if (typeof afterValue === "string" || typeof afterValue === "number") {
        updates[paramKey] = afterValue;
      }
    }
  }
  return updates;
}

interface NodePropertiesPanelProps {
  nodeId: string;
  data: WorkflowNodeData;
  onClose: () => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  setNodes: (updater: (nodes: any[]) => any[]) => void;
  updateMode?: boolean;
  onUpdateParameters?: (nodeId: string, parameters: Record<string, unknown>) => Promise<void>;
}

// Cache for parameter options
const parameterOptionsCache: Record<string, Record<string, string[]>> = {};

export function NodePropertiesPanel({
  nodeId,
  data,
  onClose,
  setNodes,
  updateMode = false,
  onUpdateParameters,
}: NodePropertiesPanelProps) {
  const { label, color, definition, parameters, server } = data;
  const [isUpdating, setIsUpdating] = useState(false);
  const [parameterOptions, setParameterOptions] = useState<Record<string, string[]>>({});
  const [isLoadingOptions, setIsLoadingOptions] = useState(false);
  const [isComfyEditorOpen, setIsComfyEditorOpen] = useState(false);
  const [isOpeningComfyEditor, setIsOpeningComfyEditor] = useState(false);
  const [isApplyingComfyEdits, setIsApplyingComfyEdits] = useState(false);
  const [isOverwritingWorkflow, setIsOverwritingWorkflow] = useState(false);
  const [comfyEditorError, setComfyEditorError] = useState<string | null>(null);
  const [parameterPanelError, setParameterPanelError] = useState<string | null>(null);
  const [comfyBridgeStatus, setComfyBridgeStatus] = useState<string>("idle");
  const [comfyBaseUrl, setComfyBaseUrl] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [showChangedOnly, setShowChangedOnly] = useState(false);
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});
  const [collapsedSubgraphGroups, setCollapsedSubgraphGroups] = useState<Record<string, boolean>>({});
  const [propagateToPairMap, setPropagateToPairMap] = useState<Record<string, boolean>>({});
  const [removingParameterId, setRemovingParameterId] = useState<string | null>(null);
  const [templateWorkflow, setTemplateWorkflow] = useState<ComfyPrompt | null>(null);
  const exportActionRef = useRef<"apply-params" | "overwrite-template" | null>(null);
  const optionsRequestKeyRef = useRef<string | null>(null);
  const pingTimerRef = useRef<number | null>(null);
  const importSentRef = useRef(false);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const fetchNodeDefinitions = useNodeStore((state) => state.fetchWorkflows);
  const getComfyServerUrl = useComfyServerUrl();

  // Get servers from store
  const servers = useServerStore((state) => state.servers);
  const fetchServers = useServerStore((state) => state.fetchServers);

  // Fetch servers on mount
  useEffect(() => {
    if (servers.length === 0) {
      fetchServers();
    }
  }, [servers.length, fetchServers]);

  const selectedServer = useMemo(() => {
    if (server) {
      return servers.find((item) => item.name === server) || null;
    }
    return servers.length > 0 ? servers[0] : null;
  }, [server, servers]);

  // Determine which server to use for options (selected server or first available)
  const serverForOptions = selectedServer?.name || null;
  const comfyOrigin = useMemo(() => {
    if (!comfyBaseUrl) return null;
    try {
      return new URL(comfyBaseUrl).origin;
    } catch {
      return null;
    }
  }, [comfyBaseUrl]);
  const promptParameterIdSet = useMemo(
    () => new Set(definition.structureMetadata?.promptParameterIds || []),
    [definition.structureMetadata?.promptParameterIds]
  );
  const subgraphPairByInstance = useMemo(() => {
    const map = new Map<string, string>();
    const pairs = definition.structureMetadata?.subgraphPairs || [];
    for (const pair of pairs) {
      for (const instance of pair.instances) {
        map.set(instance, pair.key);
      }
    }
    return map;
  }, [definition.structureMetadata?.subgraphPairs]);
  const pairInstancesByPairKey = useMemo(() => {
    const map = new Map<string, Set<string>>();
    const pairs = definition.structureMetadata?.subgraphPairs || [];
    for (const pair of pairs) {
      map.set(pair.key, new Set(pair.instances));
    }
    return map;
  }, [definition.structureMetadata?.subgraphPairs]);
  const parameterIdByInstanceAndSignature = useMemo(() => {
    const map = new Map<string, string>();
    for (const param of definition.inputParameters) {
      const parsed = parseParameterKey(param.id);
      if (!parsed) continue;
      const instance = parsed.nodeId.includes(":") ? parsed.nodeId.split(":", 1)[0] : "main";
      const signature = `${parsed.innerNodeId}.${parsed.inputKey}`;
      map.set(`${instance}|${signature}`, param.id);
    }
    return map;
  }, [definition.inputParameters]);

  const groupedParameters = useMemo<ParameterSection[]>(() => {
    const query = searchQuery.trim().toLowerCase();
    const grouped = new Map<ParameterSectionId, ParameterSection>();
    for (const item of PARAMETER_SECTION_ORDER) {
      grouped.set(item.id, { id: item.id, label: item.label, params: [], editedCount: 0 });
    }

    for (const param of definition.inputParameters) {
      const currentValue = parameters[param.id];
      const edited = isParameterEdited(param, currentValue);
      if (showChangedOnly && !edited) continue;

      if (query) {
        const inputKey = getParameterInputKey(param.id).toLowerCase();
        const haystack = `${param.label} ${inputKey} ${param.id}`.toLowerCase();
        if (!haystack.includes(query)) continue;
      }

      const sectionId = classifyParameter(param, promptParameterIdSet);
      const section = grouped.get(sectionId);
      if (!section) continue;
      section.params.push(param);
      if (edited) section.editedCount += 1;
    }

    return PARAMETER_SECTION_ORDER
      .map((item) => grouped.get(item.id)!)
      .filter((section) => section.params.length > 0);
  }, [definition.inputParameters, parameters, promptParameterIdSet, searchQuery, showChangedOnly]);

  const totalVisibleParams = useMemo(
    () => groupedParameters.reduce((acc, section) => acc + section.params.length, 0),
    [groupedParameters]
  );

  const totalEditedVisible = useMemo(
    () => groupedParameters.reduce((acc, section) => acc + section.editedCount, 0),
    [groupedParameters]
  );

  // Fetch parameter options when workflow or server changes
  useEffect(() => {
    if (!serverForOptions || !data.type) {
      setParameterOptions({});
      return;
    }

    const cacheKey = `${data.type}:${serverForOptions}`;
    optionsRequestKeyRef.current = cacheKey;

    // Check cache first
    if (parameterOptionsCache[cacheKey]) {
      setParameterOptions(parameterOptionsCache[cacheKey]);
      setIsLoadingOptions(false);
      return;
    }

    // Clear stale options immediately when switching workflow/server.
    setParameterOptions({});

    let isCancelled = false;
    const fetchOptions = async () => {
      setIsLoadingOptions(true);
      try {
        const response = await fetch(
          `${GATEWAY_URL}/api/registry/v1/workflows/${encodeURIComponent(data.type)}/parameter-options/${encodeURIComponent(serverForOptions)}`
        );
        if (response.ok) {
          const result = await response.json();
          if (isCancelled || optionsRequestKeyRef.current !== cacheKey) {
            return;
          }
          parameterOptionsCache[cacheKey] = result.parameter_options;
          setParameterOptions(result.parameter_options);
        } else if (!isCancelled && optionsRequestKeyRef.current === cacheKey) {
          setParameterOptions({});
        }
      } catch (error) {
        console.error("Failed to fetch parameter options:", error);
        if (!isCancelled && optionsRequestKeyRef.current === cacheKey) {
          setParameterOptions({});
        }
      } finally {
        if (!isCancelled && optionsRequestKeyRef.current === cacheKey) {
          setIsLoadingOptions(false);
        }
      }
    };

    void fetchOptions();
    return () => {
      isCancelled = true;
    };
  }, [data.type, serverForOptions]);

  const postToComfyIframe = useCallback(
    (type: string, payload: Record<string, unknown> = {}) => {
      const iframeWindow = iframeRef.current?.contentWindow;
      if (!iframeWindow) return;
      iframeWindow.postMessage(
        {
          source: "graviton-host",
          type,
          payload,
        },
        comfyOrigin || "*"
      );
    },
    [comfyOrigin]
  );

  useEffect(() => {
    if (!isComfyEditorOpen) return;
    importSentRef.current = false;
    if (pingTimerRef.current !== null) {
      window.clearTimeout(pingTimerRef.current);
      pingTimerRef.current = null;
    }

    const requestPing = () => {
      postToComfyIframe("ping");
    };

    const handleBridgeMessage = (event: MessageEvent) => {
      if (comfyOrigin && event.origin !== comfyOrigin) return;
      if (event.source !== iframeRef.current?.contentWindow) return;

      const message = event.data as {
        source?: string;
        type?: string;
        payload?: {
          workflow?: ComfyPrompt;
          message?: string;
        };
      };
      if (message?.source !== "graviton-bridge") return;

      if (message.type === "ready") {
        console.log("[graviton-host] bridge ready", {
          origin: event.origin,
          payload: message.payload,
        });
        setComfyBridgeStatus("waiting-ready-pong");
        requestPing();
        return;
      }

      if (message.type === "pong") {
        console.log("[graviton-host] bridge pong", {
          origin: event.origin,
          payload: message.payload,
        });
        const ready = Boolean((message.payload as Record<string, unknown> | undefined)?.ready);
        if (ready) {
          if (!importSentRef.current && templateWorkflow) {
            importSentRef.current = true;
            setComfyBridgeStatus("importing");
            console.log("[graviton-host] sending import-workflow payload", {
              workflow: templateWorkflow,
            });
            postToComfyIframe("import-workflow", { workflow: templateWorkflow });
          }
        } else {
          setComfyBridgeStatus("waiting-ready-pong");
          if (pingTimerRef.current !== null) {
            window.clearTimeout(pingTimerRef.current);
          }
          pingTimerRef.current = window.setTimeout(() => {
            requestPing();
          }, 250);
        }
        return;
      }

      if (message.type === "workflow-imported") {
        setComfyBridgeStatus("imported");
        return;
      }

      if (message.type === "workflow-exported") {
        setIsApplyingComfyEdits(false);
        setIsOverwritingWorkflow(false);
        const exportedWorkflow = message.payload?.workflow;
        if (!templateWorkflow || !exportedWorkflow) {
          exportActionRef.current = null;
          setComfyEditorError("Missing workflow export from Comfy editor.");
          return;
        }

        if (exportActionRef.current === "overwrite-template") {
          void (async () => {
            try {
              const response = await fetch(
                `${GATEWAY_URL}/api/registry/v1/templates/${encodeURIComponent(data.type)}/workflow`,
                {
                  method: "PUT",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ workflow: exportedWorkflow }),
                }
              );
              if (!response.ok) {
                throw new Error(`Failed to overwrite template workflow: ${response.statusText}`);
              }

              await fetchNodeDefinitions();
              setTemplateWorkflow(exportedWorkflow);
              setComfyBridgeStatus("workflow-overwritten");
              setComfyEditorError(null);
              setIsComfyEditorOpen(false);
            } catch (error) {
              setComfyBridgeStatus("error");
              setComfyEditorError(
                error instanceof Error
                  ? error.message
                  : "Failed to overwrite template workflow."
              );
            } finally {
              setIsOverwritingWorkflow(false);
              exportActionRef.current = null;
            }
          })();
          return;
        }

        const structureCheck = isSameWorkflowStructure(templateWorkflow, exportedWorkflow);
        if (!structureCheck.valid) {
          exportActionRef.current = null;
          setComfyEditorError(structureCheck.reason || "Workflow was changed.");
          return;
        }

        const updates = diffParameterUpdates(templateWorkflow, exportedWorkflow, parameters);
        if (Object.keys(updates).length === 0) {
          exportActionRef.current = null;
          setComfyEditorError("No supported parameter changes were detected.");
          return;
        }

        setNodes((nodes) =>
          nodes.map((node) => {
            if (node.id !== nodeId) return node;
            return {
              ...node,
              data: {
                ...node.data,
                parameters: {
                  ...(node.data as unknown as WorkflowNodeData).parameters,
                  ...updates,
                },
              },
            };
          })
        );

        setComfyBridgeStatus("applied");
        setComfyEditorError(null);
        setIsComfyEditorOpen(false);
        exportActionRef.current = null;
        return;
      }

      if (message.type === "error") {
        setIsApplyingComfyEdits(false);
        setIsOverwritingWorkflow(false);
        exportActionRef.current = null;
        setComfyEditorError(message.payload?.message || "Comfy iframe bridge error.");
      }
    };

    window.addEventListener("message", handleBridgeMessage);
    return () => {
      if (pingTimerRef.current !== null) {
        window.clearTimeout(pingTimerRef.current);
        pingTimerRef.current = null;
      }
      window.removeEventListener("message", handleBridgeMessage);
    };
  }, [
    comfyOrigin,
    data.type,
    fetchNodeDefinitions,
    isComfyEditorOpen,
    nodeId,
    parameters,
    postToComfyIframe,
    setNodes,
    templateWorkflow,
  ]);

  const handleParameterChange = useCallback(
    (parameterId: string, value: string | number) => {
      setParameterPanelError(null);
      const targetParameterIds = new Set<string>([parameterId]);
      if (propagateToPairMap[parameterId]) {
        const parsed = parseParameterKey(parameterId);
        if (parsed) {
          const instance = parsed.nodeId.includes(":") ? parsed.nodeId.split(":", 1)[0] : "main";
          const pairKey = subgraphPairByInstance.get(instance);
          const pairInstances = pairKey ? pairInstancesByPairKey.get(pairKey) : undefined;
          if (pairInstances && pairInstances.size > 1) {
            const signature = `${parsed.innerNodeId}.${parsed.inputKey}`;
            for (const pairInstance of pairInstances) {
              if (pairInstance === instance) continue;
              const targetId = parameterIdByInstanceAndSignature.get(`${pairInstance}|${signature}`);
              if (targetId) targetParameterIds.add(targetId);
            }
          }
        }
      }

      setNodes((nodes) =>
        nodes.map((node) => {
          if (node.id === nodeId) {
            const nextParameters = {
              ...(node.data as unknown as WorkflowNodeData).parameters,
            };
            for (const targetId of targetParameterIds) {
              nextParameters[targetId] = value;
            }
            return {
              ...node,
              data: {
                ...node.data,
                parameters: nextParameters,
              },
            };
          }
          return node;
        })
      );
    },
    [
      nodeId,
      pairInstancesByPairKey,
      parameterIdByInstanceAndSignature,
      propagateToPairMap,
      setNodes,
      subgraphPairByInstance,
    ]
  );

  const toggleSection = useCallback((sectionId: ParameterSectionId) => {
    setCollapsedSections((prev) => ({ ...prev, [sectionId]: !prev[sectionId] }));
  }, []);

  const toggleSubgraphGroup = useCallback((groupKey: string) => {
    setCollapsedSubgraphGroups((prev) => ({ ...prev, [groupKey]: !prev[groupKey] }));
  }, []);

  const handleRemoveEditableParameter = useCallback(
    async (parameterId: string) => {
      if (updateMode) return;
      setParameterPanelError(null);
      const inputKey = getParameterInputKey(parameterId);
      const ok = window.confirm(
        `Remove '${inputKey}' from editable parameters for '${data.type}'?`
      );
      if (!ok) return;

      setRemovingParameterId(parameterId);
      try {
        const response = await fetch(
          `${GATEWAY_URL}/api/registry/v1/node-definitions/${encodeURIComponent(
            data.type
          )}/parameters/${encodeURIComponent(parameterId)}`,
          { method: "DELETE" }
        );
        if (!response.ok) {
          throw new Error(`Failed to remove parameter: ${response.statusText}`);
        }
        await fetchNodeDefinitions();
        setNodes((nodes) =>
          nodes.map((node) => {
            if (node.id !== nodeId) return node;
            const nextParams = { ...(node.data as unknown as WorkflowNodeData).parameters };
            delete nextParams[parameterId];
            return {
              ...node,
              data: {
                ...node.data,
                parameters: nextParams,
              },
            };
          })
        );
      } catch (error) {
        setParameterPanelError(error instanceof Error ? error.message : "Failed to remove parameter.");
      } finally {
        setRemovingParameterId(null);
      }
    },
    [data.type, fetchNodeDefinitions, nodeId, setNodes, updateMode]
  );

  const handleUpdateClick = useCallback(async () => {
    if (!onUpdateParameters) return;

    setIsUpdating(true);
    try {
      await onUpdateParameters(nodeId, parameters);
    } finally {
      setIsUpdating(false);
    }
  }, [nodeId, parameters, onUpdateParameters]);

  const handleOpenComfyEditor = useCallback(async () => {
    if (!selectedServer) {
      setComfyEditorError("No server available.");
      return;
    }
    setIsOpeningComfyEditor(true);
    importSentRef.current = false;
    exportActionRef.current = null;
    setComfyEditorError(null);
    setComfyBridgeStatus("loading-template");

    try {
      const response = await fetch(
        `${GATEWAY_URL}/api/registry/v1/templates/${encodeURIComponent(data.type)}/workflow`
      );
      if (!response.ok) {
        throw new Error(`Failed to load template workflow: ${response.statusText}`);
      }
      const payload = (await response.json()) as { workflow: ComfyPrompt };
      setTemplateWorkflow(payload.workflow);
      setComfyBaseUrl(getComfyServerUrl(selectedServer));
      setComfyBridgeStatus("waiting-iframe-ready");
      setIsComfyEditorOpen(true);
    } catch (error) {
      setComfyBridgeStatus("error");
      setComfyEditorError(error instanceof Error ? error.message : "Failed to open Comfy editor.");
    } finally {
      setIsOpeningComfyEditor(false);
    }
  }, [data.type, getComfyServerUrl, selectedServer]);

  const handleApplyComfyEdits = useCallback(() => {
    exportActionRef.current = "apply-params";
    setIsApplyingComfyEdits(true);
    setComfyBridgeStatus("exporting");
    setComfyEditorError(null);
    console.log("[graviton-host] sending export-workflow");
    postToComfyIframe("export-workflow");
  }, [postToComfyIframe]);

  const handleOverwriteTemplateWorkflow = useCallback(() => {
    exportActionRef.current = "overwrite-template";
    setIsOverwritingWorkflow(true);
    setComfyBridgeStatus("exporting-overwrite");
    setComfyEditorError(null);
    console.log("[graviton-host] sending export-workflow for overwrite");
    postToComfyIframe("export-workflow");
  }, [postToComfyIframe]);

  return (
    <>
    <div className="w-96 bg-[var(--surface-1)]/90 backdrop-blur-sm border-l border-[var(--border)] h-full overflow-y-auto overflow-x-hidden">
      {/* Header */}
      <div
        className="flex items-center gap-3 px-4 py-3 border-b border-[var(--border)] sticky top-0 bg-[var(--surface-1)]/95 backdrop-blur-sm z-10"
        style={{ backgroundColor: updateMode ? "rgba(59, 130, 246, 0.15)" : `${color}15` }}
      >
        <div
          className="flex items-center justify-center w-8 h-8 rounded text-lg"
          style={{ backgroundColor: updateMode ? "#3b82f6" : color }}
        >
          {updateMode ? (
            <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
          ) : (
            <span className="text-xs font-bold text-white">
              {label.slice(0, 2).toUpperCase()}
            </span>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-semibold text-[var(--text-primary)] truncate">
            {updateMode ? "Update Parameters" : label}
          </h2>
          {updateMode ? (
            <p className="text-xs text-blue-400">
              Modify parameters for pending step
            </p>
          ) : definition.group && (
            <p className="text-xs text-[var(--text-muted)]">
              {definition.group}
            </p>
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Loading indicator */}
      {isLoadingOptions && (
        <div className="px-4 py-2 text-xs text-[var(--text-muted)] flex items-center gap-2">
          <div className="w-3 h-3 border border-[var(--text-muted)] border-t-transparent rounded-full animate-spin" />
          Loading options...
        </div>
      )}

      {!updateMode && (
        <div className="px-4 pt-3">
          <button
            onClick={handleOpenComfyEditor}
            disabled={isOpeningComfyEditor || !selectedServer}
            className="w-full px-3 py-2 text-sm bg-[var(--surface-4)] hover:bg-[var(--surface-5)] text-[var(--text-primary)] border border-[var(--border)] rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isOpeningComfyEditor ? "Opening Comfy Editor..." : "Open In Comfy Editor"}
          </button>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            Server: {selectedServer?.name || "none"}
          </p>
        </div>
      )}

      {comfyEditorError && (
        <div className="mx-4 mt-3 rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          {comfyEditorError}
        </div>
      )}

      {parameterPanelError && (
        <div className="mx-4 mt-3 rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          {parameterPanelError}
        </div>
      )}

      {/* Parameters */}
      <div className="px-4 pt-3">
        <div className="sticky top-[57px] z-10 -mx-4 border-b border-[var(--border)] bg-[var(--surface-1)]/95 px-4 pb-3 pt-1 backdrop-blur-sm">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search editable parameters..."
            className="w-full rounded-md border border-[var(--border-1)] bg-[var(--surface-3)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-[var(--brand-secondary)] focus:outline-none"
          />
          <div className="mt-2 flex items-center justify-between text-xs text-[var(--text-muted)]">
            <label className="inline-flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showChangedOnly}
                onChange={(e) => setShowChangedOnly(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-[var(--border-1)] bg-[var(--surface-3)]"
              />
              Show changed only
            </label>
            <span>
              {totalVisibleParams} field{totalVisibleParams === 1 ? "" : "s"}
              {totalEditedVisible > 0 ? ` • ${totalEditedVisible} edited` : ""}
            </span>
          </div>
        </div>
      </div>

      <div className="p-4 pt-3 space-y-3">
        {groupedParameters.map((section) => (
          <div key={section.id} className="rounded-md border border-[var(--border)] bg-[var(--surface-2)]/60">
            <button
              type="button"
              onClick={() => toggleSection(section.id)}
              className="flex w-full items-center justify-between px-3 py-2 text-left"
            >
              <span className="text-xs font-semibold text-[var(--text-secondary)]">
                {section.label} ({section.params.length})
                {section.editedCount > 0 ? ` • ${section.editedCount} edited` : ""}
              </span>
              <span className="text-[var(--text-muted)]">
                {collapsedSections[section.id] ? "+" : "-"}
              </span>
            </button>

            {!collapsedSections[section.id] && (
              <div className="space-y-3 border-t border-[var(--border)] px-3 py-3">
                {(() => {
                  const byGroup = new Map<string, SubgraphGroup>();
                  for (const param of section.params) {
                    const groupKey = getSubgraphInstanceKey(param.id);
                    const group = byGroup.get(groupKey);
                    const edited = isParameterEdited(param, parameters[param.id]);
                    if (!group) {
                      const pairKey = subgraphPairByInstance.get(groupKey) || null;
                      const baseLabel = getSubgraphInstanceLabel(groupKey);
                      byGroup.set(groupKey, {
                        key: groupKey,
                        label: pairKey ? `${baseLabel} (paired)` : baseLabel,
                        pairKey,
                        params: [param],
                        editedCount: edited ? 1 : 0,
                      });
                    } else {
                      group.params.push(param);
                      if (edited) group.editedCount += 1;
                    }
                  }

                  const sortedGroups = Array.from(byGroup.values()).sort((a, b) => {
                    if (a.key === "main") return -1;
                    if (b.key === "main") return 1;
                    const an = Number(a.key);
                    const bn = Number(b.key);
                    if (!Number.isNaN(an) && !Number.isNaN(bn)) return an - bn;
                    return a.key.localeCompare(b.key);
                  });

                  return sortedGroups.map((group) => {
                    const groupCollapseKey = `${section.id}:${group.key}`;
                    return (
                      <div key={group.key} className="rounded-md border border-[var(--border)]/70 bg-[var(--surface-1)]/30">
                        <button
                          type="button"
                          onClick={() => toggleSubgraphGroup(groupCollapseKey)}
                          className="flex w-full items-center justify-between px-2.5 py-2 text-left"
                        >
                          <span className="text-[11px] font-semibold text-[var(--text-secondary)]">
                            {group.label} ({group.params.length})
                            {group.editedCount > 0 ? ` • ${group.editedCount} edited` : ""}
                          </span>
                          {group.pairKey && (
                            <span className="rounded bg-[var(--brand-secondary)]/15 px-1.5 py-0.5 text-[10px] text-[var(--brand-secondary)]">
                              {group.pairKey}
                            </span>
                          )}
                          <span className="text-[var(--text-muted)]">
                            {collapsedSubgraphGroups[groupCollapseKey] ? "+" : "-"}
                          </span>
                        </button>

                        {!collapsedSubgraphGroups[groupCollapseKey] && (
                          <div className="space-y-3 border-t border-[var(--border)]/60 px-2.5 py-3">
                            {group.params.map((param) => {
                              const options = resolveOptionsForParam(param.id, parameterOptions);
                              const hasOptions = options && options.length > 0;
                              const edited = isParameterEdited(param, parameters[param.id]);
                              const inputKey = getParameterInputKey(param.id);
                              const isRemoving = removingParameterId === param.id;
                              const parsedParam = parseParameterKey(param.id);
                              const paramInstance = parsedParam?.nodeId.includes(":")
                                ? parsedParam.nodeId.split(":", 1)[0]
                                : "main";
                              const paramPairKey = paramInstance
                                ? subgraphPairByInstance.get(paramInstance) || null
                                : null;
                              const isPairPropagationAvailable = Boolean(paramPairKey);
                              const isPropagateChecked = Boolean(propagateToPairMap[param.id]);

                              return (
                                <div
                                  key={param.id}
                                  className={`rounded-md border p-2 ${
                                    edited
                                      ? "border-[var(--brand-secondary)]/60 bg-[var(--brand-secondary)]/10"
                                      : "border-transparent"
                                  }`}
                                >
                                  <div className="mb-1.5 flex items-center justify-between gap-2">
                                    <label
                                      className="block text-xs font-medium text-[var(--text-secondary)] truncate"
                                      title={param.label}
                                    >
                                      <span className="truncate">{param.label}</span>
                                      {hasOptions && (
                                        <span className="ml-1 text-[var(--text-muted)] whitespace-nowrap">
                                          ({options.length})
                                        </span>
                                      )}
                                    </label>
                                    <div className="flex items-center gap-2">
                                      {edited && (
                                        <span className="rounded bg-[var(--brand-secondary)]/20 px-1.5 py-0.5 text-[10px] text-[var(--brand-secondary)]">
                                          edited
                                        </span>
                                      )}
                                      {!updateMode && (
                                        <button
                                          type="button"
                                          onClick={() => void handleRemoveEditableParameter(param.id)}
                                          disabled={isRemoving}
                                          className="rounded border border-red-500/30 px-1.5 py-0.5 text-[10px] text-red-300 hover:bg-red-500/10 disabled:opacity-50"
                                          title="Remove from editable parameters"
                                        >
                                          {isRemoving ? "Removing..." : "Remove"}
                                        </button>
                                      )}
                                    </div>
                                  </div>

                                  <div className="mb-2 text-[10px] text-[var(--text-muted)]" title={param.id}>
                                    {param.id}
                                  </div>
                                  {isPairPropagationAvailable && (
                                    <label className="mb-2 inline-flex cursor-pointer items-center gap-2 text-[10px] text-[var(--text-muted)]">
                                      <input
                                        type="checkbox"
                                        checked={isPropagateChecked}
                                        onChange={(e) =>
                                          setPropagateToPairMap((prev) => ({
                                            ...prev,
                                            [param.id]: e.target.checked,
                                          }))
                                        }
                                        className="h-3.5 w-3.5 rounded border-[var(--border-1)] bg-[var(--surface-3)]"
                                      />
                                      Propagate to all paired subgraphs
                                    </label>
                                  )}

                                  {hasOptions ? (
                                    <select
                                      value={(parameters[param.id] as string) || ""}
                                      onChange={(e) => handleParameterChange(param.id, e.target.value)}
                                      className="w-full px-3 py-2 text-sm bg-[var(--surface-3)] border border-[var(--border-1)] rounded-md text-[var(--text-primary)] focus:outline-none focus:border-[var(--brand-secondary)] truncate"
                                      title={(parameters[param.id] as string) || ""}
                                    >
                                      <option value="">Select {inputKey}...</option>
                                      {options.map((option) => (
                                        <option
                                          key={option}
                                          value={option}
                                          title={option}
                                          className="truncate max-w-full"
                                        >
                                          {option.length > 50 ? option.slice(0, 47) + "..." : option}
                                        </option>
                                      ))}
                                    </select>
                                  ) : (
                                    <>
                                      {param.type === "textarea" && (
                                        <textarea
                                          value={(parameters[param.id] as string) || ""}
                                          onChange={(e) => handleParameterChange(param.id, e.target.value)}
                                          placeholder={param.placeholder}
                                          rows={3}
                                          className="w-full px-3 py-2 text-sm bg-[var(--surface-3)] border border-[var(--border-1)] rounded-md text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--brand-secondary)] resize-none"
                                        />
                                      )}

                                      {param.type === "text" && (
                                        <input
                                          type="text"
                                          value={(parameters[param.id] as string) || ""}
                                          onChange={(e) => handleParameterChange(param.id, e.target.value)}
                                          placeholder={param.placeholder}
                                          className="w-full px-3 py-2 text-sm bg-[var(--surface-3)] border border-[var(--border-1)] rounded-md text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--brand-secondary)]"
                                        />
                                      )}

                                      {param.type === "number" && (
                                        <input
                                          type="number"
                                          value={(parameters[param.id] as number) ?? param.default ?? 0}
                                          onChange={(e) =>
                                            handleParameterChange(param.id, parseFloat(e.target.value) || 0)
                                          }
                                          className="w-full px-3 py-2 text-sm bg-[var(--surface-3)] border border-[var(--border-1)] rounded-md text-[var(--text-primary)] focus:outline-none focus:border-[var(--brand-secondary)]"
                                        />
                                      )}
                                    </>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  });
                })()}
              </div>
            )}
          </div>
        ))}

        {groupedParameters.length === 0 && (
          <p className="text-sm text-[var(--text-muted)] text-center py-4">
            {definition.inputParameters.length === 0
              ? "No editable parameters"
              : "No parameters matched your filters"}
          </p>
        )}

        {/* Update button when in update mode */}
        {updateMode && onUpdateParameters && (
          <div className="pt-4 mt-4 border-t border-[var(--border)]">
            <button
              onClick={handleUpdateClick}
              disabled={isUpdating}
              className="w-full px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {isUpdating ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Updating...
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                  Update Parameters
                </>
              )}
            </button>
            <p className="mt-2 text-xs text-[var(--text-muted)] text-center">
              Send updated parameters to the running workflow
            </p>
          </div>
        )}
      </div>
    </div>
    {isComfyEditorOpen && comfyBaseUrl && (
      <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-[1px] p-6">
        <div className="mx-auto flex h-full w-full max-w-[1400px] flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface-2)] shadow-2xl">
          <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
            <div>
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">Comfy Editor</h3>
              <p className="text-xs text-[var(--text-muted)]">
                {selectedServer?.name} • {comfyBridgeStatus}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={handleOverwriteTemplateWorkflow}
                disabled={isApplyingComfyEdits || isOverwritingWorkflow}
                className="rounded-md bg-[var(--brand-secondary)] px-3 py-1.5 text-sm text-white hover:opacity-90 disabled:opacity-50"
              >
                {isOverwritingWorkflow ? "Overwriting..." : "Overwrite Workflow"}
              </button>
              <button
                onClick={handleApplyComfyEdits}
                disabled={isApplyingComfyEdits || isOverwritingWorkflow}
                className="rounded-md bg-[var(--brand-success)] px-3 py-1.5 text-sm text-white hover:opacity-90 disabled:opacity-50"
              >
                {isApplyingComfyEdits ? "Applying..." : "Apply Parameter Edits"}
              </button>
              <button
                onClick={() => {
                  setIsComfyEditorOpen(false);
                  setIsApplyingComfyEdits(false);
                  setIsOverwritingWorkflow(false);
                  exportActionRef.current = null;
                }}
                className="rounded-md bg-[var(--surface-4)] px-3 py-1.5 text-sm text-[var(--text-primary)] hover:bg-[var(--surface-5)]"
              >
                Close
              </button>
            </div>
          </div>
          <iframe
            ref={iframeRef}
            title="Comfy Editor"
            src={comfyBaseUrl}
            className="h-full w-full border-0"
            allow="clipboard-read; clipboard-write"
          />
        </div>
      </div>
    )}
    </>
  );
}
