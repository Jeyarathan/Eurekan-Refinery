import { useState } from 'react'
import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  type EdgeProps,
} from '@xyflow/react'

export interface StreamEdgeData extends Record<string, unknown> {
  volume: number
  maxVolume: number
  dimmed?: boolean
  streamName?: string
}

const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}K` : n.toFixed(0))

export function StreamEdge({
  id,
  sourceX, sourceY, targetX, targetY,
  sourcePosition, targetPosition,
  data, markerEnd,
}: EdgeProps) {
  const [hovered, setHovered] = useState(false)
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX, sourceY, targetX, targetY,
    sourcePosition, targetPosition,
    borderRadius: 4,    // near-orthogonal 90-degree turns
    offset: 20,         // distance before first turn
  })

  const { volume, maxVolume, dimmed, streamName } = (data as StreamEdgeData) ?? {
    volume: 0, maxVolume: 1, dimmed: false,
  }

  if (dimmed) {
    return (
      <BaseEdge
        id={id} path={edgePath} markerEnd={markerEnd}
        style={{ stroke: 'rgba(148,163,184,0.3)', strokeWidth: 1, strokeDasharray: '4 3' }}
      />
    )
  }

  // Width: 1px < 1K, 3px 1K-10K, 6px > 10K
  const strokeWidth = volume < 1000 ? 1 : volume < 10000 ? 3 : 6
  const opacity = Math.max(0.3, Math.min(1, volume / (maxVolume || 1)))
  const color = `rgba(99, 102, 241, ${opacity.toFixed(2)})`

  return (
    <>
      {/* Invisible wide hit-target for hover */}
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={20}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      />
      <BaseEdge
        id={id} path={edgePath} markerEnd={markerEnd}
        style={{ stroke: color, strokeWidth }}
      />
      {hovered && volume > 0 && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: 'none',
            }}
            className="z-50 rounded border border-slate-200 bg-white px-2 py-1 text-[10px] shadow-lg"
          >
            <div className="font-semibold text-slate-800">
              {streamName || 'Stream'}: {fmt(volume)} bbl/d
            </div>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}
