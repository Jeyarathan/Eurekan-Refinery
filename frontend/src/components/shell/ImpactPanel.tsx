import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { IMPACTS } from './mockData'

const CAT_COLORS: Record<string, string> = {
  debottleneck: 'bg-orange-100 text-orange-700',
  spec: 'bg-purple-100 text-purple-700',
  crude: 'bg-cyan-100 text-cyan-700',
  equipment: 'bg-yellow-100 text-yellow-700',
}

export function ImpactPanel() {
  const [expanded, setExpanded] = useState<number | null>(null)

  return (
    <div className="mx-auto max-w-3xl space-y-3 p-6">
      <h2 className="text-lg font-semibold text-slate-900">
        Impact Ranking
      </h2>
      <p className="text-xs text-slate-500">
        Top opportunities ranked by incremental margin impact.
      </p>

      <div className="space-y-2">
        {IMPACTS.map((item) => {
          const isOpen = expanded === item.id
          return (
            <div
              key={item.id}
              className="rounded-lg border border-slate-200 bg-white shadow-sm"
            >
              <button
                type="button"
                onClick={() => setExpanded(isOpen ? null : item.id)}
                className="flex w-full items-center gap-3 px-4 py-3 text-left"
              >
                {/* Rank badge */}
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-bold text-indigo-700">
                  {item.id}
                </span>

                {/* Action + category */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-slate-800 truncate">
                      {item.action}
                    </span>
                    <span
                      className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                        CAT_COLORS[item.cat] ?? 'bg-slate-100 text-slate-600'
                      }`}
                    >
                      {item.cat}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-xs text-slate-500">
                      Confidence: {item.conf}
                    </span>
                  </div>
                </div>

                {/* Delta */}
                <span className="shrink-0 text-sm font-bold text-emerald-600">
                  {item.delta}
                </span>

                {/* Expand icon */}
                {isOpen ? (
                  <ChevronDown size={16} className="shrink-0 text-slate-400" />
                ) : (
                  <ChevronRight size={16} className="shrink-0 text-slate-400" />
                )}
              </button>

              {isOpen && (
                <div className="border-t border-slate-100 px-4 py-3 text-xs">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">
                        Current
                      </div>
                      <div className="rounded bg-slate-50 px-3 py-2 font-mono text-slate-700">
                        {item.from}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">
                        Proposed
                      </div>
                      <div className="rounded bg-emerald-50 px-3 py-2 font-mono text-emerald-700">
                        {item.to}
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="mt-3 rounded bg-indigo-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700"
                  >
                    Apply to Scenario
                  </button>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
