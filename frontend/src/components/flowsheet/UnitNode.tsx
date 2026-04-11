import { Handle, Position, type NodeProps } from '@xyflow/react'
import { Factory } from 'lucide-react'

export interface UnitNodeData extends Record<string, unknown> {
  label: string
  unitId: string
  throughput: number
  capacity?: number
  conversion?: number | null
  regenUtilPct?: number | null
  binding?: boolean
  bindingHint?: string
}

const fmt = (n: number) => `${(n / 1000).toFixed(1)}k`

function UtilizationBar({ pct }: { pct: number }) {
  const clamped = Math.max(0, Math.min(100, pct))
  const color =
    clamped >= 95
      ? 'bg-rose-500'
      : clamped >= 80
        ? 'bg-amber-500'
        : 'bg-emerald-500'
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
      <div
        className={`h-full ${color} transition-all`}
        style={{ width: `${clamped}%` }}
      />
    </div>
  )
}

export function UnitNode({ data }: NodeProps) {
  const {
    label,
    throughput,
    capacity,
    conversion,
    regenUtilPct,
    binding,
    bindingHint,
  } = data as UnitNodeData
  const cduUtil = capacity ? (throughput / capacity) * 100 : 0

  return (
    <div
      className={`min-w-[200px] rounded-lg border bg-white px-4 py-3 shadow-sm ${
        binding
          ? 'animate-pulse border-amber-400 ring-2 ring-amber-200'
          : 'border-slate-200'
      }`}
      title={binding && bindingHint ? bindingHint : undefined}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2 !w-2 !border-slate-300 !bg-slate-300"
      />
      <div className="flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-indigo-100 text-indigo-700">
          <Factory size={16} strokeWidth={2.5} />
        </div>
        <div>
          <div className="text-sm font-semibold text-slate-900">{label}</div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500">
            Process unit
          </div>
        </div>
      </div>
      <div className="mt-3 space-y-2">
        <div>
          <div className="flex items-baseline justify-between">
            <span className="text-[10px] uppercase tracking-wide text-slate-500">
              Throughput
            </span>
            <span className="text-sm font-semibold tabular-nums text-slate-900">
              {fmt(throughput)}{' '}
              <span className="text-[10px] font-normal text-slate-500">bbl/d</span>
            </span>
          </div>
          {capacity != null && (
            <div className="mt-1">
              <UtilizationBar pct={cduUtil} />
              <div className="mt-0.5 text-[10px] text-slate-500">
                {cduUtil.toFixed(0)}% of {fmt(capacity)} bbl/d
              </div>
            </div>
          )}
        </div>
        {conversion != null && (
          <div>
            <div className="flex items-baseline justify-between">
              <span className="text-[10px] uppercase tracking-wide text-slate-500">
                Conversion
              </span>
              <span className="text-sm font-semibold tabular-nums text-slate-900">
                {conversion.toFixed(1)}%
              </span>
            </div>
          </div>
        )}
        {regenUtilPct != null && (
          <div>
            <div className="flex items-baseline justify-between">
              <span className="text-[10px] uppercase tracking-wide text-slate-500">
                Regen temp
              </span>
              <span className="text-sm font-semibold tabular-nums text-slate-900">
                {regenUtilPct.toFixed(0)}%
              </span>
            </div>
            <div className="mt-1">
              <UtilizationBar pct={regenUtilPct} />
            </div>
          </div>
        )}
      </div>
      <Handle
        type="source"
        position={Position.Right}
        className="!h-2 !w-2 !border-slate-300 !bg-slate-300"
      />
    </div>
  )
}
