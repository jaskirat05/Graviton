import { create } from "zustand";

export interface ContextMenuState {
  show: boolean;
  position: { x: number; y: number };
  flowPosition: { x: number; y: number };
}

interface WorkflowEditorStore {
  selectedNodeId: string | null;
  updateMode: boolean;
  showDashboard: boolean;
  showSettings: boolean;
  waitEnabled: boolean;
  waitSeconds: number;
  chainId: string | null;
  definitionSignature: string | null;
  contextMenu: ContextMenuState;
  exportOutput: string;
  isNewWorkflowEditorOpen: boolean;
  isOpeningNewWorkflowEditor: boolean;
  isSavingNewWorkflow: boolean;
  newWorkflowError: string | null;
  newWorkflowBridgeStatus: string;
  newWorkflowBaseUrl: string | null;
  newWorkflowName: string;
  newWorkflowServerName: string;

  setSelectedNodeId: (nodeId: string | null) => void;
  setUpdateMode: (value: boolean) => void;
  setShowDashboard: (value: boolean) => void;
  setShowSettings: (value: boolean) => void;
  setWaitEnabled: (value: boolean) => void;
  setWaitSeconds: (value: number) => void;
  setChainId: (chainId: string | null) => void;
  setDefinitionSignature: (signature: string | null) => void;
  setContextMenu: (value: ContextMenuState | ((prev: ContextMenuState) => ContextMenuState)) => void;
  setExportOutput: (value: string) => void;
  setIsNewWorkflowEditorOpen: (value: boolean) => void;
  setIsOpeningNewWorkflowEditor: (value: boolean) => void;
  setIsSavingNewWorkflow: (value: boolean) => void;
  setNewWorkflowError: (value: string | null) => void;
  setNewWorkflowBridgeStatus: (value: string) => void;
  setNewWorkflowBaseUrl: (value: string | null) => void;
  setNewWorkflowName: (value: string) => void;
  setNewWorkflowServerName: (value: string) => void;
  resetNewWorkflowEditor: () => void;
  resetForNewChain: () => void;
}

const initialContextMenu: ContextMenuState = {
  show: false,
  position: { x: 0, y: 0 },
  flowPosition: { x: 0, y: 0 },
};

export const useWorkflowEditorStore = create<WorkflowEditorStore>((set) => ({
  selectedNodeId: null,
  updateMode: false,
  showDashboard: false,
  showSettings: false,
  waitEnabled: false,
  waitSeconds: 0,
  chainId: null,
  definitionSignature: null,
  contextMenu: initialContextMenu,
  exportOutput: "",
  isNewWorkflowEditorOpen: false,
  isOpeningNewWorkflowEditor: false,
  isSavingNewWorkflow: false,
  newWorkflowError: null,
  newWorkflowBridgeStatus: "idle",
  newWorkflowBaseUrl: null,
  newWorkflowName: "new_workflow",
  newWorkflowServerName: "",

  setSelectedNodeId: (selectedNodeId) => set({ selectedNodeId }),
  setUpdateMode: (updateMode) => set({ updateMode }),
  setShowDashboard: (showDashboard) => set({ showDashboard }),
  setShowSettings: (showSettings) => set({ showSettings }),
  setWaitEnabled: (waitEnabled) => set({ waitEnabled }),
  setWaitSeconds: (waitSeconds) => set({ waitSeconds }),
  setChainId: (chainId) => set({ chainId }),
  setDefinitionSignature: (definitionSignature) => set({ definitionSignature }),
  setContextMenu: (value) =>
    set((state) => ({
      contextMenu: typeof value === "function" ? value(state.contextMenu) : value,
    })),
  setExportOutput: (exportOutput) => set({ exportOutput }),
  setIsNewWorkflowEditorOpen: (isNewWorkflowEditorOpen) => set({ isNewWorkflowEditorOpen }),
  setIsOpeningNewWorkflowEditor: (isOpeningNewWorkflowEditor) => set({ isOpeningNewWorkflowEditor }),
  setIsSavingNewWorkflow: (isSavingNewWorkflow) => set({ isSavingNewWorkflow }),
  setNewWorkflowError: (newWorkflowError) => set({ newWorkflowError }),
  setNewWorkflowBridgeStatus: (newWorkflowBridgeStatus) => set({ newWorkflowBridgeStatus }),
  setNewWorkflowBaseUrl: (newWorkflowBaseUrl) => set({ newWorkflowBaseUrl }),
  setNewWorkflowName: (newWorkflowName) => set({ newWorkflowName }),
  setNewWorkflowServerName: (newWorkflowServerName) => set({ newWorkflowServerName }),
  resetNewWorkflowEditor: () =>
    set({
      isNewWorkflowEditorOpen: false,
      isOpeningNewWorkflowEditor: false,
      isSavingNewWorkflow: false,
      newWorkflowError: null,
      newWorkflowBridgeStatus: "idle",
      newWorkflowBaseUrl: null,
      newWorkflowName: "new_workflow",
      newWorkflowServerName: "",
    }),
  resetForNewChain: () =>
    set({
      selectedNodeId: null,
      updateMode: false,
      exportOutput: "",
      contextMenu: initialContextMenu,
      chainId: null,
      definitionSignature: null,
    }),
}));
