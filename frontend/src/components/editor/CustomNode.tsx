"use client";

import { Presets, RenderEmit } from "rete-react-plugin";
import { BaseNode, SocketColors, SocketType } from "@/lib/nodes";
import { cn } from "@/lib/utils";
import { SelectControl } from "@/lib/rete/controls/SelectControl";
import { SelectControlComponent } from "@/components/editor/controls/SelectControlComponent";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type NodeProps = {
  data: BaseNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  emit: RenderEmit<any>;
};

/**
 * Get socket color by name
 */
function getSocketColor(name: string): string {
  if (name in SocketColors) {
    return SocketColors[name as SocketType];
  }
  return SocketColors.any;
}

/**
 * Custom node component with preview panel
 */
export function CustomNode({ data, emit }: NodeProps) {
  const statusColors = {
    idle: "border-zinc-700",
    running: "border-yellow-500 animate-pulse",
    completed: "border-green-500",
    failed: "border-red-500",
  };

  // Get node color (from the node class or default)
  const nodeColor = data.color ?? "#3b82f6";

  return (
    <div
      className={cn(
        "bg-zinc-900 rounded-lg border-2 shadow-xl min-w-[280px]",
        statusColors[data.status]
      )}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-2 border-b border-zinc-700 rounded-t-lg"
        style={{ backgroundColor: `${nodeColor}20` }}
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-white">{data.label}</span>
          {data.requiresApproval && (
            <span className="px-1.5 py-0.5 text-[10px] bg-amber-500/20 text-amber-400 rounded">
              Approval
            </span>
          )}
        </div>
        <span className="text-[10px] text-zinc-500">{data.selectedWorkflow}</span>
      </div>

      {/* Inputs */}
      {Object.entries(data.inputs).length > 0 && (
        <div className="px-2 py-2 border-b border-zinc-800">
          {Object.entries(data.inputs).map(([key, input]) => {
            if (!input) return null;
            return (
              <div key={key} className="flex items-center gap-2 py-1">
                <Presets.classic.Socket
                  data={{
                    type: "socket",
                    side: "input",
                    key,
                    nodeId: data.id,
                    socketKey: key,
                    payload: input.socket!,
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  } as any}
                  emit={emit}
                />
                <span className="text-xs text-zinc-400">{input.label || key}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Controls (Parameters) */}
      {Object.entries(data.controls).length > 0 && (
        <div className="px-4 py-2 space-y-2 border-b border-zinc-800">
          {Object.entries(data.controls).map(([key, control]) => {
            if (!control) return null;
            return (
              <div key={key}>
                <label className="text-[10px] text-zinc-500 uppercase tracking-wide">
                  {key}
                </label>
                {control instanceof SelectControl ? (
                  <SelectControlComponent data={control} />
                ) : (
                  <Presets.classic.Control
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    data={control as any}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Preview Panel */}
      <div className="p-2">
        <div className="bg-zinc-950 rounded-md overflow-hidden aspect-square flex items-center justify-center">
          {data.isExecuting ? (
            <div className="flex flex-col items-center gap-2 text-zinc-500">
              <div className="w-8 h-8 border-2 border-zinc-600 border-t-white rounded-full animate-spin" />
              <span className="text-xs">Generating...</span>
            </div>
          ) : data.previewUrl ? (
            data.previewType === "video" ? (
              <video
                src={data.previewUrl}
                className="w-full h-full object-contain"
                controls
                loop
                muted
              />
            ) : (
              <img
                src={data.previewUrl}
                alt="Preview"
                className="w-full h-full object-contain"
              />
            )
          ) : (
            <div className="text-zinc-600 text-xs">No preview</div>
          )}
        </div>
      </div>

      {/* Outputs */}
      {Object.entries(data.outputs).length > 0 && (
        <div className="px-2 py-2">
          {Object.entries(data.outputs).map(([key, output]) => {
            if (!output) return null;
            return (
              <div key={key} className="flex items-center justify-end gap-2 py-1">
                <span className="text-xs text-zinc-400">{output.label || key}</span>
                <Presets.classic.Socket
                  data={{
                    type: "socket",
                    side: "output",
                    key,
                    nodeId: data.id,
                    socketKey: key,
                    payload: output.socket!,
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  } as any}
                  emit={emit}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
