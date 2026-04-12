/**
 * Dagre-based auto-layout with swim lane assignment.
 *
 * Nodes are assigned to swim lanes by their ID/type, then dagre
 * positions them left-to-right within each lane.  Swim lane
 * background rectangles are computed to enclose their children.
 */

import dagre from 'dagre'
import type { Edge, Node } from '@xyflow/react'

// Swim lane definitions: order determines vertical stacking
export const SWIM_LANES = [
  { id: 'lane_naphtha', label: 'Naphtha Processing', color: '#e3f2fd' },
  { id: 'lane_fcc', label: 'FCC Complex', color: '#f3e5f5' },
  { id: 'lane_distillate', label: 'Distillate Processing', color: '#e8f5e9' },
  { id: 'lane_lightends', label: 'Light Ends', color: '#fff8e1' },
] as const

// Map node IDs to swim lanes
function assignLane(nodeId: string, nodeType: string): string | null {
  // Purchases and products are not in any lane
  if (nodeType === 'purchase' || nodeType === 'sale_point') return null
  // CDU and blender span lanes — no lane assignment
  if (nodeId === 'cdu_1' || nodeId.includes('blend')) return null

  // Naphtha lane
  if (nodeId.includes('reformer') || nodeId.includes('nht') || nodeId.includes('splitter'))
    return 'lane_naphtha'
  if (nodeId === 'purchase_reformate') return null // left side, no lane

  // FCC lane
  if (nodeId.includes('fcc') || nodeId.includes('alky') || nodeId.includes('scanfin'))
    return 'lane_fcc'

  // Distillate lane
  if (nodeId.includes('diesel_ht') || nodeId.includes('kero_ht'))
    return 'lane_distillate'

  // Light ends
  if (nodeId.includes('lpg') || nodeId.includes('fuel_gas'))
    return 'lane_lightends'

  return null
}

// Node sizes
const W_PURCHASE = 50
const W_UNIT = 130
const W_PRODUCT = 110
const H_NODE = 56
const H_SMALL = 44

export function applyDagreLayout(
  nodes: Node[],
  edges: Edge[],
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph()
  g.setGraph({
    rankdir: 'LR',
    ranksep: 100,
    nodesep: 40,
    edgesep: 20,
    marginx: 30,
    marginy: 30,
  })
  g.setDefaultEdgeLabel(() => ({}))

  for (const node of nodes) {
    const cat = node.data?.nodeCategory as string | undefined
    const w = cat === 'purchase' ? W_PURCHASE : cat === 'product' ? W_PRODUCT : W_UNIT
    const h = cat === 'purchase' ? W_PURCHASE : cat === 'product' ? H_SMALL : H_NODE
    g.setNode(node.id, { width: w, height: h })
  }

  for (const edge of edges) {
    g.setEdge(edge.source, edge.target)
  }

  dagre.layout(g)

  const positioned = nodes.map((node) => {
    const pos = g.node(node.id)
    return {
      ...node,
      position: {
        x: pos.x - (pos.width ?? W_UNIT) / 2,
        y: pos.y - (pos.height ?? H_NODE) / 2,
      },
    }
  })

  // Compute swim lane background rectangles
  const laneNodes: Node[] = []
  const PAD = 20

  for (const lane of SWIM_LANES) {
    const children = positioned.filter((n) => {
      const nt = (n.data as Record<string, unknown>)?.originalNodeType as string ?? ''
      return assignLane(n.id, nt) === lane.id
    })

    if (children.length === 0) continue

    const xs = children.map((c) => c.position.x)
    const ys = children.map((c) => c.position.y)
    const minX = Math.min(...xs) - PAD
    const minY = Math.min(...ys) - PAD - 16 // extra for label
    const maxX = Math.max(...xs) + W_UNIT + PAD
    const maxY = Math.max(...ys) + H_NODE + PAD

    laneNodes.push({
      id: lane.id,
      type: 'swimlane',
      position: { x: minX, y: minY },
      data: { label: lane.label, color: lane.color },
      style: { width: maxX - minX, height: maxY - minY },
      draggable: false,
      selectable: false,
      // Render behind other nodes
      zIndex: -1,
    })
  }

  return { nodes: [...laneNodes, ...positioned], edges }
}
