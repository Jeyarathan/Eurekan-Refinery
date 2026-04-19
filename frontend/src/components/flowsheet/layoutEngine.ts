/**
 * Rule-based layout engine. Maps optimization result nodes to pixel positions.
 * No dagre, no React Flow — positions are deterministic from node type/id.
 */

import type { CutProperties } from '../../types'

// Swim lane Y-bands
// NAPHTHA grew from h=90 to h=140 to cleanly stack arom_reformer above
// reformer_1 above isom_c56 without label overlap. Downstream lanes
// shifted down +50 to preserve 30px gaps. UTILITIES (light gray) holds
// the H2 header bus along the top and plant-fuel / H2-plant units below.
export const LANES = {
  LIGHT_ENDS: { y: 50, h: 70, label: 'LIGHT ENDS', bg: '#fff9c4' },
  NAPHTHA:    { y: 140, h: 160, label: 'NAPHTHA PROCESSING', bg: '#e0edff' },
  FCC:        { y: 330, h: 140, label: 'FCC COMPLEX', bg: '#f3e8ff' },
  HCU:        { y: 500, h: 60, label: 'HYDROCRACKING', bg: '#ede7f6' },
  DISTILLATE: { y: 590, h: 90, label: 'DISTILLATE', bg: '#dcfce7' },
  HEAVY:      { y: 710, h: 70, label: 'HEAVY END', bg: '#fee2e2' },
  UTILITIES:  { y: 795, h: 80, label: 'UTILITIES', bg: '#f3f4f6' },
} as const

export type LaneName = keyof typeof LANES

// X-axis columns
// Layout: [Crude col1 | Crude col2 | CDU | Process lanes | Blend | Products]
// Wide horizontal spread so the natural content aspect (~1.7:1) fills a
// typical landscape container (~1.75:1) without leaving big side gutters.
export const COLS = {
  CRUDE:   60,     // active crudes + crude col 1 (inactive); 60px left-pad reserves
                   // room for the rate label rendered to the LEFT of the dot.
  CRUDE_COL2: 180, // inactive crudes col 2
  CDU:     320,
  TRUNK:   450,    // CDU output trunk line x-coordinate (CDU right edge = 410)
  STAGE1:  510,
  STAGE2:  780,
  STAGE3:  1050,
  BLEND:   1260,
  PRODUCT: 1410,
} as const

export const SVG_W = 1500
export const SVG_H = 885

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

export interface ContentBounds {
  x: number; y: number; w: number; h: number
}

export interface LayoutResult {
  nodes: LayoutNode[]
  edges: LayoutEdge[]
  lanes: Array<{ id: string; label: string; x: number; y: number; w: number; h: number; bg: string }>
  trunkTop: number
  trunkBottom: number
  bounds: ContentBounds  // bounding box of all content for viewBox
}

function fmtRate(r: number): string {
  if (r <= 0) return ''
  if (r >= 1000) return `${(r / 1000).toFixed(0)}K`
  return r.toFixed(0)
}

// Assign a swim lane based on unit_id
function assignLane(id: string): LaneName | undefined {
  if (['isom_c4', 'ugp_1', 'sgp_1'].some(u => id === u)) return 'LIGHT_ENDS'
  if (['reformer_1', 'arom_reformer', 'isom_c56', 'splitter_1', 'nht_1'].some(u => id === u)) return 'NAPHTHA'
  if (['fcc_1', 'goht_1', 'scanfiner_1', 'alky_1', 'dimersol'].some(u => id === u)) return 'FCC'
  if (id === 'hcu_1') return 'HCU'
  if (['kht_1', 'dht_1'].some(u => id === u)) return 'DISTILLATE'
  if (['vacuum_1', 'coker_1'].some(u => id === u)) return 'HEAVY'
  if (id === 'pfs_1') return 'UTILITIES'
  if (id === 'h2_plant') return 'UTILITIES'
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
    // Light Ends lane — left-to-right: UGP, SGP, C4 Isom
    ugp_1: COLS.STAGE1,
    sgp_1: COLS.STAGE2,
    isom_c4: COLS.STAGE3,
    // Utilities lane — pfs_1 center-left, h2_plant further right
    pfs_1: COLS.STAGE2,
    h2_plant: COLS.STAGE3,
  }
  return map[id] ?? COLS.STAGE1
}

// Y offset within a lane (to avoid stacking on same pixel).
// NAPHTHA is h=160, center y=220, UNIT_H=38 → yBase=201.
//   arom_reformer at -45 → y=156 (16px below lane top=140)
//   reformer_1 at 0 → y=201 (7px gap below arom_reformer)
//   isom_c56 at +45 → y=246 (7px gap below reformer_1; 16px margin from lane bottom=300)
function laneYOffset(id: string): number {
  const offsets: Record<string, number> = {
    arom_reformer: -45,
    isom_c56: 45,
    scanfiner_1: -30,
    alky_1: 10,
    dimersol: 60,
  }
  return offsets[id] ?? 0
}

// Classify stream color by name/endpoints
function streamColor(label: string, sourceId: string, targetId: string): { color: string; type: string } {
  const l = label.toLowerCase()
  // Utility flows into Plant Fuel System render as muted dashed lines.
  if (targetId === 'pfs_1') return { color: '#9ca3af', type: 'utility' }
  // Hydrogen network — distinct magenta to stand out from liquid flows.
  if (l === 'h2' || l.includes('hydrogen') || sourceId === 'h2_header' || targetId === 'h2_header')
    return { color: '#ec4899', type: 'h2' }
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
// Each finished product has its own compact blender/pool node positioned
// at the BLEND column, vertically aligned with its downstream sale node.
const BLEND_W = 80
const BLEND_H = 32

// Product Y by economic priority — high-value products at top, byproducts
// at the bottom. Spacing 55px gives 8-product stack from y=90 to y=475.
function productY(id: string): number {
  const priority: Record<string, number> = {
    sale_gasoline: 0,
    sale_diesel:   1,
    sale_jet:      2,
    sale_naphtha:  3,
    sale_fuel_oil: 4,
    sale_lpg:      5,
    sale_coke:     6,
    sale_btx:      7,
  }
  const idx = priority[id] ?? 8
  return 90 + idx * 55
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

  // Classify nodes — 'process' nodes (utilities like Plant Fuel System)
  // render with the same box style as units but are visually bound to
  // the Utilities swim lane.
  const purchases = flowNodes.filter(n => n.node_type === 'purchase')
  const units = flowNodes.filter(n => n.node_type === 'unit' || n.node_type === 'process')
  const blends = flowNodes.filter(n => n.node_type === 'blend_header')
  const products = flowNodes.filter(n => n.node_type === 'sale_point')

  // Crude feed nodes — active crudes prominent on top, inactive dimmed below.
  // Sort: active first (descending throughput), then inactive alphabetically.
  const visibleCrudes = purchases.filter(n => showFullDiagram || n.throughput > 1)
  const activeCrudes = visibleCrudes.filter(n => n.throughput > 1)
    .sort((a, b) => b.throughput - a.throughput)
  const inactiveCrudes = visibleCrudes.filter(n => n.throughput <= 1)
    .sort((a, b) => a.display_name.localeCompare(b.display_name))

  // Active crudes: single column, compact 28px spacing
  const ACTIVE_SPACING = 28
  const INACTIVE_SPACING = 20
  // Second column of inactive crudes sits at COLS.CRUDE_COL2 absolute
  const COL2_OFFSET = COLS.CRUDE_COL2 - COLS.CRUDE

  // Center the active crude stack on the CDU so every active crude feeds
  // horizontally into the CDU with a clean H→V orthogonal path. The −7
  // offset aligns the 14px crude dot's center with cduCenterY.
  const inactivePerCol = Math.ceil(inactiveCrudes.length / 2)
  const inactiveHeight = inactivePerCol * INACTIVE_SPACING
  const cduCenterY = LANES.FCC.y - 20 + CDU_H / 2
  const activeBlockH = activeCrudes.length > 0
    ? (activeCrudes.length - 1) * ACTIVE_SPACING
    : 0
  // +40 bias shifts the active-crude column slightly below perfect center
  // to visually "settle" against the CDU feed port and make room for
  // stream labels above the first crude.
  const crudeStartY = activeCrudes.length > 0
    ? cduCenterY - activeBlockH / 2 - 7 + 40
    : LANES.FCC.y - Math.min(inactiveHeight / 2, 200)

  let cy = crudeStartY
  activeCrudes.forEach((n) => {
    nodes.push({
      id: n.node_id, x: COLS.CRUDE, y: cy,
      w: 14, h: 14, label: n.display_name, rate: n.throughput,
      rateStr: fmtRate(n.throughput), nodeType: 'crude',
      dimmed: false, utilPct: 0,
    })
    cy += ACTIVE_SPACING
  })

  // Inactive crudes: two columns, compact spacing. After the loop cy has
  // already advanced by ACTIVE_SPACING (28) past the last active dot, so
  // center-to-center = 28 + bump. Bump of +4 yields ~18px visual gap
  // (32 center-to-center minus the 14px dot diameter).
  if (inactiveCrudes.length > 0) {
    cy += 4
    const inactiveStartY = cy
    inactiveCrudes.forEach((n, i) => {
      const col = i < inactivePerCol ? 0 : 1
      const row = col === 0 ? i : i - inactivePerCol
      nodes.push({
        id: n.node_id, x: COLS.CRUDE + col * COL2_OFFSET, y: inactiveStartY + row * INACTIVE_SPACING,
        w: 14, h: 14, label: n.display_name, rate: n.throughput,
        rateStr: fmtRate(n.throughput), nodeType: 'crude',
        dimmed: true, utilPct: 0,
      })
    })
  }

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

  // Blend header — one compact pool per product, positioned at COLS.BLEND
  // and vertically aligned with its downstream sale node.
  const POOL_TO_PRODUCT: Record<string, string> = {
    blend_gasoline: 'sale_gasoline',
    pool_diesel:    'sale_diesel',
    pool_jet:       'sale_jet',
    pool_fuel_oil:  'sale_fuel_oil',
    pool_lpg:       'sale_lpg',
    pool_naphtha:   'sale_naphtha',
    pool_btx:       'sale_btx',
  }
  blends.forEach(n => {
    // H2 header renders as a standard unit node in the UTILITIES lane
    // alongside pfs_1 and h2_plant — no distinct bus/banner styling.
    if (n.node_id === 'h2_header') {
      const laneInfo = LANES.UTILITIES
      nodes.push({
        id: n.node_id,
        x: COLS.STAGE1,
        y: laneInfo.y + laneInfo.h / 2 - UNIT_H / 2,
        w: UNIT_W, h: UNIT_H, label: n.display_name, rate: n.throughput,
        rateStr: fmtRate(n.throughput), nodeType: 'unit', lane: 'UTILITIES',
        dimmed: false, utilPct: 0,
      })
      return
    }
    const productId = POOL_TO_PRODUCT[n.node_id]
    const y = productId ? productY(productId) - BLEND_H / 2 + PROD_H / 2
                        : LANES.NAPHTHA.y + 50
    nodes.push({
      id: n.node_id, x: COLS.BLEND, y,
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

  // Potential edges — render dashed/muted "ghost" flows in Full Diagram mode
  // so idle units don't look orphaned. Only shown when BOTH endpoints exist
  // as nodes and there's no actual edge between them already.
  if (showFullDiagram) {
    const POTENTIAL_EDGES: Array<[string, string, string]> = [
      // [source, target, label]
      ['cdu_1', 'coker_1', 'Vac Residue'],
      ['coker_1', 'pool_naphtha', 'Coker Naphtha'],
      ['coker_1', 'pool_diesel', 'Coker Diesel'],
      ['coker_1', 'pool_fuel_oil', 'Coker Gas Oil'],
      ['cdu_1', 'isom_c4', 'nC4'],
      ['isom_c4', 'alky_1', 'iC4'],
      ['cdu_1', 'goht_1', 'VGO'],
      ['goht_1', 'fcc_1', 'Treated VGO'],
      ['fcc_1', 'scanfiner_1', 'HCN'],
      ['scanfiner_1', 'blend_gasoline', 'Treated HCN'],
    ]
    const existingPairs = new Set(edges.map(e => `${e.sourceId}->${e.targetId}`))
    POTENTIAL_EDGES.forEach(([src, tgt, label], i) => {
      if (!nodeMap.has(src) || !nodeMap.has(tgt)) return
      if (existingPairs.has(`${src}->${tgt}`)) return
      edges.push({
        id: `potential_${i}`,
        sourceId: src,
        targetId: tgt,
        label,
        volume: 0,
        color: '#9ca3af',
        streamType: 'potential',
        properties: {},
      })
    })
  }

  // Active lanes (hide empty lanes in Live Flow)
  const activeNodeLanes = new Set(
    nodes.filter(n => n.lane && !n.dimmed).map(n => n.lane),
  )
  const visibleLanes = Object.entries(LANES)
    .filter(([key]) => showFullDiagram || activeNodeLanes.has(key as LaneName))
    .map(([key, info]) => ({
      id: key,
      label: info.label,
      x: COLS.STAGE1 - 30,
      // Lane bg ends before BLEND column so Blender + Products sit in their
      // own dedicated vertical strip, visually outside the process lanes.
      y: info.y,
      w: COLS.BLEND - COLS.STAGE1 + 10,
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

  // Compute content bounding box from all nodes + lanes for viewBox
  const PAD = 25
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const n of nodes) {
    // Active crudes render rate text to the LEFT of the dot — reserve 36px
    // of extra left-pad in the bounds so the rate doesn't clip.
    const leftPad = n.nodeType === 'crude' ? 40 : 10
    minX = Math.min(minX, n.x - leftPad)
    minY = Math.min(minY, n.y - 10)
    maxX = Math.max(maxX, n.x + n.w + 10)
    maxY = Math.max(maxY, n.y + n.h + 10)
  }
  for (const l of visibleLanes) {
    minX = Math.min(minX, l.x)
    minY = Math.min(minY, l.y)
    maxX = Math.max(maxX, l.x + l.w)
    maxY = Math.max(maxY, l.y + l.h)
  }
  if (!isFinite(minX)) { minX = 0; minY = 0; maxX = SVG_W; maxY = SVG_H }
  const bounds: ContentBounds = {
    x: minX - PAD, y: minY - PAD,
    w: (maxX - minX) + PAD * 2,
    h: (maxY - minY) + PAD * 2,
  }

  return { nodes, edges, lanes: visibleLanes, trunkTop, trunkBottom, bounds }
}
