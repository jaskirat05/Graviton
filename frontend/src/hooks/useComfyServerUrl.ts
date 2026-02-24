import { useCallback } from "react";
import type { ServerInfo } from "@/stores/serverStore";

export function buildComfyServerUrl(serverInfo: ServerInfo): string {
  const trimmed = serverInfo.address.trim().replace(/\/$/, "");
  const withScheme = /^https?:\/\//i.test(trimmed)
    ? trimmed
    : `${serverInfo.ssl ? "https" : "http"}://${trimmed}`;
  const url = new URL(withScheme);
  if (serverInfo.port) {
    url.port = String(serverInfo.port);
  }
  return url.origin;
}

export function useComfyServerUrl() {
  return useCallback((serverInfo: ServerInfo) => buildComfyServerUrl(serverInfo), []);
}
