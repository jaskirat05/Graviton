"use client";

/**
 * WorkflowNode - Node component for visual workflow editor
 * Shows execution status, progress, output preview, and approval UI
 */

import { memo, useState } from "react";
import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import { useExecutionStore, type StepStatus } from "@/stores/executionStore";
import { approveStep, rejectStep } from "@/hooks/useChainEvents";
import type { WorkflowNodeData, InputSocketDefinition, OutputSocketDefinition, InputParameterDefinition } from "./types";

type WorkflowNodeType = Node<WorkflowNodeData & Record<string, unknown>>;

function WorkflowNodeComponent({ id, data, selected }: NodeProps<WorkflowNodeType>) {
  const { label, icon, color, definition, parameters } = data as WorkflowNodeData;

  // Get execution state for this node
  const stepExecution = useExecutionStore((state) => state.getStepExecution(id));
  const pendingApproval = useExecutionStore((state) => state.getPendingApproval(id));
  const onApprovalResolved = useExecutionStore((state) => state.onApprovalResolved);

  // Local state for approval actions
  const [isApproving, setIsApproving] = useState(false);
  const [approvalError, setApprovalError] = useState<string | null>(null);

  // Truncate long text for preview
  const truncate = (text: string, maxLength: number = 50) => {
    if (!text || text.length <= maxLength) return text;
    return text.slice(0, maxLength) + "...";
  };

  // Format value for display
  const formatValue = (value: string | number | undefined) => {
    if (value === undefined || value === "") {
      return <span className="text-[var(--text-muted)] italic">Not set</span>;
    }
    if (typeof value === "string") {
      return truncate(value);
    }
    return String(value);
  };

  // Get status styles
  const getStatusStyles = (status?: StepStatus) => {
    switch (status) {
      case "executing":
        return { border: "border-blue-500", bg: "bg-blue-500/10", icon: "⚡" };
      case "waiting_approval":
        return { border: "border-yellow-500", bg: "bg-yellow-500/10", icon: "⏳" };
      case "completed":
        return { border: "border-green-500", bg: "bg-green-500/10", icon: "✓" };
      case "failed":
        return { border: "border-red-500", bg: "bg-red-500/10", icon: "✗" };
      default:
        return { border: "", bg: "", icon: "" };
    }
  };

  const statusStyles = getStatusStyles(stepExecution?.status);

  // Handle approve
  const handleApprove = async () => {
    if (!pendingApproval) return;
    setIsApproving(true);
    setApprovalError(null);
    try {
      await approveStep(pendingApproval.token);
      onApprovalResolved(id);
    } catch (e) {
      setApprovalError(e instanceof Error ? e.message : "Failed to approve");
    } finally {
      setIsApproving(false);
    }
  };

  // Handle reject
  const handleReject = async () => {
    if (!pendingApproval) return;
    setIsApproving(true);
    setApprovalError(null);
    try {
      await rejectStep(pendingApproval.token);
      onApprovalResolved(id);
    } catch (e) {
      setApprovalError(e instanceof Error ? e.message : "Failed to reject");
    } finally {
      setIsApproving(false);
    }
  };

  return (
    <div
      className={`
        relative w-[240px] rounded-lg border bg-[var(--surface-2)]
        transition-all duration-150 cursor-pointer
        ${selected ? "border-[var(--brand-secondary)] shadow-lg ring-2 ring-[var(--brand-secondary)]/30" : "border-[var(--border-1)] hover:border-[var(--border-2)]"}
        ${stepExecution?.status ? statusStyles.border : ""}
      `}
    >
      {/* Status indicator */}
      {stepExecution?.status && stepExecution.status !== "idle" && (
        <div className={`absolute -top-2 -right-2 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${statusStyles.bg} border ${statusStyles.border}`}>
          {statusStyles.icon}
        </div>
      )}

      {/* Header */}
      <div
        className="flex items-center gap-2 px-3 py-2 border-b border-[var(--border)]"
        style={{ backgroundColor: `${color}10` }}
      >
        <div
          className="flex items-center justify-center w-7 h-7 rounded text-sm flex-shrink-0"
          style={{ backgroundColor: color }}
        >
          {icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-[var(--text-primary)] truncate">
            {label}
          </div>
          {definition.group && (
            <div className="text-[10px] text-[var(--text-muted)] truncate">
              {definition.group}
            </div>
          )}
        </div>
      </div>

      {/* Progress bar during execution */}
      {stepExecution?.status === "executing" && (
        <div className="px-3 py-2 border-b border-[var(--border)]">
          <div className="flex items-center gap-2 text-[10px] text-[var(--text-muted)]">
            <span className="animate-pulse">Executing...</span>
            {stepExecution.currentNode && (
              <span className="truncate">Node: {stepExecution.currentNode}</span>
            )}
          </div>
          <div className="mt-1 h-1 bg-[var(--surface-4)] rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 transition-all duration-300"
              style={{ width: `${(stepExecution.progress || 0) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Error display */}
      {stepExecution?.status === "failed" && stepExecution.error && (
        <div className="px-3 py-2 border-b border-[var(--border)] bg-red-500/10">
          <div className="text-[10px] text-red-400 truncate" title={stepExecution.error}>
            {stepExecution.error}
          </div>
        </div>
      )}

      {/* Output preview */}
      {stepExecution?.artifactUrl && (stepExecution.status === "completed" || stepExecution.status === "waiting_approval") && (
        <div className="px-3 py-2 border-b border-[var(--border)]">
          <div className="text-[10px] text-[var(--text-muted)] mb-1">Output</div>
          <div className="relative w-full h-24 bg-[var(--surface-3)] rounded overflow-hidden">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={stepExecution.artifactUrl}
              alt="Output preview"
              className="w-full h-full object-contain"
              onError={(e) => {
                // Hide image on error (might be a video)
                e.currentTarget.style.display = "none";
              }}
            />
          </div>
        </div>
      )}

      {/* Approval UI */}
      {stepExecution?.status === "waiting_approval" && pendingApproval && (
        <div className="px-3 py-2 border-b border-[var(--border)] bg-yellow-500/10">
          <div className="text-[10px] text-yellow-400 mb-2">Awaiting Approval</div>
          <div className="flex gap-2">
            <button
              onClick={handleApprove}
              disabled={isApproving}
              className="flex-1 px-2 py-1 text-[10px] bg-green-600 hover:bg-green-700 text-white rounded disabled:opacity-50"
            >
              {isApproving ? "..." : "Approve"}
            </button>
            <button
              onClick={handleReject}
              disabled={isApproving}
              className="flex-1 px-2 py-1 text-[10px] bg-red-600 hover:bg-red-700 text-white rounded disabled:opacity-50"
            >
              {isApproving ? "..." : "Reject"}
            </button>
          </div>
          {approvalError && (
            <div className="mt-1 text-[9px] text-red-400">{approvalError}</div>
          )}
        </div>
      )}

      {/* Sockets section - inputs left, outputs right */}
      {(definition.inputs.length > 0 || definition.outputs.length > 0) && (
        <div className="px-3 py-2 flex justify-between text-[10px] text-[var(--text-muted)]">
          {/* Input sockets with labels */}
          <div className="space-y-1">
            {definition.inputs.map((input: InputSocketDefinition) => (
              <div key={input.id} className="flex items-center gap-1 h-5 relative">
                <Handle
                  type="target"
                  position={Position.Left}
                  id={input.id}
                  style={{
                    position: "absolute",
                    left: -20,
                    top: "50%",
                    transform: "translateY(-50%)",
                    width: 12,
                    height: 12,
                    background: getSocketColor(input.type),
                    border: "2px solid var(--surface-2)",
                    cursor: "crosshair",
                  }}
                />
                <div
                  className="w-1.5 h-1.5 rounded-full"
                  style={{ backgroundColor: getSocketColor(input.type) }}
                />
                <span>{input.label}</span>
              </div>
            ))}
          </div>

          {/* Output sockets with labels */}
          <div className="space-y-1 text-right">
            {definition.outputs.map((output: OutputSocketDefinition) => (
              <div key={output.id} className="flex items-center justify-end gap-1 h-5 relative">
                <span>{output.label}</span>
                <div
                  className="w-1.5 h-1.5 rounded-full"
                  style={{ backgroundColor: getSocketColor(output.type) }}
                />
                <Handle
                  type="source"
                  position={Position.Right}
                  id={output.id}
                  style={{
                    position: "absolute",
                    right: -20,
                    top: "50%",
                    transform: "translateY(-50%)",
                    width: 12,
                    height: 12,
                    background: getSocketColor(output.type),
                    border: "2px solid var(--surface-2)",
                    cursor: "crosshair",
                  }}
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Parameter values preview (only when not executing) */}
      {(!stepExecution || stepExecution.status === "idle") && definition.inputParameters.length > 0 && (
        <div className="px-3 py-2 border-t border-[var(--border)] space-y-1.5">
          {definition.inputParameters.slice(0, 4).map((param: InputParameterDefinition) => (
            <div key={param.id} className="flex flex-col">
              <span className="text-[9px] uppercase tracking-wide text-[var(--text-muted)]">
                {param.label.length > 30 ? param.label.slice(0, 30) + "..." : param.label}
              </span>
              <span className="text-xs text-[var(--text-secondary)] truncate">
                {formatValue(parameters[param.id] as string | number | undefined)}
              </span>
            </div>
          ))}
          {definition.inputParameters.length > 4 && (
            <div className="text-[10px] text-[var(--text-muted)]">
              +{definition.inputParameters.length - 4} more...
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function getSocketColor(type: string): string {
  switch (type) {
    case "image":
      return "#22c55e"; // green
    case "video":
      return "#3b82f6"; // blue
    default:
      return "#6b7280"; // gray
  }
}

export const WorkflowNode = memo(WorkflowNodeComponent);
