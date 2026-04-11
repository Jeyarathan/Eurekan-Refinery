import { Handle, Position, type NodeProps } from '@xyflow/react'
import { Beaker, Package } from 'lucide-react'

export interface ProductNodeData extends Record<string, unknown> {
  label: string
  volume: number
  pricePerBbl?: number | null
  isBlender?: boolean
  specBadges?: Array<{
    name: string
    status: 'pass' | 'tight' | 'fail'
    value?: string
  }>
}

const fmt = (n: number) =>
  n >= 1000 ? `${(n / 1000).toFixed(1)}k` : n.toFixed(0)

const fmtMoney = (n: number) => {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}k`
  return `$${n.toFixed(0)}`
}

function SpecBadge({
  name,
  status,
  value,
}: {
  name: string
  status: 'pass' | 'tight' | 'fail'
  value?: string
}) {
  const colors = {
    pass: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    tight: 'bg-amber-50 text-amber-700 border-amber-200',
    fail: 'bg-rose-50 text-rose-700 border-rose-200',
  }
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium ${colors[status]}`}
      title={value}
    >
      {name}
    </span>
  )
}

export function ProductNode({ data }: NodeProps) {
  const { label, volume, pricePerBbl, isBlender, specBadges } =
    data as ProductNodeData
  const revenue = pricePerBbl != null ? volume * pricePerBbl : null
  const Icon = isBlender ? Beaker : Package
  const colorClass = isBlender
    ? 'bg-violet-100 text-violet-700'
    : 'bg-emerald-100 text-emerald-700'

  return (
    <div className="min-w-[170px] rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2 !w-2 !border-slate-300 !bg-slate-300"
      />
      <div className="flex items-center gap-2">
        <div
          className={`flex h-7 w-7 items-center justify-center rounded-md ${colorClass}`}
        >
          <Icon size={14} strokeWidth={2.5} />
        </div>
        <div>
          <div className="text-sm font-semibold capitalize text-slate-900">
            {label.replace(/_/g, ' ')}
          </div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500">
            {isBlender ? 'Blend pool' : 'Product sale'}
          </div>
        </div>
      </div>
      <div className="mt-2 flex items-baseline gap-1 text-slate-700">
        <span className="text-base font-semibold tabular-nums">
          {fmt(volume)}
        </span>
        <span className="text-[10px] text-slate-500">bbl/d</span>
      </div>
      {revenue != null && (
        <div className="text-[10px] text-slate-500">
          {fmtMoney(revenue)}/d revenue
        </div>
      )}
      {specBadges && specBadges.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {specBadges.map((b) => (
            <SpecBadge key={b.name} {...b} />
          ))}
        </div>
      )}
      {!isBlender && (
        <Handle
          type="source"
          position={Position.Right}
          className="!h-2 !w-2 !border-slate-300 !bg-slate-300"
        />
      )}
      {isBlender && (
        <Handle
          type="source"
          position={Position.Right}
          className="!h-2 !w-2 !border-slate-300 !bg-slate-300"
        />
      )}
    </div>
  )
}
