/**
 * RefineryFlowsheet — main flowsheet component.
 * Pure SVG rendering with orthogonal routing.
 * Replaced React Flow (Sprint 15+).
 */

import type { PlanningResult } from '../../types'
import { SvgFlowsheet } from './SvgFlowsheet'

interface Props {
  result: PlanningResult
  showFullDiagram?: boolean
  showH2Network?: boolean
  highlightedNodeId?: string | null
  onNodeClick?: (nodeId: string | null) => void
}

export function RefineryFlowsheet(props: Props) {
  return <SvgFlowsheet {...props} />
}
