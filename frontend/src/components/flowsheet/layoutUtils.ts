/**
 * Refinery PFD layout — boiling-point hierarchy with multi-port CDU.
 *
 * All positions are deterministic. No dagre — the refinery topology
 * is fixed, so we know exactly where each node goes.
 */

import type { Edge, Node } from '@xyflow/react'

// ---------- X columns (generous spacing) ----------
const X_CRUDE = 0
const X_CDU = 200       // CDU hub
const X_LANE_START = 420 // first process unit in any lane
const X_LANE_MID = 580   // second unit in a lane
const X_LANE_END = 740   // third unit (e.g. reformer after NHT)
const X_BLEND = 940      // gasoline blender
const X_PRODUCT = 1140   // product sale nodes

// ---------- Y swim lanes (top = light, bottom = heavy) ----------
const Y_LIGHT_ENDS = -110  // LIGHT ENDS lane (above everything) - C4 isom, gas plants
const Y_LPG = 0
const Y_NAPHTHA = 140
const Y_FCC = 320
const Y_HCU = 430        // Hydrocracker lane (between FCC and Distillate)
const Y_DISTILLATE = 540
const Y_HEAVY_END = 700  // Vacuum unit + Coker
const Y_BOTTOMS = 860

// Product Y by boiling point (aligned with source lane)
const PRODUCT_Y: Record<string, number> = {
  sale_lpg: Y_LPG,
  sale_gasoline: Y_NAPHTHA + 20,
  sale_naphtha: Y_NAPHTHA + 80,
  sale_jet: Y_DISTILLATE - 20,
  sale_diesel: Y_DISTILLATE + 60,
  sale_fuel_oil: Y_BOTTOMS,
  sale_coke: Y_HEAVY_END + 40,
  sale_btx: Y_NAPHTHA - 60,  // BTX petchem product (near top)
}

// CDU output port IDs that edges should reference
const CDU_PORT_FOR_TARGET: Record<string, string> = {
  sale_lpg: 'lpg',
  sale_naphtha: 'ln',
  sale_jet: 'kero',
  sale_diesel: 'diesel',
  sale_fuel_oil: 'resid',
  blend_gasoline: 'ln',     // LN+HN to blend
  fcc_1: 'vgo',
  goht_1: 'vgo',
  hcu_1: 'vgo',
  isom_c56: 'ln',           // CDU LN to C5/C6 isomerization
  isom_c4: 'lpg',           // CDU nC4 (from LPG cut) to C4 isomerization
  arom_reformer: 'hn',      // CDU HN to aromatics reformer
  reformer_1: 'hn',
  splitter_1: 'hn',
  nht_1: 'hn',
  kht_1: 'kero',
  dht_1: 'diesel',
  kero_ht_1: 'kero',
  diesel_ht_1: 'diesel',
  vacuum_1: 'resid',
  coker_1: 'resid',
}

// Swim lane background defs
export interface SwimLaneDef {
  id: string; label: string; color: string; y: number; height: number
}

export const SWIM_LANE_DEFS: SwimLaneDef[] = [
  { id: 'lane_light_ends', label: 'Light Ends', color: '#fff9c4', y: Y_LIGHT_ENDS - 35, height: 90 },
  { id: 'lane_naphtha', label: 'Naphtha Processing', color: '#e3f2fd', y: Y_NAPHTHA - 35, height: 110 },
  { id: 'lane_fcc', label: 'FCC Complex', color: '#f3e5f5', y: Y_FCC - 35, height: 110 },
  { id: 'lane_hcu', label: 'Hydrocracking', color: '#ede7f6', y: Y_HCU - 35, height: 90 },
  { id: 'lane_distillate', label: 'Distillate', color: '#e8f5e9', y: Y_DISTILLATE - 35, height: 110 },
  { id: 'lane_heavy_end', label: 'Heavy End', color: '#fbe9e7', y: Y_HEAVY_END - 35, height: 110 },
]

// ---------- Node position by ID ----------
function nodePosition(id: string, nodeType: string, pIdx: number, pCount: number): { x: number; y: number } {
  // Purchases: stacked on far left, centred around FCC lane
  if (nodeType === 'purchase' && !id.includes('reformate')) {
    const totalH = pCount * 56
    return { x: X_CRUDE, y: Y_FCC - totalH / 2 + pIdx * 56 }
  }
  if (id === 'purchase_reformate') return { x: X_LANE_START, y: Y_NAPHTHA + 60 }

  // CDU
  if (id === 'cdu_1') return { x: X_CDU, y: Y_FCC - 60 } // tall node centred

  // Light Ends lane (C4 isom, gas plants)
  if (id === 'isom_c4') return { x: X_LANE_MID, y: Y_LIGHT_ENDS }
  if (id === 'ugp_1' || id.includes('ugp')) return { x: X_LANE_START, y: Y_LIGHT_ENDS }
  if (id === 'sgp_1' || id.includes('sgp')) return { x: X_LANE_END, y: Y_LIGHT_ENDS }

  // Naphtha lane
  if (id.includes('splitter')) return { x: X_LANE_START, y: Y_NAPHTHA }
  if (id === 'isom_c56') return { x: X_LANE_MID, y: Y_NAPHTHA + 55 }  // below NHT
  if (id.includes('nht')) return { x: X_LANE_MID, y: Y_NAPHTHA }
  if (id === 'reformer_1') return { x: X_LANE_END, y: Y_NAPHTHA }
  if (id === 'arom_reformer') return { x: X_LANE_END, y: Y_NAPHTHA - 60 }  // above mogas reformer

  // FCC lane
  if (id === 'goht_1' || id.includes('go_ht')) return { x: X_LANE_START, y: Y_FCC }
  if (id === 'fcc_1') return { x: X_LANE_MID, y: Y_FCC }
  if (id === 'scanfiner_1' || id.includes('scanfin')) return { x: X_LANE_END, y: Y_FCC }
  if (id === 'alky_1' || id.includes('alky')) return { x: X_LANE_END, y: Y_FCC - 60 }
  if (id === 'dimersol') return { x: X_LANE_END, y: Y_FCC + 55 }  // below alky in FCC lane

  // Hydrocracking lane
  if (id === 'hcu_1' || id.includes('hcu')) return { x: X_LANE_MID, y: Y_HCU }

  // Distillate lane
  if (id === 'kht_1' || id.includes('kero_ht')) return { x: X_LANE_START, y: Y_DISTILLATE - 20 }
  if (id === 'dht_1' || id.includes('diesel_ht')) return { x: X_LANE_MID, y: Y_DISTILLATE + 20 }

  // Heavy End lane
  if (id === 'vacuum_1' || id.includes('vacuum')) return { x: X_LANE_START, y: Y_HEAVY_END }
  if (id === 'coker_1' || id.includes('coker')) return { x: X_LANE_MID, y: Y_HEAVY_END }

  // Blender
  if (id.includes('blend')) return { x: X_BLEND, y: (Y_NAPHTHA + Y_FCC) / 2 }

  // Products
  if (nodeType === 'sale_point') return { x: X_PRODUCT, y: PRODUCT_Y[id] ?? Y_FCC }

  return { x: X_LANE_START, y: Y_BOTTOMS }
}

// ---------- Public API ----------
// Map swim-lane id -> node IDs that live in that lane. Used to hide lanes
// in Live Flow mode when all their units are idle.
const LANE_MEMBERSHIP: Record<string, string[]> = {
  lane_light_ends: ['isom_c4', 'ugp_1', 'sgp_1'],
  lane_heavy_end: ['vacuum_1', 'coker_1'],
  lane_hcu: ['hcu_1'],
  lane_naphtha: ['reformer_1', 'arom_reformer', 'isom_c56', 'splitter_1', 'nht_1'],
  lane_fcc: ['fcc_1', 'goht_1', 'scanfiner_1', 'alky_1', 'dimersol'],
  lane_distillate: ['kht_1', 'dht_1'],
}

export function applyPfdLayout(
  nodes: Node[],
  edges: Edge[],
  showFullDiagram = true,
): { nodes: Node[]; edges: Edge[] } {
  const purchases = nodes.filter(
    (n) => (n.data as Record<string, unknown>)?.nodeCategory === 'purchase'
      && !n.id.includes('reformate'),
  )
  let pIdx = 0

  const positioned = nodes.map((node) => {
    const d = node.data as Record<string, unknown>
    const cat = d?.nodeCategory as string
    const origType = (d?.originalNodeType as string) ?? cat
    const isPurchase = cat === 'purchase' && !node.id.includes('reformate')

    const pos = nodePosition(node.id, origType, isPurchase ? pIdx : 0, purchases.length)
    if (isPurchase) pIdx++

    // CDU gets its own node type
    const type = node.id === 'cdu_1' ? 'cdu' : node.type

    return { ...node, type, position: pos, zIndex: type === 'swimlane' ? -1 : 10 }
  })

  // Assign CDU source handles to edges originating from CDU
  const routedEdges = edges.map((edge) => {
    if (edge.source === 'cdu_1') {
      const port = CDU_PORT_FOR_TARGET[edge.target]
      // Also check display_name for keyword matching
      const sn = ((edge.data as Record<string, unknown>)?.streamName as string ?? '').toLowerCase()
      const guessedPort =
        port
        ?? (sn.includes('vgo') ? 'vgo'
          : sn.includes('naphtha') || sn.includes('ln') || sn.includes('hn') ? 'hn'
          : sn.includes('kero') ? 'kero'
          : sn.includes('diesel') ? 'diesel'
          : sn.includes('lpg') ? 'lpg'
          : sn.includes('vr') || sn.includes('resid') || sn.includes('bypass') ? 'resid'
          : undefined)
      return { ...edge, sourceHandle: guessedPort }
    }
    return edge
  })

  // Determine which lanes have at least one active unit (throughput > 1).
  // In Live Flow mode, hide lanes whose members are all idle.
  const activeUnitIds = new Set(
    nodes
      .filter((n) => {
        const d = n.data as Record<string, unknown>
        const throughput = (d?.throughput as number) ?? 0
        return (d?.nodeCategory as string) === 'unit' && throughput > 1
      })
      .map((n) => n.id),
  )
  const laneHasActiveUnit = (laneId: string): boolean => {
    const members = LANE_MEMBERSHIP[laneId] ?? []
    return members.some((uid) => activeUnitIds.has(uid))
  }

  // Swim lane backgrounds — hide empty lanes in Live Flow mode
  const visibleLanes = showFullDiagram
    ? SWIM_LANE_DEFS
    : SWIM_LANE_DEFS.filter((lane) => laneHasActiveUnit(lane.id))

  const laneNodes: Node[] = visibleLanes.map((lane) => ({
    id: lane.id,
    type: 'swimlane',
    position: { x: X_LANE_START - 30, y: lane.y },
    data: { label: lane.label, color: lane.color },
    style: { width: X_BLEND - X_LANE_START + 80, height: lane.height },
    draggable: false,
    selectable: false,
    zIndex: -1,
  }))

  return { nodes: [...laneNodes, ...positioned], edges: routedEdges }
}
