"use client";

import { useRef } from "react";
import type { ChainExecution } from "@/stores/executionStore";

interface WorkflowToolbarProps {
  currentChainName: string;
  onChainNameChange: (name: string) => void;
  onImport: (jsonString: string) => void;
  onExport: () => void;
  onOpenNewWorkflow: () => void;
  isOpeningNewWorkflow: boolean;
  waitEnabled: boolean;
  onWaitEnabledChange: (value: boolean) => void;
  waitSeconds: number;
  onWaitSecondsChange: (value: number) => void;
  execution: ChainExecution | null;
  hasNodes: boolean;
  onExecute: () => void;
  onCancelExecution: () => void;
  onAbortAllExecution: () => void;
  onClearExecution: () => void;
  onToggleSettings: () => void;
  isLoading: boolean;
  error: string | null;
}

export function WorkflowToolbar({
  currentChainName,
  onChainNameChange,
  onImport,
  onExport,
  onOpenNewWorkflow,
  isOpeningNewWorkflow,
  waitEnabled,
  onWaitEnabledChange,
  waitSeconds,
  onWaitSecondsChange,
  execution,
  hasNodes,
  onExecute,
  onCancelExecution,
  onAbortAllExecution,
  onClearExecution,
  onToggleSettings,
  isLoading,
  error,
}: WorkflowToolbarProps) {
  const importInputRef = useRef<HTMLInputElement>(null);

  return (
    <div className="flex items-center justify-between px-4 py-2 bg-[var(--surface-1)] border-b border-[var(--border)]">
      <div className="flex items-center gap-4">
        <h1 className="text-base font-semibold text-[var(--text-primary)]">Graviton</h1>
        <div className="h-4 w-px bg-[var(--border)]" />
        <input
          type="text"
          value={currentChainName}
          onChange={(e) => onChainNameChange(e.target.value)}
          className="px-2 py-1 bg-transparent border border-transparent hover:border-[var(--border)] focus:border-[var(--brand-primary)] rounded text-sm text-[var(--text-secondary)] focus:outline-none transition-colors"
          placeholder="Chain name..."
        />
        <div className="flex items-center gap-2">
          <input
            ref={importInputRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              const reader = new FileReader();
              reader.onload = (event) => onImport(event.target?.result as string);
              reader.readAsText(file);
              e.target.value = "";
            }}
          />
          <button
            onClick={() => importInputRef.current?.click()}
            className="px-3 py-1.5 text-sm bg-[var(--surface-4)] hover:bg-[var(--surface-5)] text-[var(--text-primary)] rounded-md transition-colors"
          >
            Import
          </button>
          <button
            onClick={onExport}
            className="px-3 py-1.5 text-sm bg-[var(--surface-4)] hover:bg-[var(--surface-5)] text-[var(--text-primary)] rounded-md transition-colors"
          >
            Export
          </button>
          <button
            onClick={onOpenNewWorkflow}
            disabled={isOpeningNewWorkflow}
            className="px-3 py-1.5 text-sm bg-[var(--brand-secondary)] hover:opacity-90 text-white rounded-md transition-colors disabled:opacity-50"
          >
            {isOpeningNewWorkflow ? "Opening..." : "New Workflow"}
          </button>
          <div className="flex items-center gap-2 px-2 py-1 bg-[var(--surface-3)] rounded-md">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={waitEnabled}
                onChange={(e) => onWaitEnabledChange(e.target.checked)}
                className="w-3.5 h-3.5 rounded border-[var(--border)] bg-[var(--surface-4)] text-[var(--brand-primary)] focus:ring-0 focus:ring-offset-0 cursor-pointer"
              />
              <span className="text-xs text-[var(--text-secondary)]">Wait</span>
            </label>
            {waitEnabled && (
              <div className="flex items-center gap-1">
                <input
                  type="number"
                  min={0}
                  value={waitSeconds}
                  onChange={(e) => onWaitSecondsChange(Math.max(0, parseInt(e.target.value, 10) || 0))}
                  className="w-14 px-1.5 py-0.5 text-xs text-center bg-[var(--surface-4)] border border-[var(--border)] rounded text-[var(--text-primary)] focus:outline-none focus:border-[var(--brand-secondary)]"
                />
                <span className="text-xs text-[var(--text-muted)]">sec</span>
              </div>
            )}
          </div>

          {!execution ? (
            <button
              onClick={onExecute}
              disabled={!hasNodes}
              className="px-3 py-1.5 text-sm bg-[var(--brand-success)] hover:opacity-90 text-white rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Execute
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <span
                className={`text-xs px-2 py-1 rounded ${
                  execution.status === "running"
                    ? "bg-blue-500/20 text-blue-400"
                    : execution.status === "completed"
                      ? "bg-green-500/20 text-green-400"
                      : "bg-red-500/20 text-red-400"
                }`}
              >
                {execution.status === "running"
                  ? "Running..."
                  : execution.status === "completed"
                    ? "Completed"
                    : "Failed"}
              </span>
              {execution.status === "running" ? (
                <>
                  <button
                    onClick={onCancelExecution}
                    className="px-3 py-1.5 text-sm bg-red-600 hover:bg-red-700 text-white rounded-md transition-colors"
                  >
                    Cancel
                  </button>
                </>
              ) : (
                <button
                  onClick={onClearExecution}
                  className="px-3 py-1.5 text-sm bg-[var(--surface-4)] hover:bg-[var(--surface-5)] text-[var(--text-primary)] rounded-md transition-colors"
                >
                  Clear
                </button>
              )}
            </div>
          )}
          <button
            onClick={onAbortAllExecution}
            className="px-3 py-1.5 text-sm bg-red-700 hover:bg-red-800 text-white rounded-md transition-colors"
            title="Cancel all queued/running chains"
          >
            Abort All
          </button>
        </div>
      </div>
      <div className="flex items-center gap-4">
        <button
          onClick={onToggleSettings}
          className="rounded-md p-1.5 text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-4)] hover:text-[var(--text-primary)]"
          title="Settings"
          aria-label="Open settings"
        >
          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 0 0 2.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 0 0 1.065 2.572c1.757.426 1.757 2.924 0 3.35a1.724 1.724 0 0 0-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 0 0-2.572 1.065c-.426 1.757-2.924 1.757-3.35 0a1.724 1.724 0 0 0-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 0 0-1.065-2.572c-1.757-.426-1.757-2.924 0-3.35a1.724 1.724 0 0 0 1.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.607 2.296.07 2.572-1.065Z"
            />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
          </svg>
        </button>
        {isLoading && <span className="text-xs text-[var(--text-muted)]">Loading nodes...</span>}
        {error && <span className="text-xs text-red-500">Error: {error}</span>}
        <span className="text-xs text-[var(--text-muted)]">Double-click to add nodes • Click node to edit</span>
      </div>
    </div>
  );
}
