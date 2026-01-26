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
  token?: string;
  artifact_url?: string;
  artifact_id?: string;
  level_num?: number;
  wait_seconds?: number;
  skipped?: boolean;
}

export function useChainEvents(chainId: string | null) {
  const eventSourceRef = useRef<EventSource | null>(null);

  const {
    onStepExecuting,
    onStepNode,
    onStepWorkflowComplete,
    onStepWorkflowFailed,
    onStepValidationFailed,
    onStepCompleted,
    onApprovalRequested,
    onChainCompleted,
    onChainFailed,
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
            onStepWorkflowFailed(data.step_id, data.error || "Unknown error");
          }
          break;

        case "step_validation_failed":
          if (data.step_id) {
            onStepValidationFailed(
              data.step_id,
              data.error_type || "validation_error",
              data.error_message || "Unknown validation error"
            );
          }
          break;

        case "step_completed":
          if (data.step_id) {
            onStepCompleted(data.step_id, data.artifact_id);
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
          onChainFailed(data.error || "Unknown error");
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
    onStepCompleted,
    onApprovalRequested,
    onChainCompleted,
    onChainFailed,
    startWait,
    endWait,
  ]);

  useEffect(() => {
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
