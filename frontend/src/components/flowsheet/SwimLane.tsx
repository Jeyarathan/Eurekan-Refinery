/**
 * SwimLane — a labeled, colored background group node for React Flow.
 *
 * Used as a parent node to group process units into horizontal lanes
 * (Naphtha Processing, FCC Complex, Distillate, Light Ends).
 */

import { type NodeProps } from '@xyflow/react'

export interface SwimLaneData extends Record<string, unknown> {
  label: string
  color: string
  summary?: string
}

export function SwimLane({ data }: NodeProps) {
  const { label, color, summary } = data as SwimLaneData
  return (
    <div
      className="rounded-lg border border-opacity-30"
      style={{
        background: color,
        borderColor: color.replace(/[^,]+\)/, '0.3)').replace('#', ''),
        width: '100%',
        height: '100%',
        minWidth: 200,
        minHeight: 60,
      }}
    >
      <div className="flex items-center gap-2 px-3 py-1">
        <span className="text-[9px] font-semibold uppercase tracking-wider text-slate-600 opacity-70">
          {label}
        </span>
        {summary && (
          <span className="text-[8px] text-slate-500">{summary}</span>
        )}
      </div>
    </div>
  )
}
