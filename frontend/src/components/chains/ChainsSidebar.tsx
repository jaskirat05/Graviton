"use client";

/**
 * ChainsSidebar - Collapsible sidebar showing chain names and versions
 */

import { useEffect, useState } from "react";
import { useChainStore, type ChainName, type ChainVersion, type ChainArtifacts } from "@/stores/chainStore";

interface ChainsSidebarProps {
  onViewDashboard: (chainId: string) => void;
  onLoadChain: (chainId: string, definition: Record<string, unknown>, artifacts: ChainArtifacts) => void;
  onNewChain: () => void;
}

export function ChainsSidebar({ onViewDashboard, onLoadChain, onNewChain }: ChainsSidebarProps) {
  const {
    chainNames,
    selectedChainName,
    chainVersions,
    selectedVersionId,
    isLoading,
    isLoadingVersions,
    error,
    sidebarOpen,
    fetchChainNames,
    selectChain,
    selectVersion,
    fetchChainDefinition,
    deleteChain,
    toggleSidebar,
    createNewChain,
    clearSelection,
  } = useChainStore();

  // New chain modal state
  const [showNewChainModal, setShowNewChainModal] = useState(false);
  const [newChainName, setNewChainName] = useState("");

  // Fetch chain names on mount
  useEffect(() => {
    fetchChainNames();
  }, [fetchChainNames]);

  // Format date for display
  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return "Never";
    const date = new Date(dateStr);
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  // Get status color
  const getStatusColor = (status: ChainVersion["status"]) => {
    switch (status) {
      case "completed":
        return "bg-green-500";
      case "running":
        return "bg-blue-500";
      case "failed":
        return "bg-red-500";
      case "starting":
        return "bg-yellow-500";
      case "cancelled":
        return "bg-gray-500";
      default:
        return "bg-gray-500";
    }
  };

  // Handle version click
  const handleVersionClick = (chainId: string) => {
    selectVersion(chainId);
    onViewDashboard(chainId);
  };

  // Handle delete with confirmation
  const handleDelete = async (e: React.MouseEvent, chainId: string) => {
    e.stopPropagation();
    if (confirm("Delete this chain version?")) {
      await deleteChain(chainId);
    }
  };

  // Handle load chain into editor
  const handleLoadChain = async (e: React.MouseEvent, chainId: string) => {
    e.stopPropagation();

    // Fetch both definition and artifacts in parallel
    const [defResult] = await Promise.all([
      fetchChainDefinition(chainId),
      selectVersion(chainId), // This populates chainArtifacts in the store
    ]);

    // Get artifacts from store after selectVersion completes
    const { chainArtifacts } = useChainStore.getState();

    if (defResult?.definition && chainArtifacts) {
      // Use executed_definition if available, otherwise fall back to original
      const definition = defResult.executed_definition ?? defResult.definition;
      onLoadChain(chainId, definition, chainArtifacts);
    }
  };

  // Handle create new chain
  const handleCreateNewChain = () => {
    if (!newChainName.trim()) return;
    createNewChain(newChainName.trim());
    setShowNewChainModal(false);
    setNewChainName("");
    onNewChain();
  };

  if (!sidebarOpen) {
    return (
      <button
        onClick={toggleSidebar}
        className="fixed left-0 top-1/2 -translate-y-1/2 z-50 p-2 bg-[var(--surface-2)] border border-[var(--border)] rounded-r-md hover:bg-[var(--surface-3)] transition-colors"
        title="Open chains sidebar"
      >
        <svg className="w-5 h-5 text-[var(--text-primary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
      </button>
    );
  }

  return (
    <div className="w-72 h-full bg-[var(--surface-1)] border-r border-[var(--border)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">Chains</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowNewChainModal(true)}
            className="p-1.5 hover:bg-[var(--surface-3)] rounded transition-colors"
            title="New chain"
          >
            <svg className="w-4 h-4 text-[var(--text-muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
          </button>
          <button
            onClick={() => {
              clearSelection();
              fetchChainNames();
            }}
            className="p-1.5 hover:bg-[var(--surface-3)] rounded transition-colors"
            title="Refresh"
          >
            <svg className="w-4 h-4 text-[var(--text-muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
          <button
            onClick={toggleSidebar}
            className="p-1.5 hover:bg-[var(--surface-3)] rounded transition-colors"
            title="Close sidebar"
          >
            <svg className="w-4 h-4 text-[var(--text-muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
        </div>
      </div>

      {/* Error message */}
      {error && (
        <div className="px-4 py-2 bg-red-500/10 text-red-400 text-xs">
          {error}
        </div>
      )}

      {/* Chain list */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin w-5 h-5 border-2 border-[var(--text-muted)] border-t-transparent rounded-full" />
          </div>
        ) : chainNames.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-[var(--text-muted)]">
            No chains yet
          </div>
        ) : (
          <div className="py-2">
            {chainNames.map((chain: ChainName) => (
              <div key={chain.name} className="px-2">
                {/* Chain name header */}
                <button
                  onClick={() => {
                    // Toggle: if already selected, deselect; otherwise select
                    if (selectedChainName === chain.name) {
                      clearSelection();
                    } else {
                      selectChain(chain.name);
                    }
                  }}
                  className={`w-full flex items-center justify-between px-3 py-2 rounded-md text-left transition-colors ${
                    selectedChainName === chain.name
                      ? "bg-[var(--surface-3)]"
                      : "hover:bg-[var(--surface-2)]"
                  }`}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <svg
                      className={`w-4 h-4 text-[var(--text-muted)] transition-transform ${
                        selectedChainName === chain.name ? "rotate-90" : ""
                      }`}
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                    <span className="text-sm text-[var(--text-primary)] truncate">
                      {chain.name}
                    </span>
                  </div>
                  <span className="text-xs text-[var(--text-muted)] bg-[var(--surface-4)] px-1.5 py-0.5 rounded">
                    {chain.run_count}
                  </span>
                </button>

                {/* Versions list (expanded when selected) */}
                {selectedChainName === chain.name && (
                  <div className="ml-4 mt-1 mb-2 border-l border-[var(--border)] pl-2">
                    {isLoadingVersions ? (
                      <div className="flex items-center gap-2 py-2 px-2 text-xs text-[var(--text-muted)]">
                        <div className="animate-spin w-3 h-3 border border-[var(--text-muted)] border-t-transparent rounded-full" />
                        Loading...
                      </div>
                    ) : chainVersions.length === 0 ? (
                      <div className="py-2 px-2 text-xs text-[var(--text-muted)]">
                        No versions
                      </div>
                    ) : (
                      chainVersions.map((version: ChainVersion) => (
                        <div
                          key={version.id}
                          onClick={() => handleVersionClick(version.id)}
                          className={`flex items-center justify-between px-2 py-1.5 rounded cursor-pointer transition-colors group ${
                            selectedVersionId === version.id
                              ? "bg-[var(--brand-primary)]/20"
                              : "hover:bg-[var(--surface-2)]"
                          }`}
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <div className={`w-2 h-2 rounded-full ${getStatusColor(version.status)}`} />
                            <span className="text-xs text-[var(--text-secondary)]">
                              v{version.version}
                            </span>
                            <span className="text-xs text-[var(--text-muted)] truncate">
                              {formatDate(version.started_at)}
                            </span>
                          </div>
                          <div className="flex items-center gap-1">
                            {/* Load into editor button */}
                            <button
                              onClick={(e) => handleLoadChain(e, version.id)}
                              className="p-1 opacity-0 group-hover:opacity-100 hover:bg-blue-500/20 rounded transition-all"
                              title="Load into editor"
                            >
                              <svg className="w-3 h-3 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                              </svg>
                            </button>
                            {/* Delete button */}
                            <button
                              onClick={(e) => handleDelete(e, version.id)}
                              className="p-1 opacity-0 group-hover:opacity-100 hover:bg-red-500/20 rounded transition-all"
                              title="Delete version"
                            >
                              <svg className="w-3 h-3 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                              </svg>
                            </button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* New chain modal */}
      {showNewChainModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-[var(--surface-2)] border border-[var(--border)] rounded-lg shadow-xl w-80">
            <div className="px-4 py-3 border-b border-[var(--border)]">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">New Chain</h3>
            </div>
            <div className="p-4">
              <label className="block text-xs text-[var(--text-muted)] mb-2">
                Chain Name
              </label>
              <input
                type="text"
                value={newChainName}
                onChange={(e) => setNewChainName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCreateNewChain();
                  if (e.key === "Escape") setShowNewChainModal(false);
                }}
                placeholder="Enter chain name..."
                autoFocus
                className="w-full px-3 py-2 bg-[var(--surface-3)] border border-[var(--border)] rounded-md text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-primary)]"
              />
            </div>
            <div className="flex justify-end gap-2 px-4 py-3 border-t border-[var(--border)]">
              <button
                onClick={() => {
                  setShowNewChainModal(false);
                  setNewChainName("");
                }}
                className="px-3 py-1.5 text-sm text-[var(--text-secondary)] hover:bg-[var(--surface-3)] rounded-md transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateNewChain}
                disabled={!newChainName.trim()}
                className="px-3 py-1.5 text-sm bg-[var(--brand-primary)] text-white rounded-md hover:opacity-90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
