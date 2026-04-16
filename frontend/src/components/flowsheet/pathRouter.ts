/**
 * Orthogonal path routing for SVG flowsheet edges.
 * Creates L-shaped paths that route through the CDU trunk line.
 */

import type { LayoutNode } from './layoutEngine'
import { COLS } from './layoutEngine'

const TRUNK_X = COLS.TRUNK

/**
 * Route an orthogonal path between two nodes.
 * Returns array of [x,y] points for an SVG polyline.
 */
export function routePath(
  source: LayoutNode,
  target: LayoutNode,
): [number, number][] {
  // Source exit point: right edge center
  const sx = source.x + source.w
  const sy = source.y + source.h / 2

  // Target entry point: left edge center
  const tx = target.x
  const ty = target.y + target.h / 2

  // Crude -> CDU: simple diagonal-ish line (crude nodes are circles)
  if (source.nodeType === 'crude') {
    return [[source.x + source.w / 2, source.y + source.h / 2], [tx, ty]]
  }

  // CDU -> any unit: route through trunk line
  if (source.id === 'cdu_1') {
    // CDU right edge -> trunk line -> target left edge
    return [[sx, sy], [TRUNK_X, sy], [TRUNK_X, ty], [tx, ty]]
  }

  // Same lane (within ~60px y): horizontal
  if (Math.abs(sy - ty) < 60 && sx < tx) {
    return [[sx, sy], [tx, ty]]
  }

  // Cross-lane: horizontal -> vertical -> horizontal
  // Use a corridor x midway between source and target
  const corridorX = Math.max(sx + 15, Math.min(tx - 15, (sx + tx) / 2))
  return [[sx, sy], [corridorX, sy], [corridorX, ty], [tx, ty]]
}

/**
 * Convert point array to SVG path d-attribute string.
 */
export function pathToSvg(points: [number, number][]): string {
  if (points.length === 0) return ''
  let d = `M${points[0][0]},${points[0][1]}`
  for (let i = 1; i < points.length; i++) {
    d += ` L${points[i][0]},${points[i][1]}`
  }
  return d
}

/**
 * Get midpoint of a path for label placement.
 */
export function pathMidpoint(points: [number, number][]): [number, number] {
  if (points.length === 0) return [0, 0]
  const mid = Math.floor(points.length / 2)
  return points[mid]
}
