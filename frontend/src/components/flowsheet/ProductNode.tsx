import { Handle, Position, type NodeProps } from '@xyflow/react'

export interface ProductNodeData extends Record<string, unknown> {
  label: string
  volume: number
  pricePerBbl?: number | null
  isBlender?: boolean
  nodeCategory?: string
  specBadges?: Array<{ name: string; status: 'pass' | 'tight' | 'fail' }>
}

const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(0)}K` : n.toFixed(0))
const fmtM = (n: number) =>
  n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : `$${(n / 1000).toFixed(0)}K`

export function ProductNode({ data }: NodeProps) {
  const { label, volume, pricePerBbl, isBlender, specBadges } = data as ProductNodeData

  if (isBlender) {
    // Funnel/blend shape
    return (
      <div className="flex flex-col items-center">
        <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-slate-300" />
        <div className="flex h-10 w-16 items-center justify-center rounded-lg border border-violet-300 bg-violet-50 text-center">
          <div>
            <div className="text-[8px] font-semibold text-violet-800">BLD</div>
            <div className="text-[9px] tabular-nums font-bold text-violet-900">{fmt(volume)}</div>
          </div>
        </div>
        {specBadges && specBadges.length > 0 && (
          <div className="mt-0.5 flex gap-0.5">
            {specBadges.map((b) => (
              <span
                key={b.name}
                className={`h-1.5 w-1.5 rounded-full ${
                  b.status === 'pass' ? 'bg-emerald-500' : b.status === 'tight' ? 'bg-amber-500' : 'bg-rose-500'
                }`}
                title={b.name}
              />
            ))}
          </div>
        )}
        <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-slate-300" />
      </div>
    )
  }

  // Product sale: compact arrow/chevron
  const revenue = pricePerBbl != null ? volume * pricePerBbl : null
  return (
    <div className="flex items-center gap-1">
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-slate-300" />
      <div className="text-emerald-600 text-[10px]">▸</div>
      <div>
        <div className="text-[9px] font-semibold text-slate-800 capitalize leading-tight">
          {label.replace(/_/g, ' ')} <span className="tabular-nums font-normal text-slate-600">{fmt(volume)}</span>
        </div>
        {revenue != null && revenue > 0 && (
          <div className="text-[8px] tabular-nums text-slate-500">{fmtM(revenue)}/d</div>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-slate-300" />
    </div>
  )
}
