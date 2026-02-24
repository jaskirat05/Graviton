"use client";

/**
 * ContextMenu - Right-click/double-click menu for adding nodes
 * Shows nodes grouped by category and then by group (nodeType)
 */

import { useEffect, useRef, useState } from "react";
import { useNodeStore } from "@/stores/nodeStore";
import type { NodeCategory } from "./types";

interface ContextMenuProps {
  position: { x: number; y: number };
  onSelect: (nodeType: string) => void;
  onClose: () => void;
}

const categoryConfig: Record<NodeCategory, { label: string; color: string }> = {
  image: { label: "Image", color: "#22c55e" },
  video: { label: "Video", color: "#3b82f6" },
  utility: { label: "Utility", color: "#8b5cf6" },
  invalid: { label: "Invalid", color: "#ef4444" },
};

export function ContextMenu({ position, onSelect, onClose }: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const { getNodesByCategory, nodeDefinitions, isLoading } = useNodeStore();
  const nodesByCategory = getNodesByCategory();

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };

    // Small delay to prevent immediate close
    const timer = setTimeout(() => {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleEscape);
    }, 10);

    return () => {
      clearTimeout(timer);
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [onClose]);

  // Filter nodes based on search query
  const filteredNodes = searchQuery
    ? nodeDefinitions.filter(
        (node) =>
          node.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
          node.type.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : null;

  if (isLoading) {
    return (
      <div
        ref={menuRef}
        className="fixed z-50 min-w-[280px] bg-[var(--surface-1)]/95 backdrop-blur-md border border-[var(--border)] rounded-xl shadow-2xl overflow-hidden"
        style={{ left: position.x, top: position.y }}
      >
        <div className="px-4 py-6 text-sm text-[var(--text-muted)] flex items-center justify-center gap-2">
          <div className="w-4 h-4 border-2 border-[var(--text-muted)] border-t-transparent rounded-full animate-spin" />
          Loading nodes...
        </div>
      </div>
    );
  }

  if (nodeDefinitions.length === 0) {
    return (
      <div
        ref={menuRef}
        className="fixed z-50 min-w-[280px] bg-[var(--surface-1)]/95 backdrop-blur-md border border-[var(--border)] rounded-xl shadow-2xl overflow-hidden"
        style={{ left: position.x, top: position.y }}
      >
        <div className="px-4 py-6 text-sm text-[var(--text-muted)] text-center">
          No nodes available.
          <br />
          <span className="text-xs">Check backend connection.</span>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={menuRef}
      className="fixed z-50 min-w-[300px] max-w-[340px] bg-[var(--surface-1)]/95 backdrop-blur-md border border-[var(--border)] rounded-xl shadow-2xl overflow-hidden"
      style={{
        left: position.x,
        top: position.y,
      }}
    >
      {/* Header with search */}
      <div className="p-3 border-b border-[var(--border)] bg-[var(--surface-2)]/50">
        <div className="relative">
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-muted)]"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          <input
            type="text"
            placeholder="Search nodes..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-sm bg-[var(--surface-3)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--brand-secondary)] transition-colors"
            autoFocus
          />
        </div>
      </div>

      {/* Node list */}
      <div className="py-2 max-h-[360px] overflow-y-auto">
        {/* Search results */}
        {filteredNodes ? (
          filteredNodes.length > 0 ? (
            <div className="px-2">
              {filteredNodes.map((node) => (
                <button
                  key={node.type}
                  onClick={() => onSelect(node.type)}
                  className="w-full px-3 py-2.5 flex items-center gap-3 hover:bg-[var(--surface-3)] rounded-lg transition-colors text-left group"
                >
                  <div
                    className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold text-white shadow-sm"
                    style={{ backgroundColor: node.color }}
                  >
                    {node.label.slice(0, 2).toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-[var(--text-primary)] font-medium truncate group-hover:text-white transition-colors">
                      {node.label}
                    </div>
                    <div className="text-xs text-[var(--text-muted)] truncate">
                      {node.group || node.category}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="px-4 py-6 text-sm text-[var(--text-muted)] text-center">
              No nodes match &quot;{searchQuery}&quot;
            </div>
          )
        ) : (
          /* Grouped nodes */
          (Object.keys(nodesByCategory) as NodeCategory[]).map((category) => {
            const groups = nodesByCategory[category];
            const groupNames = Object.keys(groups);
            if (groupNames.length === 0) return null;

            const config = categoryConfig[category];

            return (
              <div key={category} className="mb-2">
                {/* Category header */}
                <div className="mx-3 mt-2 mb-1 flex items-center gap-2">
                  <div
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ backgroundColor: config.color }}
                  />
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    {config.label}
                  </span>
                </div>

                {groupNames.map((groupName) => {
                  const nodes = groups[groupName];
                  return (
                    <div key={groupName} className="px-2">
                      {/* Group label */}
                      <div className="px-3 py-1 text-[11px] font-medium text-[var(--text-secondary)]">
                        {groupName}
                      </div>

                      {/* Nodes in group */}
                      {nodes.map((node) => (
                        <button
                          key={node.type}
                          onClick={() => onSelect(node.type)}
                          className="w-full px-3 py-2 flex items-center gap-3 hover:bg-[var(--surface-3)] rounded-lg transition-colors text-left group"
                        >
                          <div
                            className="w-7 h-7 rounded-md flex items-center justify-center text-[10px] font-bold text-white shadow-sm"
                            style={{ backgroundColor: node.color }}
                          >
                            {node.label.slice(0, 2).toUpperCase()}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="text-sm text-[var(--text-primary)] truncate group-hover:text-white transition-colors">
                              {node.label}
                            </div>
                          </div>
                          <svg
                            className="w-4 h-4 text-[var(--text-muted)] opacity-0 group-hover:opacity-100 transition-opacity"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M12 4v16m8-8H4"
                            />
                          </svg>
                        </button>
                      ))}
                    </div>
                  );
                })}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
