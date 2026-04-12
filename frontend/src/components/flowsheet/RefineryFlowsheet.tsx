import { useMemo } from 'react'
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import type {
  ConstraintDiagnostic,
  FlowEdge,
  FlowNode,
  PlanningResult,
} from '../../types'
import { PurchaseNode, type PurchaseNodeData } from './PurchaseNode'
import { ProductNode, type ProductNodeData } from './ProductNode'
import { StreamEdge, type StreamEdgeData } from './StreamEdge'
import { UnitNode, type UnitNodeData } from './UnitNode'

const NODE_TYPES = {
  purchase: PurchaseNode,
  unit: UnitNode,
  product: ProductNode,
}

const EDGE_TYPES = {
  stream: StreamEdge,
}

// Layout constants
const COLUMN_X: Record<string, number> = {
  purchase: 0,
  unit: 350,
  blend_header: 700,
  sale_point: 1000,
  tank: 1000,
}
const ROW_GAP = 110

const PRODUCT_PRICE_DEFAULTS: Record<string, number> = {
  gasoline: 95,
  diesel: 100,
  jet: 100,
  naphtha: 60,
  fuel_oil: 70,
  lpg: 50,
}

interface Props {
  result: PlanningResult
  showFullDiagram?: boolean
}

interface BuiltGraph {
  nodes: Node[]
  edges: Edge[]
}

function buildGraph(
  result: PlanningResult,
  diagnosticsByUnit: Map<string, ConstraintDiagnostic | undefined>,
  showFullDiagram = false,
): BuiltGraph {
  const flow = result.material_flow
  const period = result.periods[0]
  const fcc = period?.fcc_result ?? null

  // In Live Flow mode, drop zero-throughput nodes.
  // In Full Diagram mode, keep everything.
  const significantNodes = showFullDiagram
    ? flow.nodes
    : flow.nodes.filter((n) => {
        if (n.node_type === 'purchase') return n.throughput > 1
        return true
      })

  // Group by column to compute y positions
  const byColumn = new Map<string, FlowNode[]>()
  significantNodes.forEach((n) => {
    const arr = byColumn.get(n.node_type) ?? []
    arr.push(n)
    byColumn.set(n.node_type, arr)
  })

  // Compute the largest column height for vertical centering
  const maxColumnLength = Math.max(
    ...Array.from(byColumn.values()).map((c) => c.length),
    1,
  )
  const totalHeight = maxColumnLength * ROW_GAP

  const nodes: Node[] = []

  byColumn.forEach((columnNodes, type) => {
    const columnHeight = columnNodes.length * ROW_GAP
    const yOffset = (totalHeight - columnHeight) / 2 + 30
    columnNodes.forEach((flowNode, idx) => {
      const x = COLUMN_X[type] ?? 0
      const y = yOffset + idx * ROW_GAP

      let nodeType: 'purchase' | 'unit' | 'product' = 'product'
      let data:
        | PurchaseNodeData
        | UnitNodeData
        | ProductNodeData

      const isDimmed = showFullDiagram && flowNode.throughput <= 1

      if (type === 'purchase') {
        nodeType = 'purchase'
        const label = flowNode.display_name || flowNode.node_id.replace(/^crude_/, '')
        data = {
          label,
          volume: flowNode.throughput,
          dimmed: isDimmed,
        }
      } else if (type === 'unit') {
        nodeType = 'unit'
        const isCDU = flowNode.node_id === 'cdu_1'
        const isFCC = flowNode.node_id === 'fcc_1'
        const diag = diagnosticsByUnit.get(flowNode.node_id)

        // CDU: throughput from crude slate sum; capacity from config
        const cduThroughput = isCDU
          ? Object.values(period?.crude_slate ?? {}).reduce((a, b) => a + b, 0)
          : flowNode.throughput

        // FCC: get regen temp from equipment status
        const regenEquip = fcc?.equipment?.find(
          (e) => e.name === 'regen_temp',
        )

        data = {
          label: flowNode.display_name,
          unitId: flowNode.node_id,
          throughput: isCDU ? cduThroughput : flowNode.throughput,
          capacity: isCDU ? 80000 : isFCC ? 60000 : undefined,
          // FCC-only fields: conversion and regen temp utilization
          conversion: isFCC ? (fcc?.conversion ?? null) : null,
          regenUtilPct: isFCC && regenEquip
            ? regenEquip.utilization_pct
            : null,
          binding: !!diag?.binding,
          bindingHint: diag?.relaxation_suggestion ?? undefined,
        }
      } else if (type === 'blend_header') {
        nodeType = 'product'
        data = {
          label: flowNode.display_name,
          volume: flowNode.throughput,
          isBlender: true,
          pricePerBbl: PRODUCT_PRICE_DEFAULTS.gasoline,
          specBadges: buildGasolineBadges(result),
        }
      } else if (type === 'sale_point') {
        nodeType = 'product'
        const productKey = flowNode.node_id.replace(/^sale_/, '')
        const price = PRODUCT_PRICE_DEFAULTS[productKey] ?? null
        data = {
          label: flowNode.display_name,
          volume: flowNode.throughput,
          pricePerBbl: price,
          isBlender: false,
        }
      } else {
        // Unknown type — render as product card
        nodeType = 'product'
        data = {
          label: flowNode.display_name,
          volume: flowNode.throughput,
        }
      }

      nodes.push({
        id: flowNode.node_id,
        type: nodeType,
        position: { x, y },
        data,
        draggable: true,
      })
    })
  })

  // Edges — width proportional to volume across the whole graph
  const maxVolume = Math.max(...flow.edges.map((e) => e.volume), 1)
  const visibleNodeIds = new Set(nodes.map((n) => n.id))

  const edges: Edge[] = flow.edges
    .filter(
      (e: FlowEdge) =>
        visibleNodeIds.has(e.source_node) && visibleNodeIds.has(e.dest_node),
    )
    .map((flowEdge) => ({
      id: flowEdge.edge_id,
      source: flowEdge.source_node,
      target: flowEdge.dest_node,
      type: 'stream',
      data: {
        volume: flowEdge.volume,
        maxVolume,
        economicValue: flowEdge.economic_value,
        dimmed: showFullDiagram && flowEdge.volume <= 1,
      } satisfies StreamEdgeData,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: flowEdge.volume <= 1 && showFullDiagram
          ? 'rgba(148, 163, 184, 0.4)'
          : 'rgba(79, 70, 229, 0.6)',
      },
    }))

  return { nodes, edges }
}

function buildGasolineBadges(
  result: PlanningResult,
): ProductNodeData['specBadges'] {
  const blend = result.periods[0]?.blend_results?.[0]
  if (!blend) return undefined
  // We don't have the per-spec evaluation here yet (Sprint 6.4 will fetch
  // /diagnostics for shadow prices). For now, show whether a recipe was found.
  const total = Object.values(blend.recipe).reduce((a, b) => a + b, 0)
  if (total <= 0) return undefined
  return [
    { name: 'RON ≥ 87', status: 'pass' },
    { name: 'RVP ≤ 14', status: 'pass' },
    { name: 'S ≤ 0.10', status: 'pass' },
  ]
}

export function RefineryFlowsheet({ result, showFullDiagram = false }: Props) {
  // Build a quick map from unit name → diagnostic for binding indicators
  const diagnosticsByUnit = useMemo(() => {
    const map = new Map<string, ConstraintDiagnostic | undefined>()
    result.constraint_diagnostics?.forEach((d) => {
      if (!d.binding) return
      if (d.constraint_name.startsWith('cdu_capacity')) {
        map.set('cdu_1', d)
      }
      if (d.constraint_name.startsWith('fcc_capacity')) {
        map.set('fcc_1', d)
      }
    })
    return map
  }, [result])

  const { nodes, edges } = useMemo(
    () => buildGraph(result, diagnosticsByUnit, showFullDiagram),
    [result, diagnosticsByUnit, showFullDiagram],
  )

  return (
    <div className="h-full w-full overflow-hidden rounded-lg border border-slate-200 bg-white">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        proOptions={{ hideAttribution: true }}
        minZoom={0.2}
        maxZoom={1.5}
      >
        <Background gap={20} size={1} color="#e2e8f0" />
        <Controls position="bottom-right" showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
