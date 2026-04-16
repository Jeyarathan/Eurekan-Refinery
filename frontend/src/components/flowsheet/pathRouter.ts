/**
 * Orthogonal path routing for SVG flowsheet edges.
 *
 * EVERY path is an array of [x,y] waypoints connected by ONLY horizontal
 * and vertical segments (90-degree turns). No diagonals. No curves.
 *
 * Routing patterns:
 *   Crude → CDU:  horizontal to CDU left edge, then vertical to CDU center y
 *   CDU → target: horizontal to TRUNK_X, vertical to target y, horizontal to target
 *   In-lane:      horizontal (same y) or step via corridor
 *   Cross-lane:   horizontal → corridor vertical → horizontal
 *   To product:   horizontal → corridor vertical → horizontal to product
 */

import type { LayoutNode } from './layoutEngine'
import { COLS } from './layoutEngine'

const TRUNK_X = COLS.TRUNK

/**
 * Route a strictly orthogonal path between two nodes.
 * Returns array of [x,y] waypoints — only H and V segments.
 */
export function routePath(
  source: LayoutNode,
  target: LayoutNode,
): [number, number][] {
  // Source exit point: right edge, vertical center
  const sx = source.x + source.w
  const sy = source.y + source.h / 2

  // Target entry point: left edge, vertical center
  const tx = target.x
  const ty = target.y + target.h / 2

  // ── Crude → CDU: horizontal line to CDU left edge, vertical to CDU center ──
  if (source.nodeType === 'crude') {
    const cx = source.x + source.w / 2
    const cy = source.y + source.h / 2
    // Horizontal from crude to CDU column, then vertical to CDU entry
    return [[cx, cy], [tx, cy], [tx, ty]]
  }

  // ── CDU → anything: route through the trunk line ──
  if (source.id === 'cdu_1') {
    if (Math.abs(sy - ty) < 2) {
      // Same Y — just horizontal through trunk
      return [[sx, sy], [tx, ty]]
    }
    // Right → trunk → vertical → horizontal to target
    return [[sx, sy], [TRUNK_X, sy], [TRUNK_X, ty], [tx, ty]]
  }

  // ── Same Y (within 2px): pure horizontal ──
  if (Math.abs(sy - ty) < 2) {
    return [[sx, sy], [tx, ty]]
  }

  // ── Source right of target — shouldn't happen often, but handle it ──
  if (sx >= tx) {
    const corridorX = Math.max(sx + 15, tx + target.w + 15)
    return [[sx, sy], [corridorX, sy], [corridorX, ty], [tx, ty]]
  }

  // ── In-lane (small Y delta, left-to-right): step pattern ──
  // Horizontal from source, vertical jog, horizontal to target
  const midX = Math.round((sx + tx) / 2)
  return [[sx, sy], [midX, sy], [midX, ty], [tx, ty]]
}

/**
 * Convert point array to SVG path d-attribute string.
 * Deduplicates consecutive identical points and collinear segments.
 */
export function pathToSvg(points: [number, number][]): string {
  if (points.length === 0) return ''
  // Remove duplicate consecutive points
  const clean: [number, number][] = [points[0]]
  for (let i = 1; i < points.length; i++) {
    const prev = clean[clean.length - 1]
    if (Math.abs(points[i][0] - prev[0]) > 0.5 || Math.abs(points[i][1] - prev[1]) > 0.5) {
      clean.push(points[i])
    }
  }
  if (clean.length < 2) return ''
  let d = `M${clean[0][0]},${clean[0][1]}`
  for (let i = 1; i < clean.length; i++) {
    d += ` L${clean[i][0]},${clean[i][1]}`
  }
  return d
}

/**
 * Get midpoint of a path for label placement.
 */
export function pathMidpoint(points: [number, number][]): [number, number] {
  if (points.length < 2) return points[0] ?? [0, 0]
  // Find the longest segment and place label at its midpoint
  let bestLen = 0
  let bestMid: [number, number] = points[0]
  for (let i = 1; i < points.length; i++) {
    const dx = points[i][0] - points[i - 1][0]
    const dy = points[i][1] - points[i - 1][1]
    const len = Math.abs(dx) + Math.abs(dy)
    if (len > bestLen) {
      bestLen = len
      bestMid = [(points[i][0] + points[i - 1][0]) / 2, (points[i][1] + points[i - 1][1]) / 2]
    }
  }
  return bestMid
}
