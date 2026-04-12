/**
 * CDU hub node — tall narrow column with vertically stacked output ports.
 * Ports are ordered top (lightest) to bottom (heaviest) by boiling point.
 */

import { Handle, Position, type NodeProps } from '@xyflow/react'

export interface CduNodeData extends Record<string, unknown> {
  label: string
  throughput: number
  capacity: number
  nodeCategory?: string
  originalNodeType?: string
}

const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(0)}K` : n.toFixed(0))

// Named output handles — the edge's sourceHandle must match one of these IDs.
// Order: top (light) → bottom (heavy).
const OUTPUT_PORTS = [
  { id: 'lpg', label: 'LPG', pct: 8 },
  { id: 'ln', label: 'LN', pct: 22 },
  { id: 'hn', label: 'HN', pct: 36 },
  { id: 'kero', label: 'Kero', pct: 50 },
  { id: 'vgo', label: 'VGO', pct: 64 },
  { id: 'diesel', label: 'Dies', pct: 78 },
  { id: 'resid', label: 'VR', pct: 92 },
]

export function CduNode({ data }: NodeProps) {
  const { label, throughput, capacity } = data as CduNodeData
  const util = capacity > 0 ? Math.min(throughput / capacity * 100, 100) : 0
  const barColor = util >= 95 ? 'bg-rose-500' : util >= 80 ? 'bg-amber-500' : 'bg-emerald-500'

  return (
    <div
      className="relative rounded-lg border bg-white shadow-sm"
      style={{ width: 56, height: 200, borderLeftWidth: 4, borderLeftColor: '#6366f1' }}
    >
      {/* Single input handle (left centre) */}
      <Handle
        type="target"
        position={Position.Left}
        id="in"
        className="!h-2 !w-2 !border-0 !bg-slate-300"
        style={{ top: '50%' }}
      />

      {/* Label + throughput */}
      <div className="flex flex-col items-center justify-center h-full px-1">
        <span className="text-[9px] font-bold text-slate-900">{label}</span>
        <span className="text-[8px] tabular-nums text-slate-600">{fmt(throughput)}</span>
      </div>

      {/* Utilization bar at bottom */}
      <div className="absolute bottom-0 left-0 right-0 h-1 overflow-hidden rounded-b-lg bg-slate-100">
        <div className={`h-full ${barColor}`} style={{ width: `${util}%` }} />
      </div>

      {/* Named output handles — vertically spaced */}
      {OUTPUT_PORTS.map((port) => (
        <Handle
          key={port.id}
          type="source"
          position={Position.Right}
          id={port.id}
          className="!h-1.5 !w-1.5 !border-0 !bg-indigo-300"
          style={{ top: `${port.pct}%` }}
        />
      ))}
    </div>
  )
}
