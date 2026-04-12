import { useState } from 'react'
import { Layers, Loader2 } from 'lucide-react'

import { useRefineryStore } from '../../stores/refineryStore'

const BASE = '/api'

interface AltPlan {
  name: string
  description: string
  axis: string
  margin: number
  margin_pct: number
  scenario_id: string
  comparison: {
    margin_delta: number
    key_insight: string
  } | null
}

const fmtK = (n: number) =>
  `$${Math.abs(n) >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : (n / 1000).toFixed(1) + 'k'}`

export function AlternativesPanel() {
  const scenarioId = useRefineryStore((s) => s.activeScenarioId)
  const [plans, setPlans] = useState<AltPlan[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)

  async function handleSearch() {
    if (!scenarioId) return
    setLoading(true)
    try {
      const res = await fetch(`${BASE}/ai/alternatives`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario_id: scenarioId, tolerance: 0.05 }),
      })
      if (res.ok) {
        setPlans(await res.json())
        setSearched(true)
      }
    } finally {
      setLoading(false)
    }
  }

  const crudeAlts = plans.filter((p) => p.axis === 'crude')
  const productAlts = plans.filter((p) => p.axis === 'product')

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
          <Layers size={14} className="text-indigo-500" />
          Alternatives
        </h3>
        <button
          type="button"
          onClick={handleSearch}
          disabled={loading || !scenarioId}
          className="flex items-center gap-1 rounded-md bg-indigo-600 px-2.5 py-1 text-[10px] font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading ? <Loader2 size={10} className="animate-spin" /> : <Layers size={10} />}
          {loading ? 'Searching...' : 'Find Alternatives'}
        </button>
      </div>

      {!searched && !loading && (
        <p className="text-xs text-slate-500">
          Search for near-optimal plans with different crude slates or product mixes.
        </p>
      )}

      {searched && plans.length === 0 && (
        <p className="text-xs text-slate-500">
          No alternatives found within tolerance. Current plan is uniquely optimal.
        </p>
      )}

      {plans.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs text-slate-600">
            {plans.length} alternative{plans.length > 1 ? 's' : ''} found:
          </p>

          {crudeAlts.length > 0 && (
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">
                Crude Variations
              </div>
              <div className="space-y-1.5">
                {crudeAlts.map((p) => (
                  <PlanCard key={p.scenario_id} plan={p} />
                ))}
              </div>
            </div>
          )}

          {productAlts.length > 0 && (
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">
                Product Variations
              </div>
              <div className="space-y-1.5">
                {productAlts.map((p) => (
                  <PlanCard key={p.scenario_id} plan={p} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function PlanCard({ plan }: { plan: AltPlan }) {
  return (
    <div className="rounded-md border border-slate-100 px-3 py-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-slate-900">{plan.name}</span>
        <div className="text-right">
          <span className="text-xs tabular-nums font-semibold text-emerald-600">
            {fmtK(plan.margin)}/d
          </span>
          <span className="ml-1 text-[9px] text-slate-500">
            ({plan.margin_pct.toFixed(1)}%)
          </span>
        </div>
      </div>
      <p className="mt-0.5 text-[10px] text-slate-600">{plan.description}</p>
    </div>
  )
}
