import { useEffect, useState } from 'react'
import { AlertTriangle, Loader2 } from 'lucide-react'

import { getDiagnostics } from '../../api/client'
import { useRefineryStore } from '../../stores/refineryStore'
import type { ConstraintDiagnostic } from '../../types'

function UtilBar({ pct }: { pct: number }) {
  const clamped = Math.max(0, Math.min(100, pct))
  const color =
    clamped >= 95 ? 'bg-rose-500' : clamped >= 80 ? 'bg-amber-500' : 'bg-emerald-500'
  return (
    <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
      <div className={`h-full ${color}`} style={{ width: `${clamped}%` }} />
    </div>
  )
}

export function ConstraintPanel() {
  const scenarioId = useRefineryStore((s) => s.activeScenarioId)
  const [diagnostics, setDiagnostics] = useState<ConstraintDiagnostic[]>([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<ConstraintDiagnostic | null>(null)

  useEffect(() => {
    if (!scenarioId) return
    setLoading(true)
    getDiagnostics(scenarioId)
      .then(setDiagnostics)
      .catch(() => setDiagnostics([]))
      .finally(() => setLoading(false))
  }, [scenarioId])

  const binding = diagnostics.filter((d) => d.binding)

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-900">
          Bottlenecks ({binding.length} binding)
        </h3>
        {loading && <Loader2 size={14} className="animate-spin text-indigo-500" />}
      </div>

      {/* Heat map grid */}
      {diagnostics.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1">
          {diagnostics.slice(0, 20).map((d) => {
            const score = d.bottleneck_score
            const bg =
              score >= 80
                ? 'bg-rose-500'
                : score >= 40
                  ? 'bg-amber-400'
                  : score > 0
                    ? 'bg-emerald-400'
                    : 'bg-slate-200'
            return (
              <button
                key={d.constraint_name}
                type="button"
                onClick={() => setSelected(d)}
                title={`${d.display_name}: ${d.bottleneck_score.toFixed(0)}`}
                className={`h-4 w-4 rounded-sm ${bg} transition-transform hover:scale-125`}
              />
            )
          })}
        </div>
      )}

      {/* List of binding constraints */}
      <div className="space-y-2">
        {binding.slice(0, 10).map((d) => (
          <button
            key={d.constraint_name}
            type="button"
            onClick={() => setSelected(d)}
            className={`w-full rounded-md border px-3 py-2 text-left text-xs transition-colors ${
              selected?.constraint_name === d.constraint_name
                ? 'border-indigo-300 bg-indigo-50'
                : 'border-slate-100 hover:bg-slate-50'
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="font-medium text-slate-900">{d.display_name}</span>
              <div className="flex items-center gap-2">
                <UtilBar pct={d.bottleneck_score} />
                <span className="tabular-nums text-slate-500">
                  {d.bottleneck_score.toFixed(0)}
                </span>
              </div>
            </div>
            {d.shadow_price != null && Math.abs(d.shadow_price) > 0.01 && (
              <div className="mt-0.5 text-[10px] text-slate-500">
                Shadow price: ${d.shadow_price.toFixed(2)}
                {d.source_stream && ` — ${d.source_stream}`}
              </div>
            )}
          </button>
        ))}
      </div>

      {/* Detail panel for selected constraint */}
      {selected && (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3">
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="mt-0.5 text-amber-600" />
            <div className="text-xs">
              <div className="font-semibold text-amber-900">{selected.display_name}</div>
              {selected.relaxation_suggestion && (
                <p className="mt-1 text-amber-800">{selected.relaxation_suggestion}</p>
              )}
              {selected.relaxation_cost != null && (
                <p className="mt-1 text-amber-700">
                  Estimated relaxation cost: ${selected.relaxation_cost.toLocaleString()}
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
