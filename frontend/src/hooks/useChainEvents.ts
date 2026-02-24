/**
 * useChainEvents - Hook to subscribe to chain execution SSE events
 */

import { useEffect, useRef, useCallback } from "react";
import { useExecutionStore } from "@/stores/executionStore";
import { useLevelWaitStore } from "@/hooks/useLevelWait";

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:8001";

interface ChainEventData {
  type: string;
  chain_id?: string;
  step_id?: string;
  workflow?: string;
  server?: string;
  node_id?: string;
  node_name?: string;
  progress?: number;
  output_count?: number;
  error?: string;
  error_type?: string;
  error_message?: string;
  node_errors?: unknown;
  token?: string;
  artifact_url?: string;
  artifact_id?: string;
  cache_key?: string;
  level_num?: number;
  wait_seconds?: number;
  skipped?: boolean;
}

function toErrorText(value: unknown, fallback: string): string {
  if (typeof value === "string" && value.trim().length > 0) return value;
  if (value === null || value === undefined) return fallback;
  try {
    return JSON.stringify(value);
  } catch {
    return fallback;
  }
}

function formatNodeErrors(nodeErrors: unknown): string {
  if (!nodeErrors || typeof nodeErrors !== "object") return "";
  const entries = Object.entries(nodeErrors as Record<string, unknown>);
  if (entries.length === 0) return "";

  const lines: string[] = [];
  for (const [nodeId, raw] of entries.slice(0, 10)) {
    if (!raw || typeof raw !== "object") {
      lines.push(`- Node ${nodeId}: validation failed`);
      continue;
    }

    const payload = raw as { class_type?: unknown; errors?: unknown };
    const classType =
      typeof payload.class_type === "string" ? payload.class_type : "unknown";
    const errors = Array.isArray(payload.errors) ? payload.errors : [];

    if (errors.length === 0) {
      lines.push(`- Node ${nodeId} (${classType}): validation failed`);
      continue;
    }

    for (const err of errors.slice(0, 3)) {
      if (!err || typeof err !== "object") {
        lines.push(`- Node ${nodeId} (${classType}): validation failed`);
        continue;
      }
      const e = err as { type?: unknown; message?: unknown; details?: unknown };
      const type = typeof e.type === "string" ? e.type : "validation_error";
      const message = typeof e.message === "string" ? e.message : "Validation failed";
      const details = typeof e.details === "string" ? e.details : "";
      lines.push(
        `- Node ${nodeId} (${classType}) [${type}]: ${message}${details ? ` (${details})` : ""}`
      );
    }
  }

  return lines.join("\n");
}

export function useChainEvents(chainId: string | null) {
  const eventSourceRef = useRef<EventSource | null>(null);
  const cancelTriggeredRef = useRef(false);

  const {
    onStepExecuting,
    onStepNode,
    onStepWorkflowComplete,
    onStepWorkflowFailed,
    onStepValidationFailed,
    onStepCached,
    onStepCompleted,
    onApprovalRequested,
    onChainCompleted,
    onChainFailed,
    cancelChain,
  } = useExecutionStore();

  const { startWait, endWait } = useLevelWaitStore();

  const handleEvent = useCallback((event: MessageEvent) => {
    try {
      const data: ChainEventData = JSON.parse(event.data);
      const eventType = data.type;

      console.log("[SSE Event]", eventType, data);

      switch (eventType) {
        case "step_executing":
          if (data.step_id) {
            onStepExecuting(data.step_id, data.workflow || "", data.server || "");
          }
          break;

        case "step_node":
          if (data.step_id) {
            onStepNode(data.step_id, data.node_id || "", data.node_name, data.progress);
          }
          break;

        case "step_workflow_complete":
          if (data.step_id) {
            onStepWorkflowComplete(data.step_id, data.output_count || 0);
          }
          break;

        case "step_workflow_failed":
          if (data.step_id) {
            onStepWorkflowFailed(
              data.step_id,
              toErrorText(data.error, "Unknown error"),
              data.node_id,
              data.node_name
            );
            if (chainId && !cancelTriggeredRef.current) {
              cancelTriggeredRef.current = true;
              void cancelChain(chainId).catch((e) => {
                console.error("Auto-cancel failed after step_workflow_failed:", e);
              });
            }
          }
          break;

        case "step_validation_failed":
          if (data.step_id) {
            const baseMessage = toErrorText(
              data.error_message,
              "Unknown validation error"
            );
            const nodeDetails = formatNodeErrors(data.node_errors);
            const fullMessage = nodeDetails
              ? `${baseMessage}\n\nNode details:\n${nodeDetails}`
              : baseMessage;
            onStepValidationFailed(
              data.step_id,
              toErrorText(data.error_type, "validation_error"),
              fullMessage
            );
            if (chainId && !cancelTriggeredRef.current) {
              cancelTriggeredRef.current = true;
              void cancelChain(chainId).catch((e) => {
                console.error("Auto-cancel failed after step_validation_failed:", e);
              });
            }
          }
          break;

        case "step_completed":
          if (data.step_id) {
            onStepCompleted(data.step_id, data.artifact_id);
          }
          break;

        case "step_cached":
          if (data.step_id) {
            onStepCached(data.step_id, data.artifact_id, data.artifact_url);
          }
          break;

        case "approval_requested":
          if (data.step_id && data.token) {
            onApprovalRequested(
              data.step_id,
              data.token,
              data.workflow || "",
              data.artifact_url || "",
              data.artifact_id || ""
            );
          }
          break;

        case "chain_completed":
          onChainCompleted();
          break;

        case "chain_failed":
          onChainFailed(toErrorText(data.error, "Unknown error"));
          break;

        case "level_wait_started":
          if (data.level_num !== undefined && data.wait_seconds !== undefined) {
            startWait(data.level_num, data.wait_seconds);
          }
          break;

        case "level_wait_ended":
          endWait();
          break;
      }
    } catch (e) {
      console.error("Failed to parse SSE event:", e);
    }
  }, [
    onStepExecuting,
    onStepNode,
    onStepWorkflowComplete,
    onStepWorkflowFailed,
    onStepValidationFailed,
    onStepCached,
    onStepCompleted,
    onApprovalRequested,
    onChainCompleted,
    onChainFailed,
    cancelChain,
    chainId,
    startWait,
    endWait,
  ]);

  useEffect(() => {
    cancelTriggeredRef.current = false;
    if (!chainId) {
      // Close existing connection if chainId becomes null
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      return;
    }

    // Create new EventSource connection
    const url = `${GATEWAY_URL}/chains/events?chain_id=${chainId}`;
    console.log("[SSE] Connecting to:", url);
    const eventSource = new EventSource(url);
    eventSourceRef.current = eventSource;

    eventSource.onopen = () => {
      console.log("[SSE] Connection opened");
    };

    // Backend sends named events, so we need to listen for each type
    const eventTypes = [
      "step_executing",
      "step_node",
      "step_workflow_complete",
      "step_workflow_failed",
      "step_validation_failed",
      "step_completed",
      "step_cached",
      "approval_requested",
      "chain_completed",
      "chain_failed",
      "level_wait_started",
      "level_wait_ended",
    ];

    for (const eventType of eventTypes) {
      eventSource.addEventListener(eventType, handleEvent);
    }

    // Also listen to generic message events (fallback)
    eventSource.onmessage = handleEvent;

    eventSource.onerror = (error) => {
      console.error("[SSE] Connection error:", error);
      console.log("[SSE] ReadyState:", eventSource.readyState);
      // EventSource will automatically try to reconnect
    };

    // Cleanup on unmount or chainId change
    return () => {
      for (const eventType of eventTypes) {
        eventSource.removeEventListener(eventType, handleEvent);
      }
      eventSource.close();
      eventSourceRef.current = null;
    };
  }, [chainId, handleEvent]);

  // Return a function to manually close the connection
  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  return { disconnect };
}

// =============================================================================
// API functions for approval actions
// =============================================================================

export async function approveStep(token: string): Promise<void> {
  const response = await fetch(`${GATEWAY_URL}/approve/${token}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decided_by: "frontend-user" }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to approve");
  }
}

export async function rejectStep(
  token: string,
  newParameters?: Record<string, unknown>
): Promise<void> {
  const response = await fetch(`${GATEWAY_URL}/reject/${token}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      decided_by: "frontend-user",
      new_parameters: newParameters,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to reject");
  }
}

export async function getApprovalParameters(token: string): Promise<{
  workflow_name: string;
  parameters: Array<{
    key: string;
    current_value: unknown;
    type: string;
    category: string;
    description: string;
  }>;
}> {
  const response = await fetch(`${GATEWAY_URL}/approval/${token}/parameters`);

  if (!response.ok) {
    throw new Error("Failed to get approval parameters");
  }

  return response.json();
}
