"use client";

import { NodePropertiesPanel } from "./NodePropertiesPanel";
import type { WorkflowNodeData } from "./types";

interface WorkflowSidePanelsProps {
  selectedNode: { id: string; data: unknown } | null;
  updateMode: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  setNodes: (updater: (nodes: any[]) => any[]) => void;
  onCloseNodePanel: () => void;
  onUpdateParameters: (nodeId: string, parameters: Record<string, unknown>) => Promise<void>;
  exportOutput: string;
  onCloseExport: () => void;
}

export function WorkflowSidePanels({
  selectedNode,
  updateMode,
  setNodes,
  onCloseNodePanel,
  onUpdateParameters,
  exportOutput,
  onCloseExport,
}: WorkflowSidePanelsProps) {
  return (
    <>
      {selectedNode && (
        <NodePropertiesPanel
          nodeId={selectedNode.id}
          data={selectedNode.data as WorkflowNodeData}
          onClose={onCloseNodePanel}
          setNodes={setNodes}
          updateMode={updateMode}
          onUpdateParameters={onUpdateParameters}
        />
      )}

      {exportOutput && !selectedNode && (
        <div className="w-96 bg-[var(--surface-1)] border-l border-[var(--border)] overflow-auto">
          <div className="p-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-medium text-[var(--text-primary)]">Chain Output</h2>
              <button
                onClick={onCloseExport}
                className="text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              >
                Close
              </button>
            </div>
            <pre className="text-xs text-[var(--text-secondary)] bg-[var(--surface-3)] p-4 rounded-md overflow-auto">
              {exportOutput}
            </pre>
          </div>
        </div>
      )}
    </>
  );
}
