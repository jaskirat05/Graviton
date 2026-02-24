"use client";

import { useEffect, useRef, useState } from "react";
import {
  useServerStore,
  type ServerControlPlaneStatus,
  type WorkerControlSecretResponse,
} from "@/stores/serverStore";
import { useRegistryEvents } from "@/hooks/useRegistryEvents";

interface ServerSettingsPanelProps {
  onClose: () => void;
}

export function ServerSettingsPanel({ onClose }: ServerSettingsPanelProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const servers = useServerStore((state) => state.servers);
  const fetchServers = useServerStore((state) => state.fetchServers);
  const createServer = useServerStore((state) => state.createServer);
  const syncServerWorkflows = useServerStore((state) => state.syncServerWorkflows);
  const syncServerObjectInfo = useServerStore((state) => state.syncServerObjectInfo);
  const syncDataPlaneConfig = useServerStore((state) => state.syncDataPlaneConfig);
  const syncServerDataPlaneConfig = useServerStore((state) => state.syncServerDataPlaneConfig);
  const fetchServerHealth = useServerStore((state) => state.fetchServerHealth);
  const fetchServerControlPlaneStatus = useServerStore((state) => state.fetchServerControlPlaneStatus);
  const deleteServer = useServerStore((state) => state.deleteServer);
  const storeError = useServerStore((state) => state.error);

  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [port, setPort] = useState("8188");
  const [ssl, setSsl] = useState(false);
  const [isAdding, setIsAdding] = useState(false);
  const [syncingServerId, setSyncingServerId] = useState<string | null>(null);
  const [syncingNodesServerId, setSyncingNodesServerId] = useState<string | null>(null);
  const [syncingDataPlaneServerId, setSyncingDataPlaneServerId] = useState<string | null>(null);
  const [deletingServerId, setDeletingServerId] = useState<string | null>(null);
  const [syncingDataPlaneConfig, setSyncingDataPlaneConfig] = useState(false);
  const [pingStatusByServer, setPingStatusByServer] = useState<Record<string, boolean>>({});
  const [refreshingHealthByServer, setRefreshingHealthByServer] = useState<Record<string, boolean>>({});
  const [controlPlaneStatusByServer, setControlPlaneStatusByServer] = useState<
    Record<string, ServerControlPlaneStatus>
  >({});
  const [message, setMessage] = useState<string | null>(null);
  const [newControlSecret, setNewControlSecret] = useState<WorkerControlSecretResponse | null>(null);

  useRegistryEvents(
    () => {},
    (event) => {
      if (event.type !== "server_ping_status_changed") return;
      const serverId = typeof event.server_id === "string" ? event.server_id : "";
      if (!serverId) return;
      const ok = Boolean(event.ok);
      setPingStatusByServer((prev) => ({ ...prev, [serverId]: ok }));
    }
  );

  useEffect(() => {
    fetchServers();
  }, [fetchServers]);

  useEffect(() => {
    if (servers.length === 0) return;
    void Promise.all(
      servers.map(async (server) => {
        try {
          const health = await fetchServerHealth(server.id);
          const controlPlaneStatus = await fetchServerControlPlaneStatus(server.id);
          setPingStatusByServer((prev) => ({
            ...prev,
            [server.id]: health.health_state === "healthy" || health.health_state === "degraded",
          }));
          setControlPlaneStatusByServer((prev) => ({
            ...prev,
            [server.id]: controlPlaneStatus,
          }));
        } catch {
          setPingStatusByServer((prev) => ({ ...prev, [server.id]: false }));
        }
      })
    );
  }, [fetchServerControlPlaneStatus, fetchServerHealth, servers]);

  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      if (!panelRef.current) return;
      if (!panelRef.current.contains(event.target as Node)) {
        onClose();
      }
    };

    window.addEventListener("mousedown", onPointerDown, true);
    return () => window.removeEventListener("mousedown", onPointerDown, true);
  }, [onClose]);

  const handleAddServer = async () => {
    const trimmedName = name.trim();
    const trimmedAddress = address.trim();

    if (!trimmedName || !trimmedAddress) {
      setMessage("Name and address are required.");
      return;
    }

    setIsAdding(true);
    setMessage(null);
    setNewControlSecret(null);
    try {
      const result = await createServer({
        name: trimmedName,
        address: trimmedAddress,
        port: port.trim() ? Number(port) : undefined,
        ssl,
      });
      setName("");
      setAddress("");
      setPort("8188");
      setSsl(false);
      setNewControlSecret(result.controlSecret ?? null);
      if (result.controlSecret) {
        setMessage(
          result.controlSecretError
            ? `Server registered. Secret warning: ${result.controlSecretError}`
            : "Server registered. Save the control secret now."
        );
      } else if (result.controlSecretError) {
        setMessage(`Server registered, but secret setup failed: ${result.controlSecretError}`);
      } else {
        setMessage("Server registered.");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to register server.");
    } finally {
      setIsAdding(false);
    }
  };

  const handleCopySecret = async () => {
    if (!newControlSecret?.shared_secret) return;
    try {
      await navigator.clipboard.writeText(newControlSecret.shared_secret);
      setMessage("Control secret copied.");
    } catch {
      setMessage("Failed to copy control secret.");
    }
  };

  const handleSyncServer = async (serverId: string, force = false) => {
    setSyncingServerId(serverId);
    setMessage(null);
    try {
      await syncServerWorkflows(serverId, force);
      setMessage(force ? "Force workflow sync requested." : "Workflow sync requested.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to sync workflows.");
    } finally {
      setSyncingServerId(null);
    }
  };

  const handleDeleteServer = async (serverId: string, serverName: string) => {
    const confirmed = window.confirm(`Delete server '${serverName}'?`);
    if (!confirmed) return;

    setDeletingServerId(serverId);
    setMessage(null);
    try {
      await deleteServer(serverId);
      if (newControlSecret?.server_id === serverId) {
        setNewControlSecret(null);
      }
      setMessage("Server deleted.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to delete server.");
    } finally {
      setDeletingServerId(null);
    }
  };

  const handleSyncNodes = async (serverId: string) => {
    setSyncingNodesServerId(serverId);
    setMessage(null);
    try {
      await syncServerObjectInfo(serverId);
      setMessage("Node catalog sync requested.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to sync node catalog.");
    } finally {
      setSyncingNodesServerId(null);
    }
  };

  const handleRefreshHealth = async (serverId: string) => {
    setRefreshingHealthByServer((prev) => ({ ...prev, [serverId]: true }));
    setMessage(null);
    try {
      const health = await fetchServerHealth(serverId);
      const controlPlaneStatus = await fetchServerControlPlaneStatus(serverId);
      const isUp = health.health_state === "healthy" || health.health_state === "degraded";
      setPingStatusByServer((prev) => ({ ...prev, [serverId]: isUp }));
      setControlPlaneStatusByServer((prev) => ({ ...prev, [serverId]: controlPlaneStatus }));
      setMessage(`Health refreshed: ${health.health_state}`);
    } catch (error) {
      setPingStatusByServer((prev) => ({ ...prev, [serverId]: false }));
      setMessage(error instanceof Error ? error.message : "Failed to refresh health.");
    } finally {
      setRefreshingHealthByServer((prev) => ({ ...prev, [serverId]: false }));
    }
  };

  const handleSyncDataPlane = async () => {
    setSyncingDataPlaneConfig(true);
    setMessage(null);
    try {
      await syncDataPlaneConfig(true);
      setMessage("Data plane config force sync requested.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to sync data plane config.");
    } finally {
      setSyncingDataPlaneConfig(false);
    }
  };

  const handleSyncServerDataPlane = async (serverId: string) => {
    setSyncingDataPlaneServerId(serverId);
    setMessage(null);
    try {
      await syncServerDataPlaneConfig(serverId, true);
      setMessage("Server data plane force sync requested.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to sync server data plane config.");
    } finally {
      setSyncingDataPlaneServerId(null);
    }
  };

  return (
    <div
      ref={panelRef}
      className="absolute right-4 top-14 z-40 w-[min(96vw,760px)] max-h-[calc(100vh-4.5rem)] overflow-y-auto overflow-x-hidden rounded-lg border border-[var(--border)] bg-[var(--surface-2)] shadow-xl"
    >
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">Settings</h3>
        <button
          onClick={onClose}
          className="text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)]"
        >
          Close
        </button>
      </div>

      <div className="space-y-3 p-4">
        <div className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-3">
          <div className="mb-2 text-xs font-medium text-[var(--text-secondary)]">Data Plane</div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleSyncDataPlane}
              disabled={syncingDataPlaneConfig}
              className="rounded border border-[var(--border)] px-3 py-2 text-xs text-[var(--text-secondary)] hover:bg-[var(--surface-4)] disabled:opacity-50"
            >
              {syncingDataPlaneConfig ? "Syncing..." : "Sync DataPlane"}
            </button>
          </div>
          <div className="mt-2 text-[11px] text-[var(--text-muted)]">
            Data plane mode comes from environment config. Use this to force fanout to workers.
          </div>
        </div>

        <div>
          <label className="mb-1 block text-xs text-[var(--text-secondary)]">Server Name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="gpu-west-1"
            className="w-full rounded-md border border-[var(--border)] bg-[var(--surface-3)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--brand-secondary)] focus:outline-none"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs text-[var(--text-secondary)]">Address</label>
          <input
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="127.0.0.1"
            className="w-full rounded-md border border-[var(--border)] bg-[var(--surface-3)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--brand-secondary)] focus:outline-none"
          />
        </div>

        <div className="grid grid-cols-[1fr_auto] items-end gap-3">
          <div>
            <label className="mb-1 block text-xs text-[var(--text-secondary)]">Port</label>
            <input
              type="number"
              min={1}
              max={65535}
              value={port}
              onChange={(e) => setPort(e.target.value)}
              className="w-full rounded-md border border-[var(--border)] bg-[var(--surface-3)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--brand-secondary)] focus:outline-none"
            />
          </div>
          <label className="mb-2 flex items-center gap-2 text-xs text-[var(--text-secondary)]">
            <input
              type="checkbox"
              checked={ssl}
              onChange={(e) => setSsl(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-[var(--border)] bg-[var(--surface-4)]"
            />
            SSL
          </label>
        </div>

        <button
          onClick={handleAddServer}
          disabled={isAdding}
          className="flex w-full items-center justify-center gap-2 rounded-md bg-[var(--brand-primary)] px-3 py-2 text-sm text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isAdding ? (
            <>
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
              Adding...
            </>
          ) : (
            "Add Server"
          )}
        </button>

        {(message || storeError) && (
          <div className="text-xs text-[var(--text-secondary)]">{message || storeError}</div>
        )}

        {newControlSecret && (
          <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3">
            <div className="mb-1 text-xs font-semibold text-amber-300">Worker Control Secret (show once)</div>
            <div className="mb-2 text-[11px] text-amber-100/90">
              Save this now. If lost, delete and re-add the worker to generate a new secret.
            </div>
            <div className="mb-2 break-all rounded border border-[var(--border)] bg-[var(--surface-4)] px-2 py-1.5 font-mono text-[11px] text-[var(--text-primary)]">
              {newControlSecret.shared_secret}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-[11px] text-[var(--text-muted)]">
                worker_id: {newControlSecret.worker_id} | version: {newControlSecret.secret_version}
              </div>
              <div className="flex flex-wrap items-center gap-1">
                <button
                  onClick={handleCopySecret}
                  className="rounded border border-[var(--border)] px-2 py-1 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--surface-4)]"
                >
                  Copy
                </button>
                <button
                  onClick={() => setNewControlSecret(null)}
                  className="rounded border border-[var(--border)] px-2 py-1 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--surface-4)]"
                >
                  I Saved It
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="border-t border-[var(--border)] p-4">
        <div className="mb-2 text-xs font-medium text-[var(--text-secondary)]">Registered Servers</div>
        {servers.length === 0 ? (
          <div className="text-xs text-[var(--text-muted)]">No servers registered.</div>
        ) : (
          <div className="max-h-40 space-y-2 overflow-y-auto overflow-x-hidden">
            {servers.map((server) => (
              <div
                key={server.id}
                className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] px-2.5 py-2"
              >
                <div
                  className={`mb-2 h-1 w-full rounded ${(pingStatusByServer[server.id] ?? true) ? "bg-emerald-500 animate-pulse" : "bg-red-500 animate-pulse"}`}
                  title={(pingStatusByServer[server.id] ?? true) ? "Healthy" : "Unhealthy"}
                />
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-xs font-medium text-[var(--text-primary)]">{server.name}</div>
                    <div className="break-all text-[11px] text-[var(--text-muted)]">
                      {server.ssl ? "https" : "http"}://{server.address}
                      {server.port ? `:${server.port}` : ""}
                    </div>
                    <div
                      className={`text-[10px] ${
                        controlPlaneStatusByServer[server.id]?.reachable === false
                          ? "text-amber-400"
                          : controlPlaneStatusByServer[server.id]?.is_outdated
                            ? "text-orange-400"
                            : "text-emerald-400"
                      }`}
                    >
                      {controlPlaneStatusByServer[server.id]?.reachable === false
                        ? "DataPlane: Unreachable"
                        : controlPlaneStatusByServer[server.id]?.is_outdated
                          ? "DataPlane: Outdated"
                          : "DataPlane: Up to date"}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center justify-end gap-1">
                    <button
                      onClick={() => handleRefreshHealth(server.id)}
                      disabled={
                        Boolean(refreshingHealthByServer[server.id]) ||
                        syncingDataPlaneServerId === server.id ||
                        syncingServerId === server.id ||
                        syncingNodesServerId === server.id ||
                        deletingServerId === server.id
                      }
                      className="rounded border border-[var(--border)] p-1 text-[var(--text-secondary)] hover:bg-[var(--surface-4)] disabled:opacity-50"
                      title="Refresh health for this server"
                      aria-label={`Refresh health for ${server.name}`}
                    >
                      {refreshingHealthByServer[server.id] ? (
                        <span className="block h-3.5 w-3.5 animate-spin rounded-full border border-current border-t-transparent" />
                      ) : (
                        <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M23 4v6h-6" />
                          <path strokeLinecap="round" strokeLinejoin="round" d="M1 20v-6h6" />
                          <path strokeLinecap="round" strokeLinejoin="round" d="M3.51 9a9 9 0 0 1 14.13-3.36L23 10" />
                          <path strokeLinecap="round" strokeLinejoin="round" d="M20.49 15a9 9 0 0 1-14.13 3.36L1 14" />
                        </svg>
                      )}
                    </button>
                    <button
                      onClick={() => handleSyncServerDataPlane(server.id)}
                      disabled={
                        syncingDataPlaneServerId === server.id ||
                        syncingServerId === server.id ||
                        syncingNodesServerId === server.id ||
                        deletingServerId === server.id
                      }
                      className="rounded border border-[var(--border)] px-2 py-1 text-[10px] text-[var(--text-secondary)] hover:bg-[var(--surface-4)] disabled:opacity-50"
                      title="Force sync data plane config for this server"
                    >
                      {syncingDataPlaneServerId === server.id ? "Syncing..." : "Sync DataPlane"}
                    </button>
                    <button
                      onClick={() => handleSyncNodes(server.id)}
                      disabled={
                        syncingNodesServerId === server.id ||
                        syncingDataPlaneServerId === server.id ||
                        syncingServerId === server.id ||
                        deletingServerId === server.id
                      }
                      className="rounded border border-[var(--border)] px-2 py-1 text-[10px] text-[var(--text-secondary)] hover:bg-[var(--surface-4)] disabled:opacity-50"
                      title="Refresh object_info projection for this server"
                    >
                      {syncingNodesServerId === server.id ? "Syncing..." : "Sync Nodes"}
                    </button>
                    <button
                      onClick={() => handleSyncServer(server.id, false)}
                      disabled={
                        syncingServerId === server.id ||
                        syncingDataPlaneServerId === server.id ||
                        syncingNodesServerId === server.id ||
                        deletingServerId === server.id
                      }
                      className="rounded border border-[var(--border)] px-2 py-1 text-[10px] text-[var(--text-secondary)] hover:bg-[var(--surface-4)] disabled:opacity-50"
                      title="Re-sync templates from this server"
                    >
                      {syncingServerId === server.id ? "Syncing..." : "Sync"}
                    </button>
                    <button
                      onClick={() => handleSyncServer(server.id, true)}
                      disabled={
                        syncingServerId === server.id ||
                        syncingDataPlaneServerId === server.id ||
                        syncingNodesServerId === server.id ||
                        deletingServerId === server.id
                      }
                      className="rounded border border-[var(--border)] px-2 py-1 text-[10px] text-[var(--text-secondary)] hover:bg-[var(--surface-4)] disabled:opacity-50"
                      title="Force re-upsert templates from this server"
                    >
                      {syncingServerId === server.id ? "Syncing..." : "Force Sync"}
                    </button>
                    <button
                      onClick={() => handleDeleteServer(server.id, server.name)}
                      disabled={
                        deletingServerId === server.id ||
                        syncingDataPlaneServerId === server.id ||
                        syncingServerId === server.id ||
                        syncingNodesServerId === server.id
                      }
                      className="rounded border border-[var(--border)] p-1 text-[var(--text-secondary)] hover:bg-red-500/10 hover:text-red-400 disabled:opacity-50"
                      title="Delete server"
                      aria-label={`Delete server ${server.name}`}
                    >
                      <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M3 6h18" />
                        <path strokeLinecap="round" strokeLinejoin="round" d="M8 6V4h8v2" />
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19 6l-1 14H6L5 6" />
                        <path strokeLinecap="round" strokeLinejoin="round" d="M10 11v6M14 11v6" />
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
