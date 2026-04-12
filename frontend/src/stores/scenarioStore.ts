import { create } from 'zustand'

import {
  branchScenario,
  compareScenarios,
  getScenario,
  getScenarios,
} from '../api/client'
import type {
  PlanningResult,
  ScenarioComparison,
  ScenarioSummary,
} from '../types'
import { useRefineryStore } from './refineryStore'

interface ScenarioState {
  scenarios: ScenarioSummary[]
  activeId: string | null
  comparison: ScenarioComparison | null
  isLoading: boolean

  loadScenarios: () => Promise<void>
  setActive: (id: string) => Promise<void>
  branch: (
    parentId: string,
    name: string,
    changes: { crude_prices?: Record<string, number>; product_prices?: Record<string, number> },
  ) => Promise<PlanningResult>
  compare: (baseId: string, compId: string) => Promise<void>
}

export const useScenarioStore = create<ScenarioState>((set, get) => ({
  scenarios: [],
  activeId: null,
  comparison: null,
  isLoading: false,

  loadScenarios: async () => {
    const scenarios = await getScenarios()
    set({ scenarios })
  },

  setActive: async (id) => {
    set({ activeId: id, isLoading: true })
    try {
      const result: PlanningResult = await getScenario(id)
      useRefineryStore.getState().setActiveResult(result)
    } finally {
      set({ isLoading: false })
    }
  },

  branch: async (parentId, name, changes) => {
    set({ isLoading: true })
    try {
      const result = await branchScenario(parentId, { name, changes })
      useRefineryStore.getState().setActiveResult(result)
      set({ activeId: result.scenario_id })
      await get().loadScenarios()
      return result
    } finally {
      set({ isLoading: false })
    }
  },

  compare: async (baseId, compId) => {
    const comparison = await compareScenarios(baseId, compId)
    set({ comparison })
  },
}))
