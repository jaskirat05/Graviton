"use client";

/**
 * NodePropertiesPanel - Side panel for editing selected node's parameters
 * Shows dropdowns for parameters with available options from the server
 */

import { useCallback, useState, useEffect } from "react";
import { useServerStore } from "@/stores/serverStore";
import type { WorkflowNodeData, InputParameterDefinition } from "./types";

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

  // Get servers from store
  const servers = useServerStore((state) => state.servers);
  const fetchServers = useServerStore((state) => state.fetchServers);

  // Fetch servers on mount
  useEffect(() => {
    if (servers.length === 0) {
      fetchServers();
    }
  }, [servers.length, fetchServers]);

  // Determine which server to use for options (selected server or first available)
  const serverForOptions = server || (servers.length > 0 ? servers[0].name : null);

  // Fetch parameter options when workflow or server changes
  useEffect(() => {
    if (!serverForOptions || !data.type) return;

    const cacheKey = `${data.type}:${serverForOptions}`;

    // Check cache first
    if (parameterOptionsCache[cacheKey]) {
      setParameterOptions(parameterOptionsCache[cacheKey]);
      return;
    }

    const fetchOptions = async () => {
      setIsLoadingOptions(true);
      try {
        const response = await fetch(
          `http://localhost:8001/workflows/${encodeURIComponent(data.type)}/parameter-options/${encodeURIComponent(serverForOptions)}`
        );
        if (response.ok) {
          const result = await response.json();
          parameterOptionsCache[cacheKey] = result.parameter_options;
          setParameterOptions(result.parameter_options);
        }
      } catch (error) {
        console.error("Failed to fetch parameter options:", error);
      } finally {
        setIsLoadingOptions(false);
      }
    };

    fetchOptions();
  }, [data.type, serverForOptions]);

  const handleParameterChange = useCallback(
    (parameterId: string, value: string | number) => {
      setNodes((nodes) =>
        nodes.map((node) => {
          if (node.id === nodeId) {
            return {
              ...node,
              data: {
                ...node.data,
                parameters: {
                  ...(node.data as unknown as WorkflowNodeData).parameters,
                  [parameterId]: value,
                },
              },
            };
          }
          return node;
        })
      );
    },
    [nodeId, setNodes]
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

  return (
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

      {/* Parameters */}
      <div className="p-4 space-y-4">
        {definition.inputParameters.map((param: InputParameterDefinition) => {
          const options = parameterOptions[param.id];
          const hasOptions = options && options.length > 0;

          return (
            <div key={param.id}>
              <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1.5 truncate" title={param.label}>
                <span className="truncate">{param.label}</span>
                {hasOptions && (
                  <span className="ml-1 text-[var(--text-muted)] whitespace-nowrap">
                    ({options.length})
                  </span>
                )}
              </label>

              {/* Dropdown for parameters with options */}
              {hasOptions ? (
                <select
                  value={(parameters[param.id] as string) || ""}
                  onChange={(e) => handleParameterChange(param.id, e.target.value)}
                  className="w-full px-3 py-2 text-sm bg-[var(--surface-3)] border border-[var(--border-1)] rounded-md text-[var(--text-primary)] focus:outline-none focus:border-[var(--brand-secondary)] truncate"
                  title={(parameters[param.id] as string) || ""}
                >
                  <option value="">Select {param.label}...</option>
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
                      onChange={(e) => handleParameterChange(param.id, parseFloat(e.target.value) || 0)}
                      className="w-full px-3 py-2 text-sm bg-[var(--surface-3)] border border-[var(--border-1)] rounded-md text-[var(--text-primary)] focus:outline-none focus:border-[var(--brand-secondary)]"
                    />
                  )}
                </>
              )}
            </div>
          );
        })}

        {definition.inputParameters.length === 0 && (
          <p className="text-sm text-[var(--text-muted)] text-center py-4">
            No editable parameters
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
  );
}
