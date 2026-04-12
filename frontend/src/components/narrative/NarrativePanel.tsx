import { useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight, Info, Loader2, Sparkles, XCircle } from 'lucide-react'

import { useRefineryStore } from '../../stores/refineryStore'
import type { SolutionNarrative } from '../../types'

const BASE = '/api'

export function NarrativePanel() {
  const scenarioId = useRefineryStore((s) => s.activeScenarioId)
  const [narrative, setNarrative] = useState<SolutionNarrative | null>(null)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  async function handleGenerate() {
    if (!scenarioId) return
    setLoading(true)
    try {
      const res = await fetch(`${BASE}/ai/narrative`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario_id: scenarioId }),
      })
      if (res.ok) setNarrative(await res.json())
    } finally {
      setLoading(false)
    }
  }

  const severityIcon = (s: string) => {
    if (s === 'critical' || s === 'warning') return <AlertTriangle size={12} className="text-amber-600" />
    if (s === 'info') return <Info size={12} className="text-blue-500" />
    return <XCircle size={12} className="text-rose-500" />
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
          <Sparkles size={14} className="text-indigo-500" />
          Narrative
        </h3>
        <button
          type="button"
          onClick={handleGenerate}
          disabled={loading || !scenarioId}
          className="flex items-center gap-1 rounded-md bg-indigo-600 px-2.5 py-1 text-[10px] font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
          Generate
        </button>
      </div>

      {!narrative && !loading && (
        <p className="text-xs text-slate-500">Click Generate to create a plan narrative.</p>
      )}

      {narrative && (
        <div className="space-y-3">
          {/* Executive summary */}
          <p className="text-xs leading-relaxed text-slate-700">{narrative.executive_summary}</p>

          {/* Economics */}
          {narrative.economics_narrative && (
            <p className="rounded bg-slate-50 px-2 py-1.5 text-[10px] text-slate-600">
              {narrative.economics_narrative}
            </p>
          )}

          {/* Risk flags */}
          {narrative.risk_flags.length > 0 && (
            <div className="space-y-1">
              <div className="text-[10px] uppercase tracking-wide text-slate-500">Risks</div>
              {narrative.risk_flags.map((f, i) => (
                <div key={i} className="flex items-start gap-1.5 rounded border border-slate-100 px-2 py-1.5">
                  {severityIcon(f.severity)}
                  <div className="text-[10px]">
                    <div className="font-medium text-slate-800">{f.message}</div>
                    <div className="text-slate-500">{f.recommendation}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Decision explanations (accordion) */}
          {narrative.decision_explanations.length > 0 && (
            <div className="space-y-1">
              <div className="text-[10px] uppercase tracking-wide text-slate-500">Decisions</div>
              {narrative.decision_explanations.map((d, i) => {
                const isOpen = expanded === `d${i}`
                return (
                  <div key={i} className="rounded border border-slate-100">
                    <button
                      type="button"
                      onClick={() => setExpanded(isOpen ? null : `d${i}`)}
                      className="flex w-full items-center gap-1 px-2 py-1.5 text-left text-[10px] font-medium text-slate-800"
                    >
                      {isOpen ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                      {d.decision}
                    </button>
                    {isOpen && (
                      <div className="px-2 pb-2 text-[10px] text-slate-600">
                        <p>{d.reasoning}</p>
                        <p className="mt-1 text-slate-500">
                          Alternatives: {d.alternatives_considered}
                        </p>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          {/* Data quality warnings */}
          {narrative.data_quality_warnings.length > 0 && (
            <div className="space-y-1">
              {narrative.data_quality_warnings.map((w, i) => (
                <p key={i} className="text-[10px] text-amber-700">{w}</p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
