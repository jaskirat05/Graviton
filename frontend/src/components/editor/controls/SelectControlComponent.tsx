/**
 * SelectControlComponent - React component for rendering SelectControl
 *
 * Renders a dropdown select element for node controls.
 * Stops event propagation to prevent interfering with node dragging.
 */

import { SelectControl } from "@/lib/rete/controls/SelectControl";

interface SelectControlComponentProps {
  data: SelectControl;
}

export function SelectControlComponent({ data }: SelectControlComponentProps) {
  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    data.setValue(e.target.value);
  };

  const handlePointerDown = (e: React.PointerEvent) => {
    e.stopPropagation();
  };

  return (
    <select
      value={data.value}
      onChange={handleChange}
      onPointerDown={handlePointerDown}
      className="w-full px-2 py-1 bg-zinc-700 border border-zinc-600 rounded text-sm text-white focus:outline-none focus:border-blue-500"
    >
      {data.options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
