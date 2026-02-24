import { create } from "zustand";

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:8001";

interface ChangedStep {
  stepId: string;
  newParameters: Record<string, unknown>;
}

interface ExecutionPlanResult {
  mode: "execute" | "regenerate" | "cached";
  result: Record<string, unknown>;
  signature: string;
  changedSteps: ChangedStep[];
}

interface ChainExecutionStore {
  isSubmitting: boolean;
  error: string | null;
  executeWithCache: (
    chain: Record<string, unknown>,
    opts: { signature: string | null; force: boolean; levelWaitSeconds: number }
  ) => Promise<ExecutionPlanResult>;
  clearError: () => void;
}

function asStepMap(chain: Record<string, unknown>): Record<string, Record<string, unknown>> {
  const raw = chain.steps;
  if (!Array.isArray(raw)) return {};
  const mapped: Record<string, Record<string, unknown>> = {};
  for (const step of raw) {
    if (!step || typeof step !== "object") continue;
    const id = (step as { id?: unknown }).id;
    if (typeof id !== "string" || !id.trim()) continue;
    mapped[id] = step as Record<string, unknown>;
  }
  return mapped;
}

function findChangedSteps(
  oldChain: Record<string, unknown>,
  newChain: Record<string, unknown>
): ChangedStep[] {
  const oldSteps = asStepMap(oldChain);
  const newSteps = asStepMap(newChain);
  const changedIds: string[] = [];
  const changedParams: Record<string, Record<string, unknown>> = {};

  for (const [stepId, newStep] of Object.entries(newSteps)) {
    const oldStep = oldSteps[stepId];
    if (!oldStep) {
      changedIds.push(stepId);
      const params = newStep.parameters;
      changedParams[stepId] = params && typeof params === "object" ? (params as Record<string, unknown>) : {};
      continue;
    }
    if (JSON.stringify(oldStep) === JSON.stringify(newStep)) continue;

    changedIds.push(stepId);
    const oldParams = oldStep.parameters;
    const newParams = newStep.parameters;
    const oldParamObj =
      oldParams && typeof oldParams === "object" ? (oldParams as Record<string, unknown>) : {};
    const newParamObj =
      newParams && typeof newParams === "object" ? (newParams as Record<string, unknown>) : {};
    const diff: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(newParamObj)) {
      if (JSON.stringify(oldParamObj[key]) !== JSON.stringify(value)) {
        diff[key] = value;
      }
    }
    changedParams[stepId] = diff;
  }

  const ordered: ChangedStep[] = [];
  const orderedSteps = Array.isArray(newChain.steps) ? newChain.steps : [];
  for (const step of orderedSteps) {
    if (!step || typeof step !== "object") continue;
    const stepId = (step as { id?: unknown }).id;
    if (typeof stepId !== "string") continue;
    if (!changedIds.includes(stepId)) continue;
    ordered.push({
      stepId,
      newParameters: changedParams[stepId] || {},
    });
  }

  return ordered;
}

export const useChainExecutionStore = create<ChainExecutionStore>((set) => ({
  isSubmitting: false,
  error: null,

  clearError: () => set({ error: null }),

  executeWithCache: async (chain, opts) => {
    set({ isSubmitting: true, error: null });
    try {
      let signature = opts.signature;
      if (!signature) {
        const hashResponse = await fetch(`${GATEWAY_URL}/chains/hash`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chain }),
        });
        if (!hashResponse.ok) {
          const payload = await hashResponse.json().catch(() => ({}));
          throw new Error(payload?.detail || "Failed to calculate chain hash");
        }
        const hashPayload = await hashResponse.json();
        signature = String(hashPayload?.hash || "").trim();
        if (!signature) {
          throw new Error("Hash response did not include signature");
        }
      }

      if (signature && !opts.force) {
        const byHash = await fetch(`${GATEWAY_URL}/chains/by-hash/${encodeURIComponent(signature)}`);
        if (!byHash.ok) {
          const payload = await byHash.json().catch(() => ({}));
          throw new Error(payload?.detail || "Failed to query chain by hash");
        }
        const byHashPayload = await byHash.json();
        const latestCompleted = byHashPayload?.latest_completed;
        const storedDefinition = byHashPayload?.chain_definition;

        if (latestCompleted && storedDefinition && typeof storedDefinition === "object") {
          const changedSteps = findChangedSteps(storedDefinition as Record<string, unknown>, chain);
          if (changedSteps.length === 0) {
            return {
              mode: "cached",
              signature,
              changedSteps,
              result: {
                chain_id: latestCompleted.chain_id,
                job_id: latestCompleted.job_id,
                status: "completed",
                cached: true,
              },
            };
          }
        }
      }

      const executeResponse = await fetch(
        `${GATEWAY_URL}/chains/execute?force=${opts.force ? "true" : "false"}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chain,
            level_wait_seconds: opts.levelWaitSeconds,
          }),
        }
      );
      const executePayload = await executeResponse.json().catch(() => ({}));
      if (!executeResponse.ok) {
        throw new Error(executePayload?.detail || "Failed to execute chain");
      }

      return {
        mode: executePayload?.cached ? "cached" : "execute",
        signature,
        changedSteps: [],
        result: executePayload as Record<string, unknown>,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to execute chain";
      set({ error: message });
      throw new Error(message);
    } finally {
      set({ isSubmitting: false });
    }
  },
}));
