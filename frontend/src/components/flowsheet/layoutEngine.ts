/**
 * Rule-based layout engine. Maps optimization result nodes to pixel positions.
 * No dagre, no React Flow — positions are deterministic from node type/id.
 */

import type { CutProperties } from '../../types'

// Swim lane Y-bands
export const LANES = {
  LIGHT_ENDS: { y: 50, h: 70, label: 'LIGHT ENDS', bg: '#fff9c4' },
  NAPHTHA:    { y: 140, h: 90, label: 'NAPHTHA PROCESSING', bg: '#e0edff' },
  FCC:        { y: 260, h: 140, label: 'FCC COMPLEX', bg: '#f3e8ff' },
  HCU:        { y: 430, h: 60, label: 'HYDROCRACKING', bg: '#ede7f6' },
  DISTILLATE: { y: 520, h: 90, label: 'DISTILLATE', bg: '#dcfce7' },
  HEAVY:      { y: 640, h: 70, label: 'HEAVY END', bg: '#fee2e2' },
} as const

export type LaneName = keyof typeof LANES

// X-axis columns
export const COLS = {
  CRUDE:   50,
  CDU:     130,
  TRUNK:   200,   // CDU output trunk line x-coordinate
  STAGE1:  280,
  STAGE2:  400,
  STAGE3:  530,
  BLEND:   660,
  PRODUCT: 750,
} as const

export const SVG_W = 830
export const SVG_H = 740

export interface LayoutNode {
  id: string
  x: number
  y: number
  w: number
  h: number
  label: string
  rate: number
  rateStr: string
  nodeType: 'crude' | 'cdu' | 'unit' | 'blend' | 'product'
  lane?: LaneName
  dimmed: boolean
  badge?: string     // e.g. FCC conversion %
  utilPct: number
}

export interface LayoutEdge {
  id: string
  sourceId: string
  targetId: string
  label: string
  volume: number
  color: string
  streamType: string
  properties: Record<string, unknown>
}

export interface LayoutResult {
  nodes: LayoutNode[]
  edges: LayoutEdge[]
  lanes: Array<{ id: string; label: string; x: number; y: number; w: number; h: number; bg: string }>
  trunkTop: number
  trunkBottom: number
}

function fmtRate(r: number): string {
  if (r <= 0) return '–'
  if (r >= 1000) return `${(r / 1000).toFixed(0)}K`
  return r.toFixed(0)
}

// Assign a swim lane based on unit_id
function assignLane(id: string): LaneName | undefined {
  if (id === 'isom_c4') return 'LIGHT_ENDS'
  if (['reformer_1', 'arom_reformer', 'isom_c56', 'splitter_1', 'nht_1'].some(u => id === u)) return 'NAPHTHA'
  if (['fcc_1', 'goht_1', 'scanfiner_1', 'alky_1', 'dimersol'].some(u => id === u)) return 'FCC'
  if (id === 'hcu_1') return 'HCU'
  if (['kht_1', 'dht_1'].some(u => id === u)) return 'DISTILLATE'
  if (['vacuum_1', 'coker_1'].some(u => id === u)) return 'HEAVY'
  return undefined
}

// Assign X position by processing order within lane
function assignX(id: string): number {
  const map: Record<string, number> = {
    splitter_1: COLS.STAGE1,
    nht_1: COLS.STAGE2,
    reformer_1: COLS.STAGE3,
    arom_reformer: COLS.STAGE3,
    isom_c56: COLS.STAGE2,
    goht_1: COLS.STAGE1,
    fcc_1: COLS.STAGE2,
    scanfiner_1: COLS.STAGE3,
    alky_1: COLS.STAGE3,
    dimersol: COLS.STAGE3,
    hcu_1: COLS.STAGE2,
    kht_1: COLS.STAGE1,
    dht_1: COLS.STAGE2,
    vacuum_1: COLS.STAGE1,
    coker_1: COLS.STAGE2,
    isom_c4: COLS.STAGE2,
  }
  return map[id] ?? COLS.STAGE1
}

// Y offset within a lane (to avoid stacking on same pixel)
function laneYOffset(id: string): number {
  const offsets: Record<string, number> = {
    arom_reformer: -28,
    isom_c56: 38,
    scanfiner_1: -30,
    alky_1: 10,
    dimersol: 60,
  }
  return offsets[id] ?? 0
}

// Classify stream color by name/endpoints
function streamColor(label: string, _sourceId: string, targetId: string): { color: string; type: string } {
  const l = label.toLowerCase()
  if (l.includes('naphtha') || l.includes('ln') || l.includes('hn') || l.includes('reformate') || l.includes('isomerate'))
    return { color: '#3b82f6', type: 'naphtha' }
  if (l.includes('vgo') || l.includes('hcn') || l.includes('treated vgo') || l.includes('vacuum vgo'))
    return { color: '#8b5cf6', type: 'vgo' }
  if (l.includes('kero') || l.includes('jet') || l.includes('diesel') || l.includes('ulsd') || l.includes('lco'))
    return { color: '#06b6d4', type: 'distillate' }
  if (l.includes('resid') || l.includes('coker') || l.includes('coke') || l.includes('bypass') || l.includes('unconverted') || l.includes('fuel'))
    return { color: '#78716c', type: 'heavy' }
  if (l.includes('lpg') || l.includes('c3') || l.includes('c4') || l.includes('propylene') || l.includes('gas'))
    return { color: '#f59e0b', type: 'gas' }
  if (l.includes('gasoline') || l.includes('alkylate') || l.includes('dimate') || l.includes('raffinate'))
    return { color: '#059669', type: 'product' }
  // Crude streams
  if (targetId === 'cdu_1') return { color: '#f59e0b', type: 'crude' }
  return { color: '#94a3b8', type: 'other' }
}

// Node dimensions — UNIT_W must accommodate longest name ("Aromatics Reformer")
const PROD_W = 65
const PROD_H = 26
const UNIT_W = 100
const UNIT_H = 38
const CDU_W = 90
const CDU_H = 50
const BLEND_W = 80
const BLEND_H = 30

// Product Y by name (aligned with source lane)
function productY(id: string): number {
  const map: Record<string, number> = {
    sale_lpg: LANES.LIGHT_ENDS.y + 10,
    sale_gasoline: LANES.NAPHTHA.y + 20,
    sale_naphtha: LANES.NAPHTHA.y + 60,
    sale_btx: LANES.NAPHTHA.y - 20,
    sale_jet: LANES.DISTILLATE.y,
    sale_diesel: LANES.DISTILLATE.y + 40,
    sale_fuel_oil: LANES.HEAVY.y + 10,
    sale_coke: LANES.HEAVY.y + 45,
  }
  return map[id] ?? LANES.FCC.y + 50
}

function cutPropsToRecord(props: CutProperties | undefined | null): Record<string, unknown> {
  if (!props) return {}
  const result: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(props)) {
    if (v != null) result[k] = v
  }
  return result
}

export function calculateLayout(
  flowNodes: Array<{ node_id: string; node_type: string; display_name: string; throughput: number }>,
  flowEdges: Array<{ edge_id: string; source_node: string; dest_node: string; display_name: string; volume: number; properties?: CutProperties }>,
  fccConversion?: number | null,
  showFullDiagram = true,
): LayoutResult {
  const nodes: LayoutNode[] = []
  const edges: LayoutEdge[] = []

  // Classify nodes
  const purchases = flowNodes.filter(n => n.node_type === 'purchase')
  const units = flowNodes.filter(n => n.node_type === 'unit')
  const blends = flowNodes.filter(n => n.node_type === 'blend_header')
  const products = flowNodes.filter(n => n.node_type === 'sale_point')

  // Crude feed nodes — active on top, inactive below (or hidden in Live Flow).
  // With 40 crudes in Full Diagram, arrange in 2 columns to fit.
  const visibleCrudes = purchases.filter(n => showFullDiagram || n.throughput > 1)
  // Sort: active crudes first (descending throughput), then inactive alphabetically
  const sortedCrudes = [...visibleCrudes].sort((a, b) => {
    if (a.throughput > 1 && b.throughput <= 1) return -1
    if (a.throughput <= 1 && b.throughput > 1) return 1
    if (a.throughput > 1 && b.throughput > 1) return b.throughput - a.throughput
    return a.display_name.localeCompare(b.display_name)
  })

  const useTwoColumns = sortedCrudes.length > 12
  const colSpacing = useTwoColumns ? 55 : 0    // offset for second column
  const rowSpacing = useTwoColumns ? 16 : Math.min(30, 400 / Math.max(sortedCrudes.length, 1))
  const itemsPerCol = useTwoColumns ? Math.ceil(sortedCrudes.length / 2) : sortedCrudes.length
  const totalHeight = itemsPerCol * rowSpacing
  const crudeStartY = LANES.FCC.y - totalHeight / 2

  sortedCrudes.forEach((n, i) => {
    const col = useTwoColumns ? Math.floor(i / itemsPerCol) : 0
    const row = useTwoColumns ? (i % itemsPerCol) : i
    nodes.push({
      id: n.node_id, x: COLS.CRUDE + col * colSpacing, y: crudeStartY + row * rowSpacing,
      w: 14, h: 14, label: n.display_name, rate: n.throughput,
      rateStr: fmtRate(n.throughput), nodeType: 'crude',
      dimmed: n.throughput <= 1, utilPct: 0,
    })
  })

  // CDU node (special tall node)
  const cdu = flowNodes.find(n => n.node_id === 'cdu_1')
  if (cdu) {
    nodes.push({
      id: 'cdu_1', x: COLS.CDU, y: LANES.FCC.y - 20,
      w: CDU_W, h: CDU_H, label: cdu.display_name, rate: cdu.throughput,
      rateStr: fmtRate(cdu.throughput), nodeType: 'cdu',
      dimmed: false, utilPct: Math.min(100, (cdu.throughput / 80000) * 100),
    })
  }

  // Process unit nodes
  units.forEach(n => {
    if (n.node_id === 'cdu_1') return // already added
    const lane = assignLane(n.node_id)
    if (!lane) return
    const laneInfo = LANES[lane]
    const x = assignX(n.node_id)
    const yBase = laneInfo.y + laneInfo.h / 2 - UNIT_H / 2
    const yOff = laneYOffset(n.node_id)
    const dimmed = n.throughput <= 1
    if (!showFullDiagram && dimmed) return
    nodes.push({
      id: n.node_id, x, y: yBase + yOff,
      w: UNIT_W, h: UNIT_H, label: n.display_name, rate: n.throughput,
      rateStr: fmtRate(n.throughput), nodeType: 'unit', lane,
      dimmed,
      badge: n.node_id === 'fcc_1' && fccConversion ? `${fccConversion.toFixed(0)}%` : undefined,
      utilPct: 0,
    })
  })

  // Blend header
  blends.forEach(n => {
    nodes.push({
      id: n.node_id, x: COLS.BLEND, y: LANES.NAPHTHA.y + LANES.NAPHTHA.h / 2 - BLEND_H / 2 + 10,
      w: BLEND_W, h: BLEND_H, label: n.display_name, rate: n.throughput,
      rateStr: fmtRate(n.throughput), nodeType: 'blend',
      dimmed: false, utilPct: 0,
    })
  })

  // Product sale nodes
  products.forEach(n => {
    if (!showFullDiagram && n.throughput <= 1) return
    nodes.push({
      id: n.node_id, x: COLS.PRODUCT, y: productY(n.node_id),
      w: PROD_W, h: PROD_H, label: n.display_name, rate: n.throughput,
      rateStr: fmtRate(n.throughput), nodeType: 'product',
      dimmed: n.throughput <= 1, utilPct: 0,
    })
  })

  // Edges
  const nodeMap = new Map(nodes.map(n => [n.id, n]))
  flowEdges.forEach(e => {
    if (!showFullDiagram && e.volume <= 1) return
    if (!nodeMap.has(e.source_node) || !nodeMap.has(e.dest_node)) return
    const { color, type } = streamColor(e.display_name, e.source_node, e.dest_node)
    edges.push({
      id: e.edge_id,
      sourceId: e.source_node,
      targetId: e.dest_node,
      label: e.display_name,
      volume: e.volume,
      color,
      streamType: type,
      properties: cutPropsToRecord(e.properties),
    })
  })

  // Active lanes (hide empty lanes in Live Flow)
  const activeNodeLanes = new Set(
    nodes.filter(n => n.lane && !n.dimmed).map(n => n.lane),
  )
  const visibleLanes = Object.entries(LANES)
    .filter(([key]) => showFullDiagram || activeNodeLanes.has(key as LaneName))
    .map(([key, info]) => ({
      id: key,
      label: info.label,
      x: COLS.STAGE1 - 20,
      y: info.y,
      w: COLS.BLEND - COLS.STAGE1 + 90,
      h: info.h,
      bg: info.bg,
    }))

  // Trunk line extents
  const unitYs = nodes.filter(n => n.nodeType === 'unit' || n.nodeType === 'blend' || n.nodeType === 'product').map(n => n.y)
  const trunkTop = unitYs.length > 0 ? Math.min(...unitYs, LANES.LIGHT_ENDS.y) - 10 : LANES.LIGHT_ENDS.y - 10
  const trunkBottom = unitYs.length > 0
    ? Math.max(...unitYs.map(y => {
        const node = nodes.find(n => n.y === y)
        return y + (node?.h ?? 38)
      }), LANES.HEAVY.y + LANES.HEAVY.h) + 10
    : LANES.HEAVY.y + LANES.HEAVY.h + 10

  return { nodes, edges, lanes: visibleLanes, trunkTop, trunkBottom }
}
