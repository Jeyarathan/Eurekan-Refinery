import { useState } from 'react'
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ArrowRight, Loader2 } from 'lucide-react'

import { useScenarioStore } from '../../stores/scenarioStore'

const fmtMargin = (n: number) => {
  const sign = n >= 0 ? '+' : ''
  if (Math.abs(n) >= 1_000_000) return `${sign}$${(n / 1_000_000).toFixed(2)}M`
  return `${sign}$${(n / 1000).toFixed(1)}k`
}

export function ScenarioComparison() {
  const scenarios = useScenarioStore((s) => s.scenarios)
  const comparison = useScenarioStore((s) => s.comparison)
  const compare = useScenarioStore((s) => s.compare)

  const [baseId, setBaseId] = useState('')
  const [compId, setCompId] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleCompare() {
    if (!baseId || !compId || baseId === compId) return
    setLoading(true)
    try {
      await compare(baseId, compId)
    } finally {
      setLoading(false)
    }
  }

  // Crude slate changes as chart data
  const slateData = comparison
    ? Object.entries(comparison.crude_slate_changes)
        .filter(([, v]) => Math.abs(v) > 10)
        .map(([crude, delta]) => ({ crude, delta }))
        .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
    : []

  // Product volume deltas
  const productData = comparison
    ? Object.entries(comparison.product_volume_deltas)
        .filter(([, v]) => Math.abs(v) > 10)
        .map(([product, delta]) => ({ product: product.replace(/_/g, ' '), delta }))
        .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
    : []

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-slate-900">Compare Scenarios</h3>

      <div className="flex items-end gap-2">
        <div className="flex-1">
          <label className="block text-[10px] font-medium text-slate-500">Base</label>
          <select
            value={baseId}
            onChange={(e) => setBaseId(e.target.value)}
            className="mt-0.5 w-full rounded border border-slate-200 px-2 py-1.5 text-xs"
          >
            <option value="">Select…</option>
            {scenarios.map((s) => (
              <option key={s.scenario_id} value={s.scenario_id}>
                {s.scenario_name}
              </option>
            ))}
          </select>
        </div>
        <ArrowRight size={14} className="mb-2 text-slate-400" />
        <div className="flex-1">
          <label className="block text-[10px] font-medium text-slate-500">Comparison</label>
          <select
            value={compId}
            onChange={(e) => setCompId(e.target.value)}
            className="mt-0.5 w-full rounded border border-slate-200 px-2 py-1.5 text-xs"
          >
            <option value="">Select…</option>
            {scenarios.map((s) => (
              <option key={s.scenario_id} value={s.scenario_id}>
                {s.scenario_name}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          onClick={handleCompare}
          disabled={!baseId || !compId || baseId === compId || loading}
          className="flex items-center gap-1 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading && <Loader2 size={12} className="animate-spin" />}
          Compare
        </button>
      </div>

      {comparison && (
        <div className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
          {/* Margin delta */}
          <div className="text-center">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">
              Margin Delta
            </div>
            <div
              className={`text-3xl font-bold tabular-nums ${
                comparison.margin_delta >= 0 ? 'text-emerald-600' : 'text-rose-600'
              }`}
            >
              {fmtMargin(comparison.margin_delta)}
              <span className="text-sm font-normal text-slate-500">/d</span>
            </div>
          </div>

          {/* Conversion delta */}
          {Math.abs(comparison.conversion_delta) > 0.01 && (
            <div className="text-center text-xs text-slate-600">
              Conversion: {comparison.conversion_delta >= 0 ? '+' : ''}
              {comparison.conversion_delta.toFixed(1)}%
            </div>
          )}

          {/* Key insight */}
          {comparison.key_insight && (
            <p className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-700">
              {comparison.key_insight}
            </p>
          )}

          {/* Crude slate changes */}
          {slateData.length > 0 && (
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">
                Crude Slate Changes (bbl/d)
              </div>
              <ResponsiveContainer width="100%" height={Math.max(80, slateData.length * 28)}>
                <BarChart data={slateData} layout="vertical" margin={{ left: 40, right: 10 }}>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="crude" tick={{ fontSize: 10 }} width={40} />
                  <Tooltip formatter={(v) => `${Number(v) >= 0 ? '+' : ''}${Number(v).toLocaleString()} bbl/d`} />
                  <Bar dataKey="delta" radius={[0, 4, 4, 0]} barSize={14}>
                    {slateData.map((d, i) => (
                      <Cell key={i} fill={d.delta >= 0 ? '#10b981' : '#ef4444'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Product volume deltas */}
          {productData.length > 0 && (
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">
                Product Volume Changes (bbl/d)
              </div>
              <div className="space-y-1">
                {productData.map((d) => (
                  <div key={d.product} className="flex items-center justify-between text-xs">
                    <span className="capitalize text-slate-700">{d.product}</span>
                    <span
                      className={`tabular-nums font-medium ${
                        d.delta >= 0 ? 'text-emerald-600' : 'text-rose-600'
                      }`}
                    >
                      {d.delta >= 0 ? '+' : ''}
                      {(d.delta / 1000).toFixed(1)}k
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
