"use client";

/**
 * WorkflowNode - Node component for visual workflow editor
 * Shows execution status, progress, output preview, approval UI, and server selection
 */

import { memo, useState, useEffect } from "react";
import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import { useExecutionStore, type StepStatus } from "@/stores/executionStore";
import { useServerStore } from "@/stores/serverStore";
import { approveStep, rejectStep } from "@/hooks/useChainEvents";
import { VideoPlayer } from "@/components/ui/VideoPlayer";
import type { WorkflowNodeData, InputSocketDefinition, OutputSocketDefinition, InputParameterDefinition } from "./types";

type WorkflowNodeType = Node<WorkflowNodeData & Record<string, unknown>>;

function WorkflowNodeComponent({ id, data, selected }: NodeProps<WorkflowNodeType>) {
  const { label, color, definition, parameters, server, serverValidation } = data as WorkflowNodeData;

  // Get execution state for this node
  const execution = useExecutionStore((state) => state.execution);
  const stepExecution = useExecutionStore((state) => state.getStepExecution(id));
  const pendingApproval = useExecutionStore((state) => state.getPendingApproval(id));
  const onApprovalResolved = useExecutionStore((state) => state.onApprovalResolved);
  const requestUpdateMode = useExecutionStore((state) => state.requestUpdateMode);

  // Server store
  const servers = useServerStore((state) => state.servers);
  const fetchServers = useServerStore((state) => state.fetchServers);
  const validateWorkflowServer = useServerStore((state) => state.validateWorkflowServer);

  // Fetch servers on mount
  useEffect(() => {
    if (servers.length === 0) {
      fetchServers();
    }
  }, [servers.length, fetchServers]);

  // Check if this node can have its parameters updated (pending execution)
  const canUpdate = execution?.status === "running" &&
    (!stepExecution || stepExecution.status === "idle");

  // Local state for approval actions
  const [isApproving, setIsApproving] = useState(false);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [isValidating, setIsValidating] = useState(false);

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
        className="px-3 py-2 border-b border-[var(--border)]"
        style={{ backgroundColor: `${color}10` }}
      >
        <div className="text-sm font-medium text-[var(--text-primary)] truncate">
          {label}
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
            {definition.outputs[0]?.type === "video" ? (
              <VideoPlayer
                url={stepExecution.artifactUrl}
                className="w-full h-full"
              />
            ) : (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img
                src={stepExecution.artifactUrl}
                alt="Output preview"
                className="w-full h-full object-contain"
              />
            )}
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

      {/* Update button for pending nodes during execution */}
      {canUpdate && (
        <div className="px-3 py-2 border-t border-[var(--border)]">
          <button
            onClick={(e) => {
              e.stopPropagation();
              requestUpdateMode(id);
            }}
            className="w-full px-2 py-1.5 text-xs bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors flex items-center justify-center gap-1"
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
            Update Parameters
          </button>
        </div>
      )}

      {/* Server selection */}
      <div className="px-3 py-2 border-t border-[var(--border)]">
        <div className="text-[9px] uppercase tracking-wide text-[var(--text-muted)] mb-1">
          Server
        </div>
        <select
          value={server || ""}
          onChange={async (e) => {
            const selectedServer = e.target.value || undefined;
            // Update node data - this will be handled by parent
            const event = new CustomEvent("nodeServerChange", {
              detail: { nodeId: id, server: selectedServer },
            });
            window.dispatchEvent(event);

            // Validate if server selected
            if (selectedServer) {
              setIsValidating(true);
              const result = await validateWorkflowServer(data.type, selectedServer);
              // Dispatch validation result
              const validationEvent = new CustomEvent("nodeServerValidation", {
                detail: { nodeId: id, validation: result },
              });
              window.dispatchEvent(validationEvent);
              setIsValidating(false);
            }
          }}
          onClick={(e) => e.stopPropagation()}
          className="w-full px-2 py-1 text-xs bg-[var(--surface-3)] border border-[var(--border)] rounded text-[var(--text-primary)] focus:outline-none focus:border-[var(--brand-secondary)]"
        >
          <option value="">Auto (Load Balanced)</option>
          {servers.map((s) => (
            <option key={s.name} value={s.name}>
              {s.name} ({s.node_count} nodes)
            </option>
          ))}
        </select>
        {isValidating && (
          <div className="mt-1 text-[9px] text-blue-400">Validating...</div>
        )}
        {serverValidation && !serverValidation.valid && (
          <div className="mt-1 text-[9px] text-yellow-400" title={serverValidation.error}>
            ⚠ {serverValidation.error || "Server may not support this workflow"}
          </div>
        )}
        {serverValidation?.valid && server && (
          <div className="mt-1 text-[9px] text-green-400">✓ Validated</div>
        )}
      </div>

      {/* Output type strip at bottom */}
      {definition.outputs.length > 0 && (
        <div
          className="flex items-center justify-center gap-2 px-3 py-1.5 text-[10px] font-medium uppercase tracking-wider rounded-b-lg"
          style={{ backgroundColor: getSocketColor(definition.outputs[0].type) }}
        >
          {definition.outputs.map((output: OutputSocketDefinition, idx: number) => (
            <span key={output.id} className="text-white">
              {idx > 0 && <span className="mr-2">•</span>}
              {output.type}
            </span>
          ))}
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
