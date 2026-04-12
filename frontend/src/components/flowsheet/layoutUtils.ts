/**
 * Refinery PFD layout engine — boiling-point hierarchy.
 *
 * Top = light (LPG), bottom = heavy (fuel oil).
 * Left-to-right flow within each horizontal swim lane.
 * CDU is a hub on the left, products aligned on the right.
 */

import type { Edge, Node } from '@xyflow/react'

// --- Column X positions (left → right) ---
const X_CRUDE = 0
const X_CDU = 160
const X_PROCESS = 360    // process units within swim lanes
const X_PROCESS2 = 520   // second unit in a lane (reformer after NHT)
const X_BLEND = 680
const X_PRODUCT = 840

// --- Swim lane Y positions (top = light, bottom = heavy) ---
const LANE_GAP = 120
const Y_LIGHTENDS = 0
const Y_NAPHTHA = LANE_GAP
const Y_FCC = LANE_GAP * 2
const Y_DISTILLATE = LANE_GAP * 3
const Y_BOTTOMS = LANE_GAP * 4

// Product Y ordering by boiling point (must match swim lanes)
const PRODUCT_Y: Record<string, number> = {
  sale_lpg: Y_LIGHTENDS,
  sale_gasoline: Y_NAPHTHA,
  sale_naphtha: Y_NAPHTHA + 50,
  sale_jet: Y_DISTILLATE - 30,
  sale_diesel: Y_DISTILLATE + 30,
  sale_fuel_oil: Y_BOTTOMS,
}

// Swim lane definitions for background rectangles
export interface SwimLaneDef {
  id: string
  label: string
  color: string
  y: number
  height: number
}

export const SWIM_LANE_DEFS: SwimLaneDef[] = [
  { id: 'lane_naphtha', label: 'Naphtha Processing', color: '#e3f2fd', y: Y_NAPHTHA - 30, height: 90 },
  { id: 'lane_fcc', label: 'FCC Complex', color: '#f3e5f5', y: Y_FCC - 30, height: 90 },
  { id: 'lane_distillate', label: 'Distillate', color: '#e8f5e9', y: Y_DISTILLATE - 30, height: 90 },
]

// --- Node positioning by ID ---
function positionNode(nodeId: string, nodeType: string, purchaseIndex: number, purchaseCount: number): { x: number; y: number } {
  // Crude purchases: stacked vertically on far left, centred around CDU
  if (nodeType === 'purchase' && !nodeId.includes('reformate')) {
    const totalH = purchaseCount * 60
    const startY = (Y_FCC - totalH / 2) + purchaseIndex * 60
    return { x: X_CRUDE, y: startY }
  }

  // Purchased reformate: near naphtha lane
  if (nodeId === 'purchase_reformate') return { x: X_PROCESS, y: Y_NAPHTHA + 50 }

  // CDU hub: centered vertically spanning all lanes
  if (nodeId === 'cdu_1') return { x: X_CDU, y: Y_FCC }

  // Naphtha lane units
  if (nodeId.includes('splitter')) return { x: X_PROCESS, y: Y_NAPHTHA }
  if (nodeId.includes('nht')) return { x: X_PROCESS + 80, y: Y_NAPHTHA }
  if (nodeId === 'reformer_1') return { x: X_PROCESS2, y: Y_NAPHTHA }

  // FCC lane units
  if (nodeId.includes('go_ht')) return { x: X_PROCESS, y: Y_FCC }
  if (nodeId === 'fcc_1') return { x: X_PROCESS + 80, y: Y_FCC }
  if (nodeId.includes('scanfin')) return { x: X_PROCESS2, y: Y_FCC }
  if (nodeId.includes('alky')) return { x: X_PROCESS2 + 80, y: Y_FCC - 40 }

  // Distillate lane units
  if (nodeId.includes('kero_ht')) return { x: X_PROCESS, y: Y_DISTILLATE - 20 }
  if (nodeId.includes('diesel_ht')) return { x: X_PROCESS, y: Y_DISTILLATE + 30 }

  // Gasoline blender: right of process, between naphtha and FCC lanes
  if (nodeId.includes('blend')) return { x: X_BLEND, y: (Y_NAPHTHA + Y_FCC) / 2 }

  // Product/sale nodes: ordered by boiling point on far right
  if (nodeType === 'sale_point') {
    const y = PRODUCT_Y[nodeId] ?? Y_FCC
    return { x: X_PRODUCT, y }
  }

  // Fallback
  return { x: X_PROCESS, y: Y_BOTTOMS }
}

export function applyPfdLayout(
  nodes: Node[],
  edges: Edge[],
): { nodes: Node[]; edges: Edge[] } {
  // Count purchases for vertical centering
  const purchases = nodes.filter(
    (n) => (n.data as Record<string, unknown>)?.nodeCategory === 'purchase'
      && !n.id.includes('reformate'),
  )
  let purchaseIdx = 0

  const positioned = nodes.map((node) => {
    const cat = (node.data as Record<string, unknown>)?.nodeCategory as string
    const origType = (node.data as Record<string, unknown>)?.originalNodeType as string ?? cat
    const isPurchase = cat === 'purchase' && !node.id.includes('reformate')

    const pos = positionNode(
      node.id, origType,
      isPurchase ? purchaseIdx : 0,
      purchases.length,
    )
    if (isPurchase) purchaseIdx++

    return { ...node, position: pos }
  })

  // Generate swim lane background nodes
  const laneNodes: Node[] = SWIM_LANE_DEFS.map((lane) => ({
    id: lane.id,
    type: 'swimlane',
    position: { x: X_PROCESS - 20, y: lane.y },
    data: { label: lane.label, color: lane.color },
    style: { width: X_BLEND - X_PROCESS + 60, height: lane.height },
    draggable: false,
    selectable: false,
    zIndex: -1,
  }))

  return { nodes: [...laneNodes, ...positioned], edges }
}
