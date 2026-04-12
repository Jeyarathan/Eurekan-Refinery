/**
 * Zustand store for the active planning result and related UI state.
 *
 * - `activeResult` is the currently displayed scenario.
 * - `isStale` flips to true when the user edits any input after the last solve;
 *    it resets to false on every successful `finishOptimizing` call.
 * - `isOptimizing` is true while a solve request is in flight.
 */

import { create } from 'zustand'

import type { PlanningResult } from '../types'

interface RefineryState {
  activeScenarioId: string | null
  activeResult: PlanningResult | null
  isStale: boolean
  isOptimizing: boolean
  lastOptimizedAt: Date | null
  lastInputChangedAt: Date | null
  showFullDiagram: boolean
  highlightedNodeId: string | null

  setActiveResult: (result: PlanningResult) => void
  markStale: () => void
  startOptimizing: () => void
  finishOptimizing: (result: PlanningResult) => void
  toggleFullDiagram: () => void
  setHighlightedNode: (id: string | null) => void
  reset: () => void
}

export const useRefineryStore = create<RefineryState>((set) => ({
  activeScenarioId: null,
  activeResult: null,
  isStale: false,
  isOptimizing: false,
  lastOptimizedAt: null,
  lastInputChangedAt: null,
  showFullDiagram: false,
  highlightedNodeId: null,

  setActiveResult: (result) =>
    set({
      activeResult: result,
      activeScenarioId: result.scenario_id,
      isStale: false,
      lastOptimizedAt: new Date(),
    }),

  markStale: () =>
    set({
      isStale: true,
      lastInputChangedAt: new Date(),
    }),

  startOptimizing: () => set({ isOptimizing: true }),

  finishOptimizing: (result) =>
    set({
      isOptimizing: false,
      activeResult: result,
      activeScenarioId: result.scenario_id,
      isStale: false,
      lastOptimizedAt: new Date(),
    }),

  toggleFullDiagram: () =>
    set((s) => ({ showFullDiagram: !s.showFullDiagram })),

  setHighlightedNode: (id) => set({ highlightedNodeId: id }),

  reset: () =>
    set({
      activeScenarioId: null,
      activeResult: null,
      isStale: false,
      isOptimizing: false,
      lastOptimizedAt: null,
      lastInputChangedAt: null,
    }),
}))
