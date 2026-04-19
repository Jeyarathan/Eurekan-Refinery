import { useCallback, useMemo, useRef, useState } from 'react'
import type { PlanningResult } from '../../types'
import { calculateLayout, SVG_W, SVG_H, COLS, type LayoutNode, type LayoutEdge, type ContentBounds } from './layoutEngine'
import { routePath, pathToSvg, pathMidpoint } from './pathRouter'

// Design tokens matching reference
const C = {
  bg: '#f5f6f8', white: '#fff', surface: '#f8f9fb',
  border: '#e5e7eb', borderHi: '#d1d5db',
  text: '#1f2937', textDim: '#6b7280', textMuted: '#9ca3af',
  accent: '#7c3aed', accentLight: '#ede9fe',
  green: '#059669', greenLight: '#ecfdf5', greenBorder: '#86efac',
  red: '#dc2626', yellow: '#d97706',
}
const MONO = "'JetBrains Mono', 'Fira Code', monospace"
const SANS = "-apple-system, 'Segoe UI', system-ui, sans-serif"

// Stream tooltip via foreignObject
function StreamTooltip({ edge, x, y }: { edge: LayoutEdge | null; x: number; y: number }) {
  if (!edge) return null
  let tx = x + 16, ty = y - 100
  if (tx + 260 > x + 300) tx = x - 276
  if (ty < 5) ty = 5
  const props = edge.properties ?? {}
  const propEntries = Object.entries(props).filter(([, v]) => v != null && v !== 0)
  return (
    <foreignObject x={tx} y={ty} width={260} height={180} style={{ pointerEvents: 'none' }}>
      <div style={{
        background: C.white, borderRadius: 10, padding: 10,
        boxShadow: '0 8px 30px rgba(0,0,0,0.12)',
        border: `1.5px solid ${edge.color}44`,
        fontFamily: SANS, fontSize: 11,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
          <div style={{ width: 8, height: 8, borderRadius: 2, background: edge.color }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, fontSize: 12 }}>{edge.label}</div>
            <div style={{ color: C.textDim, fontSize: 10 }}>{edge.sourceId} &rarr; {edge.targetId}</div>
          </div>
          <div style={{ fontFamily: MONO, fontWeight: 700, fontSize: 13, color: edge.color }}>
            {edge.volume >= 1000 ? `${(edge.volume / 1000).toFixed(0)}K` : edge.volume.toFixed(0)}
          </div>
        </div>
        {propEntries.length > 0 && (
          <div style={{
            background: C.surface, borderRadius: 6, padding: '5px 7px',
            border: `1px solid ${C.border}`,
          }}>
            <div style={{ fontSize: 9, color: C.textMuted, fontWeight: 700, marginBottom: 3 }}>PROPERTIES</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
              {propEntries.slice(0, 6).map(([k, v]) => (
                <span key={k} style={{
                  padding: '1px 5px', background: C.white, borderRadius: 3,
                  border: `1px solid ${C.border}`, fontSize: 10,
                }}>
                  <span style={{ color: C.textMuted }}>{k}:</span>{' '}
                  <span style={{ fontFamily: MONO, fontWeight: 600 }}>
                    {typeof v === 'number' ? v.toFixed(2) : String(v)}
                  </span>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </foreignObject>
  )
}

interface Props {
  result: PlanningResult
  showFullDiagram?: boolean
  highlightedNodeId?: string | null
  onNodeClick?: (nodeId: string | null) => void
}

export function SvgFlowsheet({
  result, showFullDiagram = false, highlightedNodeId = null, onNodeClick,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [hovUnit, setHovUnit] = useState<string | null>(null)
  const [hovEdge, setHovEdge] = useState<string | null>(null)
  const [hovPos, setHovPos] = useState({ x: 0, y: 0 })

  // Zoom/pan state — initialized lazily from layout bounds
  const [viewBox, setViewBox] = useState<ContentBounds | null>(null)
  const [isPanning, setIsPanning] = useState(false)
  const panStart = useRef({ x: 0, y: 0, vx: 0, vy: 0 })

  const flow = result.material_flow
  const period = result.periods[0]
  const fccConv = period?.fcc_result?.conversion ?? null

  const layout = useMemo(
    () => calculateLayout(flow.nodes, flow.edges, fccConv, showFullDiagram),
    [flow, fccConv, showFullDiagram],
  )

  // Auto-fit viewBox to content bounds whenever layout changes
  const vb = viewBox ?? layout.bounds
  // Reset viewBox when showFullDiagram toggles (content bounds change)
  const prevShowFull = useRef(showFullDiagram)
  if (prevShowFull.current !== showFullDiagram) {
    prevShowFull.current = showFullDiagram
    // Schedule reset on next render (can't setState during render)
    queueMicrotask(() => setViewBox(layout.bounds))
  }

  const nodeMap = useMemo(
    () => new Map(layout.nodes.map(n => [n.id, n])),
    [layout.nodes],
  )

  // Compute paths
  const edgePaths = useMemo(
    () => layout.edges.map(e => {
      const src = nodeMap.get(e.sourceId)
      const tgt = nodeMap.get(e.targetId)
      if (!src || !tgt) return { ...e, d: '', mid: [0, 0] as [number, number] }
      const pts = routePath(src, tgt)
      return { ...e, d: pathToSvg(pts), mid: pathMidpoint(pts) }
    }),
    [layout.edges, nodeMap],
  )

  // Hover logic
  const anyHov = hovUnit || hovEdge
  const isEdgeHighlighted = useCallback((e: LayoutEdge) => {
    if (!anyHov) return true
    if (hovEdge) return e.id === hovEdge
    return e.sourceId === hovUnit || e.targetId === hovUnit
  }, [anyHov, hovEdge, hovUnit])

  const isNodeHighlighted = useCallback((n: LayoutNode) => {
    if (!anyHov) return true
    if (hovUnit) return n.id === hovUnit
    if (hovEdge) {
      const edge = layout.edges.find(e => e.id === hovEdge)
      return edge ? (edge.sourceId === n.id || edge.targetId === n.id) : false
    }
    return false
  }, [anyHov, hovUnit, hovEdge, layout.edges])

  // Zoom
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault()
    const factor = e.deltaY > 0 ? 1.1 : 0.9
    setViewBox(prev => {
      const p = prev ?? layout.bounds
      const nw = p.w * factor
      const nh = p.h * factor
      const dx = (p.w - nw) / 2
      const dy = (p.h - nh) / 2
      return { x: p.x + dx, y: p.y + dy, w: nw, h: nh }
    })
  }, [layout.bounds])

  // Pan
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return
    if ((e.target as Element).closest('[data-interactive]')) return
    setIsPanning(true)
    panStart.current = { x: e.clientX, y: e.clientY, vx: vb.x, vy: vb.y }
  }, [vb])

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isPanning) return
    const svg = svgRef.current
    if (!svg) return
    const rect = svg.getBoundingClientRect()
    const scale = vb.w / rect.width
    const dx = (e.clientX - panStart.current.x) * scale
    const dy = (e.clientY - panStart.current.y) * scale
    setViewBox(prev => ({ ...(prev ?? vb), x: panStart.current.vx - dx, y: panStart.current.vy - dy }))
  }, [isPanning, vb])

  const handleMouseUp = useCallback(() => setIsPanning(false), [])
  const fitView = useCallback(() => setViewBox(layout.bounds), [layout.bounds])
  const zoomIn = useCallback(() => setViewBox(prev => {
    const p = prev ?? layout.bounds
    const nw = p.w * 0.8, nh = p.h * 0.8
    return { x: p.x + (p.w - nw) / 2, y: p.y + (p.h - nh) / 2, w: nw, h: nh }
  }), [layout.bounds])
  const zoomOut = useCallback(() => setViewBox(prev => {
    const p = prev ?? layout.bounds
    const nw = p.w * 1.25, nh = p.h * 1.25
    return { x: p.x + (p.w - nw) / 2, y: p.y + (p.h - nh) / 2, w: nw, h: nh }
  }), [layout.bounds])

  // Suppress unused variable warnings for props used by the interface contract
  void highlightedNodeId

  return (
    <div className="relative h-full w-full overflow-hidden rounded-lg border border-slate-200 bg-white">
      <svg
        ref={svgRef}
        viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
        preserveAspectRatio="xMidYMid meet"
        className="block h-full w-full"
        style={{ cursor: isPanning ? 'grabbing' : 'grab' }}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={() => { handleMouseUp(); setHovUnit(null); setHovEdge(null) }}
      >
        {/* Background */}
        <rect x={vb.x} y={vb.y} width={vb.w} height={vb.h} fill={C.bg} />

        {/* Swim lane backgrounds */}
        {layout.lanes.map(lane => (
          <g key={lane.id}>
            <rect x={lane.x} y={lane.y} width={lane.w} height={lane.h} rx={10} fill={lane.bg} stroke={C.border} />
            <text x={lane.x + 10} y={lane.y + 14} fill={C.textMuted} fontSize={8} fontWeight={700}
              letterSpacing={1.5} fontFamily={SANS}>{lane.label}</text>
          </g>
        ))}

        {/* CDU trunk line — vertical bundling line at COLS.TRUNK where all
             CDU outputs exit right and fan horizontally to downstream units.
             Rendered with solid mid-gray at ~0.5 opacity so it reads as an
             intentional plant-topology element, not a ghosted background. */}
        <path d={`M${COLS.TRUNK},${layout.trunkTop} L${COLS.TRUNK},${layout.trunkBottom}`}
          stroke="#64748b" strokeWidth={3} strokeLinecap="round" opacity={0.5} />

        {/* Stream edges */}
        {edgePaths.map(e => {
          const hi = isEdgeHighlighted(e)
          const w = Math.max(1.5, Math.min(5.5, e.volume / 8000))
          return (
            <g key={e.id}>
              {/* Wide invisible hit area */}
              <path d={e.d} fill="none" stroke="transparent" strokeWidth={Math.max(12, w + 8)}
                style={{ cursor: 'pointer' }}
                data-interactive="true"
                onMouseEnter={(ev) => {
                  const r = svgRef.current?.getBoundingClientRect()
                  if (r) {
                    const scale = vb.w / r.width
                    setHovPos({ x: vb.x + (ev.clientX - r.left) * scale, y: vb.y + (ev.clientY - r.top) * scale })
                  }
                  setHovEdge(e.id)
                }}
                onMouseMove={(ev) => {
                  const r = svgRef.current?.getBoundingClientRect()
                  if (r) {
                    const scale = vb.w / r.width
                    setHovPos({ x: vb.x + (ev.clientX - r.left) * scale, y: vb.y + (ev.clientY - r.top) * scale })
                  }
                }}
                onMouseLeave={() => setHovEdge(null)}
              />
              {/* Visible path — utility / H2 / potential streams all render
                   dashed with distinct opacity so they read as non-liquid
                   flows against the main material balance. */}
              <path d={e.d} fill="none" stroke={e.color}
                strokeWidth={hovEdge === e.id ? w + 1.5 : (e.streamType === 'utility' || e.streamType === 'potential' ? 1.5 : (e.streamType === 'h2' ? 2 : w))}
                strokeLinecap="round" strokeLinejoin="round"
                strokeDasharray={e.streamType === 'utility' ? '4 3' : (e.streamType === 'potential' ? '5 4' : (e.streamType === 'h2' ? '6 3' : undefined))}
                opacity={anyHov ? (hi ? 0.8 : 0.06) : (e.streamType === 'utility' ? 0.5 : (e.streamType === 'potential' ? 0.22 : (e.streamType === 'h2' ? 0.7 : 0.4)))}
                style={{ transition: 'opacity 0.2s', pointerEvents: 'none' }}
              />
              {/* Volume label on hover */}
              {hovEdge === e.id && (
                <text x={e.mid[0]} y={e.mid[1] - 7} fill={e.color}
                  fontSize={9} fontWeight={700} fontFamily={MONO} textAnchor="middle"
                  style={{ pointerEvents: 'none' }}>
                  {e.volume >= 1000 ? `${(e.volume / 1000).toFixed(0)}K` : e.volume.toFixed(0)}
                </text>
              )}
            </g>
          )
        })}

        {/* Crude feed nodes.
            Active crudes: rate label LEFT of dot (clear of the horizontal
              feed edge that exits rightward into the CDU); code label RIGHT.
            Inactive crudes: code only, smaller font, tighter dot. */}
        {layout.nodes.filter(n => n.nodeType === 'crude').map(n => {
          const op = anyHov && !isNodeHighlighted(n) ? 0.15 : (n.dimmed ? 0.45 : 1)
          const labelFont = n.dimmed ? 9 : 10
          const dotR = n.dimmed ? 5 : 7
          return (
            <g key={n.id} opacity={op} style={{ transition: 'opacity 0.2s' }}>
              <circle cx={n.x + 7} cy={n.y + 7} r={dotR} fill="#f59e0b" stroke="#fff"
                strokeWidth={n.dimmed ? 1 : 2} />
              {!n.dimmed && n.rateStr && (
                <text x={n.x - 4} y={n.y + 11} textAnchor="end" fill={C.text}
                  fontSize={10} fontWeight={700} fontFamily={MONO}>{n.rateStr}</text>
              )}
              <text x={n.x + 18} y={n.y + 11} fill={n.dimmed ? C.textDim : C.text}
                fontSize={labelFont} fontWeight={n.dimmed ? 500 : 700}>{n.label}</text>
            </g>
          )
        })}

        {/* CDU node */}
        {layout.nodes.filter(n => n.nodeType === 'cdu').map(n => (
          <g key={n.id} data-interactive="true" style={{ cursor: 'pointer' }}
            onMouseEnter={() => setHovUnit(n.id)} onMouseLeave={() => setHovUnit(null)}
            onClick={() => onNodeClick?.(n.id)}>
            <rect x={n.x} y={n.y} width={n.w} height={n.h} rx={7}
              fill={hovUnit === n.id ? C.accentLight : C.white}
              stroke={hovUnit === n.id ? C.accent : C.border}
              strokeWidth={hovUnit === n.id ? 2 : 1.5} />
            <text x={n.x + 8} y={n.y + 16} fill={C.text} fontSize={11} fontWeight={700}>{n.label}</text>
            <text x={n.x + n.w - 8} y={n.y + 16} textAnchor="end" fill={C.textDim}
              fontSize={10} fontFamily={MONO}>{n.rateStr}</text>
            <rect x={n.x + 8} y={n.y + n.h - 8} width={n.w - 16} height={3} rx={1.5} fill="#f3f4f6" />
            <rect x={n.x + 8} y={n.y + n.h - 8}
              width={Math.max(0, (n.w - 16) * n.utilPct / 100)} height={3} rx={1.5}
              fill={n.utilPct > 95 ? C.red : n.utilPct > 75 ? C.yellow : C.green} />
          </g>
        ))}

        {/* Process unit nodes */}
        {layout.nodes.filter(n => n.nodeType === 'unit').map(n => {
          const hi = isNodeHighlighted(n)
          const op = anyHov ? (hi ? 1 : 0.12) : 1
          const finalOp = n.dimmed ? op * 0.4 : op
          const isHov = hovUnit === n.id
          const bFg = n.utilPct > 95 ? C.red : n.utilPct > 75 ? C.yellow : n.utilPct > 0 ? C.green : '#d1d5db'
          return (
            <g key={n.id} opacity={finalOp} style={{ transition: 'opacity 0.2s', cursor: 'pointer' }}
              data-interactive="true"
              onMouseEnter={() => setHovUnit(n.id)} onMouseLeave={() => setHovUnit(null)}
              onClick={() => onNodeClick?.(n.id)}>
              <rect x={n.x} y={n.y} width={n.w} height={n.h} rx={7}
                fill={isHov ? C.accentLight : (n.dimmed ? '#f9fafb' : C.white)}
                stroke={isHov ? C.accent : C.border} strokeWidth={isHov ? 2 : 1.5} />
              <text x={n.x + 8} y={n.y + 14} fill={C.text} fontSize={10} fontWeight={600}>{n.label}</text>
              <text x={n.x + n.w - 8} y={n.y + 14} textAnchor="end" fill={C.textDim}
                fontSize={9} fontFamily={MONO}>{n.rateStr}</text>
              {n.badge && (
                <>
                  <rect x={n.x + n.w - 30} y={n.y + 2} width={26} height={13} rx={3} fill={C.green} />
                  <text x={n.x + n.w - 17} y={n.y + 11} textAnchor="middle" fill="#fff"
                    fontSize={8} fontWeight={700} fontFamily={MONO}>{n.badge}</text>
                </>
              )}
              <rect x={n.x + 8} y={n.y + n.h - 8} width={n.w - 16} height={3} rx={1.5} fill="#f3f4f6" />
              <rect x={n.x + 8} y={n.y + n.h - 8}
                width={Math.max(0, (n.w - 16) * n.utilPct / 100)} height={3} rx={1.5} fill={bFg} />
            </g>
          )
        })}

        {/* Blend header (pool) nodes — compact per-product, one per finished
            product. Label on top, throughput beneath, 4 spec placeholder dots
            at the bottom. */}
        {layout.nodes.filter(n => n.nodeType === 'blend').map(n => {
          const op = anyHov && !isNodeHighlighted(n) ? 0.12 : 1
          const isHov = hovUnit === n.id
          const dotSpacing = (n.w - 20) / 3
          return (
            <g key={n.id} opacity={op} style={{ transition: 'opacity 0.2s', cursor: 'pointer' }}
              data-interactive="true"
              onMouseEnter={() => setHovUnit(n.id)} onMouseLeave={() => setHovUnit(null)}>
              <rect x={n.x} y={n.y} width={n.w} height={n.h} rx={5}
                fill={C.greenLight} stroke={C.greenBorder} strokeWidth={isHov ? 1.75 : 1} />
              <text x={n.x + n.w / 2} y={n.y + 11} textAnchor="middle"
                fill={C.text} fontSize={9} fontWeight={700}>{n.label}</text>
              <text x={n.x + n.w / 2} y={n.y + 21} textAnchor="middle"
                fill={C.green} fontSize={9} fontFamily={MONO} fontWeight={700}>{n.rateStr}</text>
              {[0, 1, 2, 3].map(i => (
                <circle key={i} cx={n.x + 10 + i * dotSpacing} cy={n.y + n.h - 5}
                  r={1.5} fill={C.white} stroke={C.greenBorder} strokeWidth={0.8} />
              ))}
            </g>
          )
        })}

        {/* Product sale nodes */}
        {layout.nodes.filter(n => n.nodeType === 'product').map(n => {
          const op = anyHov && !isNodeHighlighted(n) ? 0.12 : (n.dimmed ? 0.4 : 1)
          return (
            <g key={n.id} opacity={op} style={{ transition: 'opacity 0.2s' }}
              onMouseEnter={() => setHovUnit(n.id)} onMouseLeave={() => setHovUnit(null)}>
              <rect x={n.x} y={n.y} width={n.w} height={n.h} rx={5}
                fill={C.white} stroke={C.border} strokeWidth={1} />
              <text x={n.x + n.w / 2} y={n.y + n.h / 2 + 1} textAnchor="middle" dominantBaseline="middle"
                fill={C.text} fontSize={9} fontWeight={600}>
                {n.label} <tspan fill={C.textDim} fontFamily={MONO} fontSize={9}>{n.rateStr}</tspan>
              </text>
            </g>
          )
        })}

        {/* Stream tooltip */}
        <StreamTooltip
          edge={hovEdge ? edgePaths.find(e => e.id === hovEdge) ?? null : null}
          x={hovPos.x} y={hovPos.y}
        />
      </svg>

      {/* Zoom controls (bottom-right) */}
      <div className="absolute bottom-3 right-3 flex flex-col gap-1">
        {[
          { label: '+', action: zoomIn },
          { label: '\u2212', action: zoomOut },
          { label: '\u229e', action: fitView },
        ].map(btn => (
          <button key={btn.label} onClick={btn.action}
            className="flex h-7 w-7 items-center justify-center rounded border border-slate-200 bg-white text-xs font-bold text-slate-600 shadow-sm hover:bg-slate-50">
            {btn.label}
          </button>
        ))}
      </div>

      {/* Legend (bottom-left) */}
      <div className="absolute bottom-3 left-3 flex gap-3 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-[9px]">
        {[
          { l: 'Naphtha', c: '#3b82f6' }, { l: 'VGO/FCC', c: '#8b5cf6' },
          { l: 'Distillate', c: '#06b6d4' }, { l: 'Heavy', c: '#78716c' },
          { l: 'Gas', c: '#f59e0b' }, { l: 'Product', c: '#059669' },
        ].map(x => (
          <div key={x.l} className="flex items-center gap-1">
            <div style={{ width: 14, height: 3, borderRadius: 1, background: x.c, opacity: 0.7 }} />
            <span className="text-slate-500">{x.l}</span>
          </div>
        ))}
      </div>

      {/* Minimap (bottom-left, above legend) */}
      <div className="absolute bottom-12 left-3 rounded border border-slate-200 bg-white shadow-sm"
        style={{ width: 160, height: 100 }}>
        <svg viewBox={`${layout.bounds.x} ${layout.bounds.y} ${layout.bounds.w} ${layout.bounds.h}`}
          width={160} height={100} style={{ display: 'block' }}
          onClick={(e) => {
            const r = (e.target as Element).closest('svg')?.getBoundingClientRect()
            if (!r) return
            const b = layout.bounds
            const sx = b.x + ((e.clientX - r.left) / r.width) * b.w
            const sy = b.y + ((e.clientY - r.top) / r.height) * b.h
            setViewBox(prev => {
              const p = prev ?? b
              return { ...p, x: sx - p.w / 2, y: sy - p.h / 2 }
            })
          }}>
          <rect x={layout.bounds.x} y={layout.bounds.y} width={layout.bounds.w} height={layout.bounds.h} fill={C.bg} />
          {layout.lanes.map(lane => (
            <rect key={lane.id} x={lane.x} y={lane.y} width={lane.w} height={lane.h} fill={lane.bg} />
          ))}
          {layout.nodes.filter(n => n.nodeType === 'unit' || n.nodeType === 'cdu').map(n => (
            <rect key={n.id} x={n.x} y={n.y} width={n.w} height={n.h}
              fill={n.dimmed ? '#d1d5db' : '#818cf8'} rx={2} />
          ))}
          {/* Viewport rectangle */}
          <rect x={vb.x} y={vb.y} width={vb.w} height={vb.h}
            fill="none" stroke={C.accent} strokeWidth={4} rx={2} opacity={0.6} />
        </svg>
      </div>
    </div>
  )
}
