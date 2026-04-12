import { Handle, Position, type NodeProps } from '@xyflow/react'
import { Droplet } from 'lucide-react'

export interface PurchaseNodeData extends Record<string, unknown> {
  label: string
  volume: number
  dimmed?: boolean
  nodeCategory?: string
}

const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(0)}K` : n.toFixed(0))

export function PurchaseNode({ data }: NodeProps) {
  const { label, volume, dimmed } = data as PurchaseNodeData
  return (
    <div className={`flex flex-col items-center gap-0.5 ${dimmed ? 'opacity-30' : ''}`}>
      <div className="flex h-7 w-7 items-center justify-center rounded-full bg-amber-100 text-amber-700">
        <Droplet size={12} strokeWidth={2.5} />
      </div>
      <div className="text-[9px] font-semibold text-slate-800 leading-tight">{label}</div>
      {volume > 1 && (
        <div className="text-[8px] tabular-nums text-slate-500">{fmt(volume)}</div>
      )}
      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-slate-300" />
    </div>
  )
}
