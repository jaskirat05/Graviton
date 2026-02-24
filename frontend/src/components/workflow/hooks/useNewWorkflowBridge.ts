import { useCallback, useEffect } from "react";
import { useServerStore, type ServerInfo } from "@/stores/serverStore";

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:8001";

type ComfyPromptNode = {
  class_type: string;
  inputs: Record<string, unknown>;
};

type ComfyPrompt = Record<string, ComfyPromptNode>;

interface UseNewWorkflowBridgeParams {
  isOpen: boolean;
  origin: string | null;
  workflowName: string;
  selectedServer: ServerInfo | null;
  iframeRef: React.RefObject<HTMLIFrameElement | null>;
  pingTimerRef: React.RefObject<number | null>;
  fetchServers: () => Promise<void>;
  fetchWorkflows: () => Promise<void>;
  getComfyServerUrl: (server: ServerInfo) => string;
  setServerName: (name: string) => void;
  setBaseUrl: (url: string | null) => void;
  setOpening: (value: boolean) => void;
  setSaving: (value: boolean) => void;
  setError: (value: string | null) => void;
  setStatus: (value: string) => void;
  setOpen: (value: boolean) => void;
  setCurrentChainName: (name: string) => void;
}

export function useNewWorkflowBridge({
  isOpen,
  origin,
  workflowName,
  selectedServer,
  iframeRef,
  pingTimerRef,
  fetchServers,
  fetchWorkflows,
  getComfyServerUrl,
  setServerName,
  setBaseUrl,
  setOpening,
  setSaving,
  setError,
  setStatus,
  setOpen,
  setCurrentChainName,
}: UseNewWorkflowBridgeParams) {
  const postToIframe = useCallback(
    (type: string, payload: Record<string, unknown> = {}) => {
      const iframeWindow = iframeRef.current?.contentWindow;
      if (!iframeWindow) return;
      iframeWindow.postMessage(
        {
          source: "graviton-host",
          type,
          payload,
        },
        origin || "*"
      );
    },
    [iframeRef, origin]
  );

  useEffect(() => {
    if (!isOpen) return;
    if (pingTimerRef.current !== null) {
      window.clearTimeout(pingTimerRef.current);
      pingTimerRef.current = null;
    }

    const requestPing = () => postToIframe("ping");

    const handleBridgeMessage = (event: MessageEvent) => {
      if (origin && event.origin !== origin) return;
      if (event.source !== iframeRef.current?.contentWindow) return;

      const message = event.data as {
        source?: string;
        type?: string;
        payload?: {
          workflow?: ComfyPrompt;
          message?: string;
          ready?: boolean;
        };
      };
      if (message?.source !== "graviton-bridge") return;

      if (message.type === "ready") {
        console.log("[graviton-host] new-workflow bridge ready", {
          origin: event.origin,
          payload: message.payload,
        });
        setStatus("waiting-ready-pong");
        requestPing();
        return;
      }

      if (message.type === "pong") {
        console.log("[graviton-host] new-workflow bridge pong", {
          origin: event.origin,
          payload: message.payload,
        });
        const ready = Boolean((message.payload as Record<string, unknown> | undefined)?.ready);
        if (ready) {
          setStatus("ready");
        } else {
          setStatus("waiting-ready-pong");
          if (pingTimerRef.current !== null) {
            window.clearTimeout(pingTimerRef.current);
          }
          pingTimerRef.current = window.setTimeout(requestPing, 250);
        }
        return;
      }

      if (message.type === "workflow-exported") {
        const exportedWorkflow = message.payload?.workflow;
        setSaving(false);
        if (!exportedWorkflow || typeof exportedWorkflow !== "object") {
          setStatus("error");
          setError("Missing workflow export from Comfy editor.");
          return;
        }

        void (async () => {
          const trimmedName = workflowName.trim();
          if (!trimmedName) {
            setStatus("error");
            setError("Workflow name is required.");
            return;
          }

          try {
            const response = await fetch(
              `${GATEWAY_URL}/api/registry/v1/templates/${encodeURIComponent(trimmedName)}/workflow`,
              {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ workflow: exportedWorkflow }),
              }
            );
            if (!response.ok) {
              throw new Error(`Failed to save workflow template: ${response.statusText}`);
            }
            await fetchWorkflows();
            console.log("[graviton-host] new-workflow upsert success", {
              template: trimmedName,
              payload: exportedWorkflow,
            });
            setCurrentChainName(trimmedName);
            setStatus("saved");
            setError(null);
            setOpen(false);
          } catch (error) {
            setStatus("error");
            setError(error instanceof Error ? error.message : "Failed to save new workflow template.");
          }
        })();
        return;
      }

      if (message.type === "error") {
        setSaving(false);
        setStatus("error");
        setError(message.payload?.message || "Comfy iframe bridge error.");
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
    fetchWorkflows,
    iframeRef,
    isOpen,
    origin,
    pingTimerRef,
    postToIframe,
    setCurrentChainName,
    setError,
    setOpen,
    setSaving,
    setStatus,
    workflowName,
  ]);

  const openEditor = useCallback(async () => {
    setOpening(true);
    setError(null);
    setStatus("opening");
    try {
      let targetServer = selectedServer;
      if (!targetServer) {
        await fetchServers();
        const refreshedServers = useServerStore.getState().servers;
        if (refreshedServers.length === 0) {
          throw new Error("No servers available.");
        }
        targetServer = refreshedServers[0];
        setServerName(targetServer.name);
      }
      setBaseUrl(getComfyServerUrl(targetServer));
      setStatus("waiting-iframe-ready");
      setOpen(true);
    } catch (error) {
      setStatus("error");
      setError(error instanceof Error ? error.message : "Failed to open Comfy editor.");
    } finally {
      setOpening(false);
    }
  }, [
    fetchServers,
    getComfyServerUrl,
    selectedServer,
    setBaseUrl,
    setError,
    setOpen,
    setOpening,
    setServerName,
    setStatus,
  ]);

  const saveWorkflow = useCallback(() => {
    const trimmedName = workflowName.trim();
    if (!trimmedName) {
      setError("Workflow name is required.");
      return;
    }
    setSaving(true);
    setError(null);
    setStatus("exporting");
    console.log("[graviton-host] sending new-workflow export request", {
      template: trimmedName,
    });
    postToIframe("export-workflow");
  }, [postToIframe, setError, setSaving, setStatus, workflowName]);

  return {
    openEditor,
    saveWorkflow,
  };
}
