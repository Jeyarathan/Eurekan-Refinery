import { Handle, Position, type NodeProps } from '@xyflow/react'

export interface UnitNodeData extends Record<string, unknown> {
  label: string
  unitId: string
  throughput: number
  capacity?: number
  conversion?: number | null
  regenUtilPct?: number | null
  binding?: boolean
  bindingHint?: string
  nodeCategory?: string
  areaColor?: string
}

const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(0)}K` : n.toFixed(0))

export function UnitNode({ data }: NodeProps) {
  const {
    label, throughput, capacity, conversion,
    binding, bindingHint, areaColor,
  } = data as UnitNodeData

  const util = capacity && capacity > 0 ? Math.min(throughput / capacity * 100, 100) : 0
  const barColor = util >= 95 ? 'bg-rose-500' : util >= 80 ? 'bg-amber-500' : 'bg-emerald-500'

  return (
    <div
      className={`rounded-lg border bg-white shadow-sm ${
        binding ? 'ring-2 ring-amber-300 animate-pulse' : ''
      }`}
      style={{ borderLeftWidth: 4, borderLeftColor: areaColor || '#cbd5e1', minWidth: 110 }}
      title={binding && bindingHint ? bindingHint : undefined}
    >
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-slate-300" />

      <div className="flex items-baseline justify-between gap-2 px-2.5 py-1.5">
        <span className="text-[10px] font-semibold text-slate-900">{label}</span>
        <span className="text-[9px] tabular-nums text-slate-600">{fmt(throughput)}</span>
      </div>

      {/* Conversion badge for FCC */}
      {conversion != null && (
        <div className="absolute -top-2 -right-2 rounded-full bg-indigo-600 px-1.5 py-0.5 text-[8px] font-bold text-white">
          {conversion.toFixed(0)}%
        </div>
      )}

      {/* Utilization bar */}
      <div className="h-1 w-full overflow-hidden rounded-b-lg bg-slate-100">
        <div className={`h-full ${barColor}`} style={{ width: `${util}%` }} />
      </div>

      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-slate-300" />
    </div>
  )
}
