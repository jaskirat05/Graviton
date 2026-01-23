"use client";

/**
 * NodePropertiesPanel - Side panel for editing selected node's parameters
 */

import { useCallback } from "react";
import type { WorkflowNodeData, InputParameterDefinition } from "./types";

interface NodePropertiesPanelProps {
  nodeId: string;
  data: WorkflowNodeData;
  onClose: () => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  setNodes: (updater: (nodes: any[]) => any[]) => void;
}

export function NodePropertiesPanel({ nodeId, data, onClose, setNodes }: NodePropertiesPanelProps) {
  const { label, icon, color, definition, parameters } = data;

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

  return (
    <div className="w-80 bg-[var(--surface-1)] border-r border-[var(--border)] h-full overflow-auto">
      {/* Header */}
      <div
        className="flex items-center gap-3 px-4 py-3 border-b border-[var(--border)]"
        style={{ backgroundColor: `${color}15` }}
      >
        <div
          className="flex items-center justify-center w-8 h-8 rounded text-lg"
          style={{ backgroundColor: color }}
        >
          {icon}
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-semibold text-[var(--text-primary)] truncate">
            {label}
          </h2>
          {definition.group && (
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

      {/* Parameters */}
      <div className="p-4 space-y-4">
        {definition.inputParameters.map((param: InputParameterDefinition) => (
          <div key={param.id}>
            <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1.5">
              {param.label}
            </label>

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
          </div>
        ))}

        {definition.inputParameters.length === 0 && (
          <p className="text-sm text-[var(--text-muted)] text-center py-4">
            No editable parameters
          </p>
        )}
      </div>
    </div>
  );
}
