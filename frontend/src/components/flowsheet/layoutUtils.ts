/**
 * Dagre-based auto-layout for the refinery flowsheet.
 *
 * Nodes are positioned left-to-right by process area, with dagre
 * computing optimal positions to minimise edge crossings.
 */

import dagre from 'dagre'
import type { Edge, Node } from '@xyflow/react'

// Node sizes for dagre
const NODE_WIDTH = 130
const NODE_HEIGHT = 56
const PURCHASE_SIZE = 50
const PRODUCT_SIZE = 100

export function applyDagreLayout(
  nodes: Node[],
  edges: Edge[],
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph()
  g.setGraph({
    rankdir: 'LR',
    ranksep: 120,
    nodesep: 50,
    edgesep: 30,
    marginx: 40,
    marginy: 40,
  })
  g.setDefaultEdgeLabel(() => ({}))

  for (const node of nodes) {
    const isPurchase = node.data?.nodeCategory === 'purchase'
    const isProduct = node.data?.nodeCategory === 'product'
    const w = isPurchase ? PURCHASE_SIZE : isProduct ? PRODUCT_SIZE : NODE_WIDTH
    const h = isPurchase ? PURCHASE_SIZE : isProduct ? 44 : NODE_HEIGHT
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
        x: pos.x - (pos.width ?? NODE_WIDTH) / 2,
        y: pos.y - (pos.height ?? NODE_HEIGHT) / 2,
      },
    }
  })

  return { nodes: positioned, edges }
}
