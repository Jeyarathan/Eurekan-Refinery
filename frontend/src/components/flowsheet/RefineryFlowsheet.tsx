import { useCallback, useMemo } from 'react'
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import type { FlowEdge, PlanningResult } from '../../types'
import { applyPfdLayout } from './layoutUtils'
import { CduNode } from './CduNode'
import { PurchaseNode, type PurchaseNodeData } from './PurchaseNode'
import { ProductNode, type ProductNodeData } from './ProductNode'
import { StreamEdge, type StreamEdgeData } from './StreamEdge'
import { SwimLane } from './SwimLane'
import { UnitNode, type UnitNodeData } from './UnitNode'

const NODE_TYPES = { purchase: PurchaseNode, cdu: CduNode, unit: UnitNode, product: ProductNode, swimlane: SwimLane }
const EDGE_TYPES = { stream: StreamEdge }

const AREA_COLORS: Record<string, string> = {
  unit: '#90caf9',        // blue for naphtha/process units
  fcc: '#ce93d8',         // purple for FCC complex
  reformer: '#90caf9',    // blue for naphtha processing
  blend_header: '#b39ddb',
}

const PRODUCT_PRICES: Record<string, number> = {
  gasoline: 95, diesel: 100, jet: 100, naphtha: 60, fuel_oil: 55, lpg: 50,
}

interface Props {
  result: PlanningResult
  showFullDiagram?: boolean
  highlightedNodeId?: string | null
  onNodeClick?: (nodeId: string | null) => void
}

export function RefineryFlowsheet({
  result, showFullDiagram = false, highlightedNodeId = null, onNodeClick,
}: Props) {
  const { nodes, edges } = useMemo(() => {
    const flow = result.material_flow
    const period = result.periods[0]
    const fcc = period?.fcc_result ?? null

    // Filter nodes
    const significant = showFullDiagram
      ? flow.nodes
      : flow.nodes.filter((n) => n.node_type === 'purchase' ? n.throughput > 1 : true)

    // Build React Flow nodes
    const rfNodes: Node[] = significant.map((fn) => {
      const nodeType = fn.node_type === 'purchase' ? 'purchase'
        : fn.node_type === 'unit' ? 'unit' : 'product'

      let data: PurchaseNodeData | UnitNodeData | ProductNodeData

      if (fn.node_type === 'purchase') {
        data = {
          label: fn.display_name || fn.node_id.replace(/^(crude_|purchase_)/, ''),
          volume: fn.throughput,
          dimmed: showFullDiagram && fn.throughput <= 1,
          nodeCategory: 'purchase',
        }
      } else if (fn.node_type === 'unit') {
        const isCDU = fn.node_id === 'cdu_1'
        const isFCC = fn.node_id === 'fcc_1'
        const isReformer = fn.node_id === 'reformer_1'
        const cduThroughput = isCDU
          ? Object.values(period?.crude_slate ?? {}).reduce((a, b) => a + b, 0)
          : fn.throughput
        const regenEquip = fcc?.equipment?.find((e) => e.name === 'regen_temp')
        data = {
          label: fn.display_name,
          unitId: fn.node_id,
          throughput: isCDU ? cduThroughput : fn.throughput,
          capacity: isCDU ? 80000 : isFCC ? 60000 : isReformer ? 35000 : undefined,
          conversion: isFCC ? (fcc?.conversion ?? null) : null,
          regenUtilPct: isFCC && regenEquip ? regenEquip.utilization_pct : null,
          binding: false,
          nodeCategory: 'unit',
          areaColor: isFCC ? AREA_COLORS.fcc : isReformer ? AREA_COLORS.reformer : AREA_COLORS.unit,
        }
      } else if (fn.node_type === 'blend_header') {
        data = {
          label: fn.display_name,
          volume: fn.throughput,
          isBlender: true,
          pricePerBbl: PRODUCT_PRICES.gasoline,
          nodeCategory: 'blend',
          specBadges: [
            { name: 'RON', status: 'pass' as const },
            { name: 'RVP', status: 'pass' as const },
            { name: 'S', status: 'pass' as const },
          ],
        }
      } else {
        const prodKey = fn.node_id.replace(/^sale_/, '')
        data = {
          label: fn.display_name,
          volume: fn.throughput,
          pricePerBbl: PRODUCT_PRICES[prodKey] ?? null,
          isBlender: false,
          nodeCategory: 'product',
        }
      }

      return {
        id: fn.node_id,
        type: nodeType,
        position: { x: 0, y: 0 }, // dagre will position
        data: { ...data, originalNodeType: fn.node_type },
        draggable: true,
      }
    })

    // Build edges with stream tracing
    const maxVol = Math.max(...flow.edges.map((e) => e.volume), 1)
    const visibleIds = new Set(rfNodes.map((n) => n.id))

    // Stream tracing: forward walk from highlighted node
    const connected = new Set<string>()
    if (highlightedNodeId) {
      const touched = new Set([highlightedNodeId])
      let changed = true
      while (changed) {
        changed = false
        for (const e of flow.edges) {
          if (touched.has(e.source_node) && !touched.has(e.dest_node)) {
            touched.add(e.dest_node)
            connected.add(e.edge_id)
            changed = true
          }
        }
      }
      for (const e of flow.edges) {
        if (e.source_node === highlightedNodeId || e.dest_node === highlightedNodeId)
          connected.add(e.edge_id)
      }
    }

    const rfEdges: Edge[] = flow.edges
      .filter((e: FlowEdge) => visibleIds.has(e.source_node) && visibleIds.has(e.dest_node))
      .map((fe) => {
        const traceDim = highlightedNodeId != null && !connected.has(fe.edge_id)
        const isDimmed = traceDim || (showFullDiagram && fe.volume <= 1)
        return {
          id: fe.edge_id,
          source: fe.source_node,
          target: fe.dest_node,
          type: 'stream',
          data: {
            volume: fe.volume,
            maxVolume: maxVol,
            dimmed: isDimmed,
            streamName: fe.display_name,
          } satisfies StreamEdgeData,
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isDimmed ? 'rgba(148,163,184,0.3)' : 'rgba(99,102,241,0.6)',
            width: 10,
            height: 10,
          },
        }
      })

    // Apply PFD boiling-point layout
    return applyPfdLayout(rfNodes, rfEdges)
  }, [result, showFullDiagram, highlightedNodeId])

  const handleNodeClick = useCallback((_: unknown, node: Node) => {
    onNodeClick?.(node.id)
  }, [onNodeClick])

  const handlePaneClick = useCallback(() => {
    onNodeClick?.(null)
  }, [onNodeClick])

  return (
    <div className="h-full w-full overflow-hidden rounded-lg border border-slate-200 bg-white">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        onNodeClick={handleNodeClick}
        onPaneClick={handlePaneClick}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        minZoom={0.15}
        maxZoom={2}
      >
        <Background gap={24} size={1} color="#f1f5f9" />
        <Controls position="bottom-right" showZoom showFitView showInteractive={false} />
        <MiniMap
          position="bottom-left"
          style={{ width: 180, height: 120 }}
          pannable
          zoomable
          nodeColor={(n) =>
            n.type === 'purchase' ? '#fbbf24'
            : n.type === 'cdu' ? '#6366f1'
            : n.type === 'unit' ? '#818cf8'
            : n.type === 'product' ? '#10b981'
            : '#94a3b8'
          }
          maskColor="rgba(241,245,249,0.6)"
        />
      </ReactFlow>
    </div>
  )
}
