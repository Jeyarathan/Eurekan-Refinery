import { useCallback, useState } from 'react'
import { Layers, Loader2 } from 'lucide-react'

import { getScenario } from '../../api/client'
import { useRefineryStore } from '../../stores/refineryStore'
import type { PlanningResult } from '../../types'

const BASE = '/api'

interface AltPlan {
  name: string
  description?: string
  axis?: string
  margin: number
  margin_pct?: number
  scenario_id: string
}

const fmtK = (n: number) =>
  n >= 1000 ? `${(n / 1000).toFixed(1)}k` : n.toFixed(0)
const fmtM = (n: number) =>
  `$${Math.abs(n) >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : (n / 1000).toFixed(0) + 'k'}`

export function AlternativesPanel() {
  const scenarioId = useRefineryStore((s) => s.activeScenarioId)
  const activeResult = useRefineryStore((s) => s.activeResult)
  const [plans, setPlans] = useState<AltPlan[]>([])
  const [details, setDetails] = useState<Map<string, PlanningResult>>(new Map())
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
        const alts: AltPlan[] = await res.json()
        setPlans(alts)
        setSearched(true)
        // Fetch full results for all alternatives (for the table)
        const detailMap = new Map<string, PlanningResult>()
        for (const a of alts) {
          try {
            const r = await getScenario(a.scenario_id)
            detailMap.set(a.scenario_id, r)
          } catch { /* skip */ }
        }
        setDetails(detailMap)
      }
    } finally {
      setLoading(false)
    }
  }

  const loadPlan = useCallback(async (sid: string) => {
    const r = details.get(sid)
    if (r) {
      useRefineryStore.getState().setActiveResult(r)
    }
  }, [details])

  if (!searched && !loading) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
            <Layers size={14} className="text-indigo-500" />
            Near-Optimal Alternatives
          </h3>
          <button
            type="button"
            onClick={handleSearch}
            disabled={!scenarioId}
            className="flex items-center gap-1 rounded-md bg-indigo-600 px-2.5 py-1 text-[10px] font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            <Layers size={10} /> Find Alternatives
          </button>
        </div>
        <p className="text-xs text-slate-500">
          Search for plans with different crude slates or product mixes that achieve similar margin.
        </p>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-2 text-xs text-slate-600">
          <Loader2 size={14} className="animate-spin text-indigo-500" />
          Exploring near-optimal solutions (9 objectives)...
        </div>
      </div>
    )
  }

  if (plans.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h3 className="mb-1 text-sm font-semibold text-slate-900">Alternatives</h3>
        <p className="text-xs text-slate-500">No alternatives within 5%. Current plan is uniquely optimal.</p>
      </div>
    )
  }

  // Build comparison table data
  const optP = activeResult?.periods[0]
  const optSlate = optP?.crude_slate ?? {}
  const optProducts = optP?.product_volumes ?? {}
  const optConv = optP?.fcc_result?.conversion ?? 0

  // Collect all crudes used in any plan (>500 bbl/d)
  const allCrudes = new Set<string>()
  for (const [, v] of Object.entries(optSlate)) if (v > 500) allCrudes.add(Object.keys(optSlate).find(k => optSlate[k] === v) ?? '')
  Object.keys(optSlate).forEach(c => { if (optSlate[c] > 500) allCrudes.add(c) })
  for (const p of plans) {
    const d = details.get(p.scenario_id)
    if (d) {
      Object.entries(d.periods[0]?.crude_slate ?? {}).forEach(([c, v]) => {
        if (v > 500) allCrudes.add(c)
      })
    }
  }
  const crudeList = [...allCrudes].sort()
  const productList = ['gasoline', 'diesel', 'jet', 'naphtha', 'fuel_oil', 'lpg']

  function cellColor(val: number, ref: number, better: 'higher' | 'lower'): string {
    if (ref === 0) return ''
    const pct = (val - ref) / Math.abs(ref)
    if (Math.abs(pct) < 0.10) return ''
    const isBetter = better === 'higher' ? pct > 0 : pct < 0
    return isBetter ? 'bg-emerald-50 text-emerald-800' : 'bg-rose-50 text-rose-800'
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
          <Layers size={14} className="text-indigo-500" />
          {plans.length} Alternatives Found
        </h3>
        <button
          type="button"
          onClick={handleSearch}
          className="text-[10px] text-indigo-600 hover:underline"
        >
          Refresh
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[10px]">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50">
              <th className="sticky left-0 z-10 bg-slate-50 px-3 py-2 text-left font-medium text-slate-600">Metric</th>
              <th className="px-2 py-2 text-right font-semibold text-indigo-700">
                <div>Optimal</div>
                <div className="font-normal text-slate-500">[Active]</div>
              </th>
              {plans.map((p) => (
                <th key={p.scenario_id} className="px-2 py-2 text-right font-medium text-slate-700">
                  <div>{p.name}</div>
                  <div className="font-normal text-[9px] text-slate-400">{(p.description ?? p.name).split('.')[0]}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {/* Economics */}
            <tr className="bg-slate-50"><td colSpan={2 + plans.length} className="px-3 py-1 text-[9px] uppercase tracking-wide text-slate-500">Economics</td></tr>
            <tr className="border-b border-slate-50">
              <td className="sticky left-0 z-10 bg-white px-3 py-1 text-slate-600">Margin ($/d)</td>
              <td className="px-2 py-1 text-right tabular-nums font-semibold text-emerald-600">{fmtM(activeResult?.total_margin ?? 0)}</td>
              {plans.map((p) => (
                <td key={p.scenario_id} className={`px-2 py-1 text-right tabular-nums ${cellColor(p.margin, activeResult?.total_margin ?? 0, 'higher')}`}>
                  {fmtM(p.margin)}
                </td>
              ))}
            </tr>
            <tr className="border-b border-slate-50">
              <td className="sticky left-0 z-10 bg-white px-3 py-1 text-slate-600">% of Optimal</td>
              <td className="px-2 py-1 text-right tabular-nums text-slate-700">100%</td>
              {plans.map((p) => (
                <td key={p.scenario_id} className="px-2 py-1 text-right tabular-nums text-slate-600">{(p.margin_pct ?? ((activeResult?.total_margin ?? 1) > 0 ? p.margin / (activeResult?.total_margin ?? 1) * 100 : 0)).toFixed(1)}%</td>
              ))}
            </tr>

            {/* Crudes */}
            <tr className="bg-slate-50"><td colSpan={2 + plans.length} className="px-3 py-1 text-[9px] uppercase tracking-wide text-slate-500">Crude Slate (bbl/d)</td></tr>
            {crudeList.map((c) => {
              const optVal = optSlate[c] ?? 0
              return (
                <tr key={c} className="border-b border-slate-50">
                  <td className="sticky left-0 z-10 bg-white px-3 py-1 text-slate-600">{c}</td>
                  <td className="px-2 py-1 text-right tabular-nums text-slate-700">{fmtK(optVal)}</td>
                  {plans.map((p) => {
                    const d = details.get(p.scenario_id)
                    const v = d?.periods[0]?.crude_slate[c] ?? 0
                    return (
                      <td key={p.scenario_id} className={`px-2 py-1 text-right tabular-nums ${cellColor(v, optVal, 'higher')}`}>
                        {v > 100 ? fmtK(v) : '—'}
                      </td>
                    )
                  })}
                </tr>
              )
            })}

            {/* Products */}
            <tr className="bg-slate-50"><td colSpan={2 + plans.length} className="px-3 py-1 text-[9px] uppercase tracking-wide text-slate-500">Products (bbl/d)</td></tr>
            {productList.map((prod) => {
              const optVal = optProducts[prod] ?? 0
              const better = prod === 'fuel_oil' ? 'lower' as const : 'higher' as const
              return (
                <tr key={prod} className="border-b border-slate-50">
                  <td className="sticky left-0 z-10 bg-white px-3 py-1 capitalize text-slate-600">{prod.replace(/_/g, ' ')}</td>
                  <td className="px-2 py-1 text-right tabular-nums text-slate-700">{fmtK(optVal)}</td>
                  {plans.map((p) => {
                    const d = details.get(p.scenario_id)
                    const v = d?.periods[0]?.product_volumes[prod] ?? 0
                    return (
                      <td key={p.scenario_id} className={`px-2 py-1 text-right tabular-nums ${cellColor(v, optVal, better)}`}>
                        {fmtK(v)}
                      </td>
                    )
                  })}
                </tr>
              )
            })}

            {/* FCC */}
            <tr className="bg-slate-50"><td colSpan={2 + plans.length} className="px-3 py-1 text-[9px] uppercase tracking-wide text-slate-500">FCC</td></tr>
            <tr className="border-b border-slate-50">
              <td className="sticky left-0 z-10 bg-white px-3 py-1 text-slate-600">Conversion %</td>
              <td className="px-2 py-1 text-right tabular-nums text-slate-700">{optConv.toFixed(1)}</td>
              {plans.map((p) => {
                const d = details.get(p.scenario_id)
                const v = d?.periods[0]?.fcc_result?.conversion ?? 0
                return (
                  <td key={p.scenario_id} className="px-2 py-1 text-right tabular-nums text-slate-600">{v.toFixed(1)}</td>
                )
              })}
            </tr>

            {/* Actions */}
            <tr>
              <td className="sticky left-0 z-10 bg-white px-3 py-2"></td>
              <td className="px-2 py-2 text-right text-[9px] font-semibold text-indigo-600">Active</td>
              {plans.map((p) => (
                <td key={p.scenario_id} className="px-2 py-2 text-right">
                  <button
                    type="button"
                    onClick={() => loadPlan(p.scenario_id)}
                    className="rounded bg-indigo-50 px-2 py-0.5 text-[9px] font-medium text-indigo-700 hover:bg-indigo-100"
                  >
                    Load
                  </button>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}
