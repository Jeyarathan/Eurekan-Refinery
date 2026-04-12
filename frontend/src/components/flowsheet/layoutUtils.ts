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
const Y_LPG = 0
const Y_NAPHTHA = 140
const Y_FCC = 320
const Y_DISTILLATE = 500
const Y_BOTTOMS = 660

// Product Y by boiling point (aligned with source lane)
const PRODUCT_Y: Record<string, number> = {
  sale_lpg: Y_LPG,
  sale_gasoline: Y_NAPHTHA + 20,
  sale_naphtha: Y_NAPHTHA + 80,
  sale_jet: Y_DISTILLATE - 40,
  sale_diesel: Y_DISTILLATE + 40,
  sale_fuel_oil: Y_BOTTOMS,
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
  reformer_1: 'hn',
  splitter_1: 'hn',
  nht_1: 'hn',
  kero_ht_1: 'kero',
  diesel_ht_1: 'diesel',
}

// Swim lane background defs
export interface SwimLaneDef {
  id: string; label: string; color: string; y: number; height: number
}

export const SWIM_LANE_DEFS: SwimLaneDef[] = [
  { id: 'lane_naphtha', label: 'Naphtha Processing', color: '#e3f2fd', y: Y_NAPHTHA - 35, height: 110 },
  { id: 'lane_fcc', label: 'FCC Complex', color: '#f3e5f5', y: Y_FCC - 35, height: 110 },
  { id: 'lane_distillate', label: 'Distillate', color: '#e8f5e9', y: Y_DISTILLATE - 55, height: 130 },
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

  // Naphtha lane
  if (id.includes('splitter')) return { x: X_LANE_START, y: Y_NAPHTHA }
  if (id.includes('nht')) return { x: X_LANE_MID, y: Y_NAPHTHA }
  if (id === 'reformer_1') return { x: X_LANE_END, y: Y_NAPHTHA }

  // FCC lane
  if (id.includes('go_ht')) return { x: X_LANE_START, y: Y_FCC }
  if (id === 'fcc_1') return { x: X_LANE_MID, y: Y_FCC }
  if (id.includes('scanfin')) return { x: X_LANE_END, y: Y_FCC }
  if (id.includes('alky')) return { x: X_LANE_END, y: Y_FCC - 60 }

  // Distillate lane
  if (id.includes('kero_ht')) return { x: X_LANE_START, y: Y_DISTILLATE - 30 }
  if (id.includes('diesel_ht')) return { x: X_LANE_START, y: Y_DISTILLATE + 30 }

  // Blender
  if (id.includes('blend')) return { x: X_BLEND, y: (Y_NAPHTHA + Y_FCC) / 2 }

  // Products
  if (nodeType === 'sale_point') return { x: X_PRODUCT, y: PRODUCT_Y[id] ?? Y_FCC }

  return { x: X_LANE_START, y: Y_BOTTOMS }
}

// ---------- Public API ----------
export function applyPfdLayout(nodes: Node[], edges: Edge[]): { nodes: Node[]; edges: Edge[] } {
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

  // Swim lane backgrounds
  const laneNodes: Node[] = SWIM_LANE_DEFS.map((lane) => ({
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
