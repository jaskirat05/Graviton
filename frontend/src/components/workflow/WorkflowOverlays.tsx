"use client";

import { ContextMenu } from "./ContextMenu";
import { ChainDashboard } from "../chains/ChainDashboard";
import { ServerSettingsPanel } from "@/components/settings/ServerSettingsPanel";

interface WorkflowOverlaysProps {
  showSettings: boolean;
  onCloseSettings: () => void;
  contextMenu: {
    show: boolean;
    position: { x: number; y: number };
  };
  onContextSelect: (workflow: string) => void;
  onContextClose: () => void;
  showDashboard: boolean;
  onCloseDashboard: () => void;
  isNewWorkflowEditorOpen: boolean;
  newWorkflowBaseUrl: string | null;
  selectedNewWorkflowServerName: string | null;
  newWorkflowBridgeStatus: string;
  newWorkflowName: string;
  onChangeNewWorkflowName: (name: string) => void;
  newWorkflowServerName: string;
  onChangeNewWorkflowServerName: (serverName: string) => void;
  servers: Array<{ id: string; name: string }>;
  isSavingNewWorkflow: boolean;
  onSaveNewWorkflow: () => void;
  onCloseNewWorkflow: () => void;
  newWorkflowError: string | null;
  newWorkflowIframeRef: React.RefObject<HTMLIFrameElement | null>;
  fatalExecutionError: { isOpen: boolean; message: string; stepId?: string } | null;
  onCloseFatalExecutionError: () => void;
}

export function WorkflowOverlays({
  showSettings,
  onCloseSettings,
  contextMenu,
  onContextSelect,
  onContextClose,
  showDashboard,
  onCloseDashboard,
  isNewWorkflowEditorOpen,
  newWorkflowBaseUrl,
  selectedNewWorkflowServerName,
  newWorkflowBridgeStatus,
  newWorkflowName,
  onChangeNewWorkflowName,
  newWorkflowServerName,
  onChangeNewWorkflowServerName,
  servers,
  isSavingNewWorkflow,
  onSaveNewWorkflow,
  onCloseNewWorkflow,
  newWorkflowError,
  newWorkflowIframeRef,
  fatalExecutionError,
  onCloseFatalExecutionError,
}: WorkflowOverlaysProps) {
  return (
    <>
      {fatalExecutionError?.isOpen && (
        <div className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-[1px] p-6">
          <div className="mx-auto mt-20 max-w-2xl rounded-xl border border-red-500/40 bg-[var(--surface-2)] shadow-2xl">
            <div className="border-b border-[var(--border)] px-5 py-4">
              <h3 className="text-sm font-semibold text-red-300">Workflow Execution Failed</h3>
              {fatalExecutionError.stepId && (
                <p className="mt-1 text-xs text-[var(--text-muted)]">Step: {fatalExecutionError.stepId}</p>
              )}
            </div>
            <div className="px-5 py-4">
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-red-500/10 p-3 text-xs text-red-200">
                {fatalExecutionError.message}
              </pre>
            </div>
            <div className="flex justify-end gap-2 border-t border-[var(--border)] px-5 py-4">
              <button
                onClick={onCloseFatalExecutionError}
                className="rounded-md bg-[var(--surface-4)] px-3 py-1.5 text-sm text-[var(--text-primary)] hover:bg-[var(--surface-5)]"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}

      {showSettings && <ServerSettingsPanel onClose={onCloseSettings} />}

      {contextMenu.show && (
        <ContextMenu position={contextMenu.position} onSelect={onContextSelect} onClose={onContextClose} />
      )}

      {showDashboard && <ChainDashboard onClose={onCloseDashboard} />}

      {isNewWorkflowEditorOpen && newWorkflowBaseUrl && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-[1px] p-6">
          <div className="mx-auto flex h-full w-full max-w-[1400px] flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface-2)] shadow-2xl">
            <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
              <div>
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">New Workflow</h3>
                <p className="text-xs text-[var(--text-muted)]">
                  {selectedNewWorkflowServerName || "server"} • {newWorkflowBridgeStatus}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={newWorkflowName}
                  onChange={(e) => onChangeNewWorkflowName(e.target.value)}
                  placeholder="workflow_name"
                  className="w-56 rounded-md border border-[var(--border)] bg-[var(--surface-3)] px-2.5 py-1.5 text-sm text-[var(--text-primary)] focus:border-[var(--brand-secondary)] focus:outline-none"
                />
                <select
                  value={newWorkflowServerName}
                  onChange={(e) => onChangeNewWorkflowServerName(e.target.value)}
                  className="rounded-md border border-[var(--border)] bg-[var(--surface-3)] px-2.5 py-1.5 text-sm text-[var(--text-primary)] focus:border-[var(--brand-secondary)] focus:outline-none"
                >
                  {servers.map((server) => (
                    <option key={server.id} value={server.name}>
                      {server.name}
                    </option>
                  ))}
                </select>
                <button
                  onClick={onSaveNewWorkflow}
                  disabled={isSavingNewWorkflow}
                  className="rounded-md bg-[var(--brand-success)] px-3 py-1.5 text-sm text-white hover:opacity-90 disabled:opacity-50"
                >
                  {isSavingNewWorkflow ? "Saving..." : "Save Workflow"}
                </button>
                <button
                  onClick={onCloseNewWorkflow}
                  className="rounded-md bg-[var(--surface-4)] px-3 py-1.5 text-sm text-[var(--text-primary)] hover:bg-[var(--surface-5)]"
                >
                  Close
                </button>
              </div>
            </div>
            {newWorkflowError && (
              <div className="mx-4 mt-3 rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
                {newWorkflowError}
              </div>
            )}
            <iframe
              ref={newWorkflowIframeRef}
              title="New Workflow Comfy Editor"
              src={newWorkflowBaseUrl}
              className="h-full w-full border-0"
              allow="clipboard-read; clipboard-write"
            />
          </div>
        </div>
      )}
    </>
  );
}
