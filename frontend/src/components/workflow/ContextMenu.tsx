"use client";

/**
 * ContextMenu - Right-click/double-click menu for adding nodes
 * Shows nodes grouped by category and then by group (nodeType)
 */

import { useEffect, useRef } from "react";
import { useNodeStore } from "@/stores/nodeStore";
import type { NodeCategory } from "./types";

interface ContextMenuProps {
  position: { x: number; y: number };
  onSelect: (nodeType: string) => void;
  onClose: () => void;
}

const categoryLabels: Record<NodeCategory, string> = {
  image: "Image",
  video: "Video",
  utility: "Utility",
};

export function ContextMenu({ position, onSelect, onClose }: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
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

  if (isLoading) {
    return (
      <div
        ref={menuRef}
        className="fixed z-50 min-w-[220px] bg-[var(--surface-2)] border border-[var(--border-1)] rounded-lg shadow-xl overflow-hidden"
        style={{ left: position.x, top: position.y }}
      >
        <div className="px-3 py-4 text-sm text-[var(--text-muted)]">Loading...</div>
      </div>
    );
  }

  if (nodeDefinitions.length === 0) {
    return (
      <div
        ref={menuRef}
        className="fixed z-50 min-w-[220px] bg-[var(--surface-2)] border border-[var(--border-1)] rounded-lg shadow-xl overflow-hidden"
        style={{ left: position.x, top: position.y }}
      >
        <div className="px-3 py-4 text-sm text-[var(--text-muted)]">
          No nodes available. Check backend connection.
        </div>
      </div>
    );
  }

  return (
    <div
      ref={menuRef}
      className="fixed z-50 min-w-[260px] bg-[var(--surface-2)] border border-[var(--border-1)] rounded-lg shadow-xl overflow-hidden"
      style={{
        left: position.x,
        top: position.y,
      }}
    >
      {/* Header */}
      <div className="px-3 py-2 bg-[var(--surface-3)] border-b border-[var(--border)]">
        <h3 className="text-sm font-medium text-[var(--text-primary)]">Add Node</h3>
      </div>

      {/* Node list by category, then by group */}
      <div className="py-1 max-h-[400px] overflow-y-auto">
        {(Object.keys(nodesByCategory) as NodeCategory[]).map((category) => {
          const groups = nodesByCategory[category];
          const groupNames = Object.keys(groups);
          if (groupNames.length === 0) return null;

          return (
            <div key={category}>
              {/* Category header */}
              <div className="px-3 py-1.5 text-[10px] font-medium text-[var(--text-muted)] uppercase tracking-wider bg-[var(--surface-3)]">
                {categoryLabels[category]}
              </div>

              {/* Groups within category */}
              {groupNames.map((groupName) => {
                const nodes = groups[groupName];
                return (
                  <div key={groupName}>
                    {/* Group header (e.g., "Image Generate") */}
                    <div className="px-3 py-1 text-[11px] font-medium text-[var(--text-secondary)]">
                      {groupName}
                    </div>

                    {/* Nodes in group */}
                    {nodes.map((node) => (
                      <button
                        key={node.type}
                        onClick={() => onSelect(node.type)}
                        className="w-full px-3 py-2 pl-5 flex items-center gap-3 hover:bg-[var(--surface-4)] transition-colors text-left"
                      >
                        <div
                          className="w-6 h-6 rounded flex items-center justify-center text-sm"
                          style={{ backgroundColor: `${node.color}20` }}
                        >
                          {node.icon}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm text-[var(--text-primary)] truncate">
                            {node.label}
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
