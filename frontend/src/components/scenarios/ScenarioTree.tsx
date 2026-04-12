import { useEffect, useState } from 'react'
import { GitBranch, Loader2 } from 'lucide-react'

import { useScenarioStore } from '../../stores/scenarioStore'
import type { ScenarioSummary } from '../../types'
import { CreateScenarioDialog } from './CreateScenarioDialog'

const fmtMargin = (n: number) =>
  `$${Math.abs(n) >= 1_000_000 ? (n / 1_000_000).toFixed(2) + 'M' : (n / 1000).toFixed(1) + 'k'}`

const fmtTime = (iso: string) => {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

export function ScenarioTree() {
  const scenarios = useScenarioStore((s) => s.scenarios)
  const activeId = useScenarioStore((s) => s.activeId)
  const isLoading = useScenarioStore((s) => s.isLoading)
  const loadScenarios = useScenarioStore((s) => s.loadScenarios)
  const setActive = useScenarioStore((s) => s.setActive)
  const branch = useScenarioStore((s) => s.branch)

  const [branchTarget, setBranchTarget] = useState<ScenarioSummary | null>(null)

  useEffect(() => {
    loadScenarios()
  }, [loadScenarios])

  // Build parent-child hierarchy
  const roots = scenarios.filter((s) => !s.parent_scenario_id)
  const childrenOf = (id: string) => scenarios.filter((s) => s.parent_scenario_id === id)

  function renderNode(scenario: ScenarioSummary, depth: number) {
    const isActive = scenario.scenario_id === activeId
    const children = childrenOf(scenario.scenario_id)
    return (
      <div key={scenario.scenario_id} style={{ marginLeft: depth * 16 }}>
        <button
          type="button"
          onClick={() => setActive(scenario.scenario_id)}
          className={`mb-1 flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors ${
            isActive
              ? 'border border-indigo-300 bg-indigo-50 text-indigo-900'
              : 'border border-transparent hover:bg-slate-100'
          }`}
        >
          <div className="flex-1 min-w-0">
            <div className="truncate font-medium">{scenario.scenario_name}</div>
            <div className="flex items-center gap-2 text-[10px] text-slate-500">
              <span className="tabular-nums">{fmtMargin(scenario.total_margin)}/d</span>
              <span>{fmtTime(scenario.created_at)}</span>
              <span
                className={`rounded px-1 py-0.5 text-[9px] font-semibold uppercase ${
                  scenario.solver_status === 'optimal'
                    ? 'bg-emerald-100 text-emerald-700'
                    : 'bg-amber-100 text-amber-700'
                }`}
              >
                {scenario.solver_status}
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              setBranchTarget(scenario)
            }}
            title="Branch from this scenario"
            className="rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
          >
            <GitBranch size={14} />
          </button>
        </button>
        {children.map((child) => renderNode(child, depth + 1))}
      </div>
    )
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-900">
          Scenarios ({scenarios.length})
        </h3>
        {isLoading && <Loader2 size={14} className="animate-spin text-indigo-500" />}
      </div>

      {scenarios.length === 0 && !isLoading && (
        <p className="text-xs text-slate-500">
          No scenarios yet. Click Optimize to create the first one.
        </p>
      )}

      <div className="space-y-0.5">
        {roots.map((r) => renderNode(r, 0))}
      </div>

      {branchTarget && (
        <CreateScenarioDialog
          parentId={branchTarget.scenario_id}
          parentName={branchTarget.scenario_name}
          onClose={() => setBranchTarget(null)}
          onBranch={async (pid, name, changes) => {
            await branch(pid, name, changes)
          }}
        />
      )}
    </div>
  )
}
