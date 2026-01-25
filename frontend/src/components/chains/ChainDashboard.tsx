"use client";

/**
 * ChainDashboard - Shows artifacts organized by execution levels for a selected chain version
 */

import { useEffect, useState, useMemo } from "react";
import { useChainStore, type Artifact, type ChainStep } from "@/stores/chainStore";
import { VideoPlayer } from "@/components/ui/VideoPlayer";

interface StepDefinition {
  id: string;
  workflow: string;
  depends_on?: string[];
}

interface ChainDefinition {
  name: string;
  steps: StepDefinition[];
}

interface ChainDashboardProps {
  onClose: () => void;
}

// Calculate execution levels from dependencies
function calculateExecutionLevels(steps: StepDefinition[]): Map<string, number> {
  const levels = new Map<string, number>();
  const stepMap = new Map(steps.map((s) => [s.id, s]));

  function getLevel(stepId: string, visited: Set<string> = new Set()): number {
    if (levels.has(stepId)) return levels.get(stepId)!;
    if (visited.has(stepId)) return 0; // Circular dependency protection

    visited.add(stepId);
    const step = stepMap.get(stepId);
    if (!step || !step.depends_on || step.depends_on.length === 0) {
      levels.set(stepId, 0);
      return 0;
    }

    const maxDepLevel = Math.max(...step.depends_on.map((dep) => getLevel(dep, visited)));
    const level = maxDepLevel + 1;
    levels.set(stepId, level);
    return level;
  }

  for (const step of steps) {
    getLevel(step.id);
  }

  return levels;
}

export function ChainDashboard({ onClose }: ChainDashboardProps) {
  const { chainArtifacts, isLoadingArtifacts, selectedVersionId, fetchChainDefinition } = useChainStore();
  const [definition, setDefinition] = useState<ChainDefinition | null>(null);

  // Fetch chain definition to get dependency info
  useEffect(() => {
    if (selectedVersionId) {
      fetchChainDefinition(selectedVersionId).then((result) => {
        if (result?.definition) {
          setDefinition(result.executed_definition ?? result.definition as unknown as ChainDefinition);
        }
      });
    }
  }, [selectedVersionId, fetchChainDefinition]);

  // Calculate execution levels and group steps
  const stepsByLevel = useMemo(() => {
    if (!chainArtifacts) return [];

    // If no definition yet, show all steps in level 0
    if (!definition) {
      return [chainArtifacts.steps];
    }

    const levels = calculateExecutionLevels(definition.steps);
    const maxLevel = Math.max(...Array.from(levels.values()), 0);

    // Group steps by level
    const grouped: ChainStep[][] = Array.from({ length: maxLevel + 1 }, () => []);

    for (const step of chainArtifacts.steps) {
      const level = levels.get(step.step_id) ?? 0;
      grouped[level].push(step);
    }

    return grouped;
  }, [chainArtifacts, definition]);

  if (!chainArtifacts) {
    return null;
  }

  // Get status color
  const getStatusColor = (status: string) => {
    switch (status) {
      case "completed":
        return "text-green-400";
      case "running":
        return "text-blue-400";
      case "failed":
        return "text-red-400";
      default:
        return "text-gray-400";
    }
  };

  // Format file size
  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  // Render artifact preview based on type
  const renderArtifactPreview = (artifact: Artifact) => {
    if (artifact.file_type === "image") {
      return (
        <img
          src={artifact.url}
          alt={artifact.filename}
          className="w-full h-32 object-cover rounded"
        />
      );
    }
    if (artifact.file_type === "video") {
      return (
        <VideoPlayer
          url={artifact.url}
          className="w-full h-32 rounded"
        />
      );
    }
    if (artifact.file_type === "audio") {
      return (
        <div className="w-full h-32 flex items-center justify-center bg-[var(--surface-3)] rounded">
          <audio src={artifact.url} controls className="w-full px-2" />
        </div>
      );
    }
    // Unknown type
    return (
      <div className="w-full h-32 flex items-center justify-center bg-[var(--surface-3)] rounded">
        <svg className="w-8 h-8 text-[var(--text-muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-[90vw] max-w-5xl h-[80vh] bg-[var(--surface-1)] rounded-lg shadow-xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)]">
          <div>
            <h2 className="text-lg font-semibold text-[var(--text-primary)]">
              {chainArtifacts.chain_name}
            </h2>
            <div className="flex items-center gap-3 mt-1">
              <span className="text-sm text-[var(--text-muted)]">
                Version {chainArtifacts.version}
              </span>
              <span className={`text-sm ${getStatusColor(chainArtifacts.status)}`}>
                {chainArtifacts.status}
              </span>
            </div>
            {chainArtifacts.error_message && (
              <div className="mt-2 px-3 py-2 bg-red-500/10 border border-red-500/30 rounded text-sm text-red-400">
                {chainArtifacts.error_message}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-[var(--surface-3)] rounded-md transition-colors"
          >
            <svg className="w-5 h-5 text-[var(--text-muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {isLoadingArtifacts ? (
            <div className="flex items-center justify-center h-full">
              <div className="animate-spin w-8 h-8 border-2 border-[var(--text-muted)] border-t-transparent rounded-full" />
            </div>
          ) : chainArtifacts.steps.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-[var(--text-muted)]">
              <svg className="w-16 h-16 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
              </svg>
              <p>No artifacts found</p>
            </div>
          ) : (
            <div className="space-y-8">
              {stepsByLevel.map((levelSteps, levelIndex) => (
                levelSteps.length > 0 && (
                  <div key={levelIndex}>
                    {/* Level header */}
                    <div className="flex items-center gap-3 mb-4">
                      <div className="flex items-center gap-2">
                        <div className="w-6 h-6 flex items-center justify-center rounded bg-[var(--brand-primary)] text-xs font-medium text-white">
                          {levelIndex + 1}
                        </div>
                        <span className="text-sm font-medium text-[var(--text-secondary)]">
                          Level {levelIndex + 1}
                        </span>
                      </div>
                      <div className="flex-1 h-px bg-[var(--border)]" />
                      <span className="text-xs text-[var(--text-muted)]">
                        {levelSteps.length} step{levelSteps.length > 1 ? "s" : ""}
                      </span>
                    </div>

                    {/* Steps in this level (horizontal layout) */}
                    <div className="flex gap-4 overflow-x-auto pb-2">
                      {levelSteps.map((step: ChainStep) => (
                        <div
                          key={step.step_id}
                          className="flex-shrink-0 w-72 bg-[var(--surface-2)] rounded-lg p-4"
                        >
                          {/* Step header */}
                          <div className="flex items-center gap-2 mb-3">
                            <div className={`w-2 h-2 rounded-full ${
                              step.status === "completed" ? "bg-green-500" :
                              step.status === "failed" ? "bg-red-500" :
                              step.status === "running" ? "bg-blue-500" : "bg-gray-500"
                            }`} />
                            <h3 className="text-sm font-medium text-[var(--text-primary)] truncate flex-1">
                              {step.workflow_name}
                            </h3>
                            <span className={`text-xs ${getStatusColor(step.status)}`}>
                              {step.status}
                            </span>
                          </div>

                          {/* Step error message */}
                          {step.error_message && (
                            <div className="mb-3 px-2 py-1.5 bg-red-500/10 border border-red-500/30 rounded text-xs text-red-400 truncate" title={step.error_message}>
                              {step.error_message}
                            </div>
                          )}

                          {/* Artifacts */}
                          {step.artifacts.length === 0 ? (
                            <p className="text-xs text-[var(--text-muted)] italic">
                              No artifacts
                            </p>
                          ) : (
                            <div className="space-y-2">
                              {step.artifacts.slice(0, 2).map((artifact: Artifact) => (
                                <a
                                  key={artifact.id}
                                  href={artifact.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="block relative group"
                                >
                                  {renderArtifactPreview(artifact)}
                                  <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity rounded">
                                    <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                                    </svg>
                                  </div>
                                </a>
                              ))}
                              {step.artifacts.length > 2 && (
                                <p className="text-xs text-[var(--text-muted)] text-center">
                                  +{step.artifacts.length - 2} more
                                </p>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
