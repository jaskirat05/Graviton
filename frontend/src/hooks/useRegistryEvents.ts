"use client";

import { useEffect, useRef } from "react";

interface RegistryEvent {
  type?: string;
  template_name?: string;
  [key: string]: unknown;
}

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:8001";

function getRegistryWsUrl(): string {
  const gateway = new URL(GATEWAY_URL);
  gateway.protocol = gateway.protocol === "https:" ? "wss:" : "ws:";
  gateway.pathname = "/api/registry/v1/events/ws";
  gateway.search = "";
  gateway.hash = "";
  return gateway.toString();
}

export function useRegistryEvents(
  onTemplateChanged: () => Promise<void> | void,
  onEvent?: (event: RegistryEvent) => void
): void {
  const reconnectTimerRef = useRef<number | null>(null);
  const refreshTimerRef = useRef<number | null>(null);
  const stoppedRef = useRef(false);

  useEffect(() => {
    stoppedRef.current = false;
    let ws: WebSocket | null = null;

    const scheduleRefresh = () => {
      if (refreshTimerRef.current !== null) {
        window.clearTimeout(refreshTimerRef.current);
      }
      refreshTimerRef.current = window.setTimeout(() => {
        void onTemplateChanged();
      }, 300);
    };

    const connect = () => {
      const wsUrl = getRegistryWsUrl();
      ws = new WebSocket(wsUrl);

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as RegistryEvent;
          onEvent?.(data);
          if (data.type === "template_changed") {
            scheduleRefresh();
          }
        } catch (error) {
          console.warn("[registry-events] invalid websocket payload:", error);
        }
      };

      ws.onclose = () => {
        if (stoppedRef.current) return;
        reconnectTimerRef.current = window.setTimeout(connect, 1000);
      };

      ws.onerror = () => {
        ws?.close();
      };
    };

    connect();

    return () => {
      stoppedRef.current = true;
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
      }
      if (refreshTimerRef.current !== null) {
        window.clearTimeout(refreshTimerRef.current);
      }
      if (ws) {
        ws.close();
      }
    };
  }, [onEvent, onTemplateChanged]);
}
