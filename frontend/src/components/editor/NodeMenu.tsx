/**
 * NodeMenu - Popup menu for spawning nodes
 *
 * Appears at the double-click position and allows users to select
 * a node type to spawn at that location.
 */

import { useEffect, useRef } from "react";
import { NodeTypeInfo } from "@/lib/nodes";

interface NodeMenuProps {
  position: { x: number; y: number };
  nodesByCategory: Record<string, NodeTypeInfo[]>;
  onSelectNode: (type: string) => void;
  onClose: () => void;
}

export function NodeMenu({
  position,
  nodesByCategory,
  onSelectNode,
  onClose,
}: NodeMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

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

    // Add listeners with slight delay to prevent immediate close
    const timeoutId = setTimeout(() => {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleEscape);
    }, 10);

    return () => {
      clearTimeout(timeoutId);
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [onClose]);

  const categoryLabels: Record<string, string> = {
    image: "Image",
    video: "Video",
    other: "Other",
  };

  return (
    <div
      ref={menuRef}
      className="absolute z-50 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl overflow-hidden min-w-[200px]"
      style={{
        left: position.x,
        top: position.y,
      }}
    >
      <div className="px-3 py-2 bg-zinc-800 border-b border-zinc-700">
        <h3 className="text-sm font-medium text-white">Add Node</h3>
      </div>

      <div className="py-1 max-h-[400px] overflow-y-auto">
        {Object.entries(nodesByCategory).map(([category, nodes]) => (
          <div key={category}>
            <div className="px-3 py-1 text-xs font-medium text-zinc-500 uppercase tracking-wider">
              {categoryLabels[category] ?? category}
            </div>
            {nodes.map((node) => (
              <button
                key={node.type}
                onClick={() => onSelectNode(node.type)}
                className="w-full px-3 py-2 flex items-center gap-3 hover:bg-zinc-800 transition-colors text-left"
              >
                <span
                  className="w-8 h-8 rounded flex items-center justify-center text-xs font-bold text-white"
                  style={{ backgroundColor: node.color }}
                >
                  {node.label.slice(0, 2).toUpperCase()}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-white font-medium truncate">
                    {node.label}
                  </div>
                  <div className="text-xs text-zinc-500 truncate">
                    {node.description}
                  </div>
                </div>
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
