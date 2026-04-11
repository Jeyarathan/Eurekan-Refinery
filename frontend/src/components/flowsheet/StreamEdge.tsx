import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  type EdgeProps,
} from '@xyflow/react'

export interface StreamEdgeData extends Record<string, unknown> {
  label?: string
  volume: number
  maxVolume: number
  economicValue?: number
}

const fmt = (n: number) =>
  n >= 1000 ? `${(n / 1000).toFixed(1)}k` : n.toFixed(0)

export function StreamEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  markerEnd,
}: EdgeProps) {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  })

  const { volume, maxVolume } = (data as StreamEdgeData) ?? {
    volume: 0,
    maxVolume: 1,
  }
  // Width: 2px to 12px proportional to volume
  const ratio = maxVolume > 0 ? volume / maxVolume : 0
  const strokeWidth = Math.max(2, Math.min(12, 2 + 10 * ratio))

  // Color: lighter for low volume, darker (indigo) for high volume
  const intensity = Math.max(0.25, ratio)
  const color = `rgba(79, 70, 229, ${intensity.toFixed(2)})`

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={{ stroke: color, strokeWidth }}
        markerEnd={markerEnd}
      />
      {volume > 0 && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: 'none',
            }}
            className="rounded border border-slate-200 bg-white px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-slate-700 shadow-sm"
          >
            {fmt(volume)} bbl/d
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}
