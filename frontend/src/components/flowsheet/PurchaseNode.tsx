import { Handle, Position, type NodeProps } from '@xyflow/react'
import { Droplet } from 'lucide-react'

export interface PurchaseNodeData extends Record<string, unknown> {
  label: string
  volume: number
  pricePerBbl?: number | null
}

const fmt = (n: number) =>
  n >= 1000 ? `${(n / 1000).toFixed(1)}k` : n.toFixed(0)

export function PurchaseNode({ data }: NodeProps) {
  const { label, volume, pricePerBbl } = data as PurchaseNodeData
  return (
    <div className="min-w-[150px] rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <div className="flex items-center gap-2">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-amber-100 text-amber-700">
          <Droplet size={14} strokeWidth={2.5} />
        </div>
        <div>
          <div className="text-sm font-semibold text-slate-900">{label}</div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500">
            Crude purchase
          </div>
        </div>
      </div>
      <div className="mt-2 flex items-baseline gap-1 text-slate-700">
        <span className="text-base font-semibold tabular-nums">
          {fmt(volume)}
        </span>
        <span className="text-[10px] text-slate-500">bbl/d</span>
      </div>
      {pricePerBbl != null && (
        <div className="text-[10px] text-slate-500">${pricePerBbl.toFixed(2)}/bbl</div>
      )}
      <Handle
        type="source"
        position={Position.Right}
        className="!h-2 !w-2 !border-slate-300 !bg-slate-300"
      />
    </div>
  )
}
