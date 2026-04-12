import { useState } from 'react'
import { Layers, Loader2 } from 'lucide-react'

import { useRefineryStore } from '../../stores/refineryStore'

const BASE = '/api'

interface AltPlan {
  name: string
  margin: number
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
        body: JSON.stringify({ scenario_id: scenarioId, tolerance: 0.10 }),
      })
      if (res.ok) {
        setPlans(await res.json())
        setSearched(true)
      }
    } finally {
      setLoading(false)
    }
  }

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
          Find Alternatives
        </button>
      </div>

      {!searched && !loading && (
        <p className="text-xs text-slate-500">
          Search for near-optimal plans with different crude slates.
        </p>
      )}

      {searched && plans.length <= 1 && (
        <p className="text-xs text-slate-500">
          No alternatives within 10% of optimal margin. The current plan is uniquely best.
        </p>
      )}

      {plans.length > 1 && (
        <div className="space-y-2">
          <p className="text-xs text-slate-600">
            {plans.length} plans achieve similar margin:
          </p>
          {plans.map((p) => (
            <div
              key={p.scenario_id}
              className="rounded-md border border-slate-100 px-3 py-2"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-slate-900">{p.name}</span>
                <span className="text-xs tabular-nums font-semibold text-emerald-600">
                  {fmtK(p.margin)}/d
                </span>
              </div>
              {p.comparison && (
                <div className="mt-1 text-[10px] text-slate-500">
                  <span
                    className={
                      p.comparison.margin_delta >= 0
                        ? 'text-emerald-600'
                        : 'text-rose-600'
                    }
                  >
                    {p.comparison.margin_delta >= 0 ? '+' : ''}
                    {fmtK(p.comparison.margin_delta)}
                  </span>{' '}
                  vs optimal. {p.comparison.key_insight}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
