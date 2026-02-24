export interface EdgeColorKey {
  id: string;
  source?: string | null;
  target?: string | null;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}

function hashString(value: string): number {
  let hash = 2166136261; // FNV-1a basis
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function getEdgeColor(edge: EdgeColorKey): string {
  // Color by source node identity for easier visual tracing across fan-out edges.
  // Fall back to full key if source is unavailable.
  const key = edge.source && edge.source.length > 0
    ? edge.source
    : `${edge.id}|${edge.source ?? ""}|${edge.sourceHandle ?? ""}|${edge.target ?? ""}|${edge.targetHandle ?? ""}`;
  const hash = hashString(key);
  const hue = hash % 360;
  return `hsl(${hue} 78% 62%)`;
}
