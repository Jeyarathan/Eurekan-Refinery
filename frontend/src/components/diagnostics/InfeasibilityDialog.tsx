import { AlertOctagon, X } from 'lucide-react'

import type { InfeasibilityReport } from '../../types'

interface Props {
  report: InfeasibilityReport
  onClose: () => void
}

export function InfeasibilityDialog({ report, onClose }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertOctagon className="text-rose-500" size={20} />
            <h2 className="text-lg font-semibold text-rose-900">No Feasible Plan</h2>
          </div>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X size={20} />
          </button>
        </div>

        <div className="mt-4 space-y-3">
          {report.violated_constraints.map((v, i) => (
            <div key={i} className="rounded-md border border-rose-200 bg-rose-50 p-3 text-xs">
              <div className="font-semibold text-rose-900">{v.display_name}</div>
              <div className="mt-0.5 text-rose-700">
                Violation: {v.violation.toFixed(4)}
              </div>
              {v.relaxation_suggestion && (
                <p className="mt-1 text-rose-800">{v.relaxation_suggestion}</p>
              )}
              {v.relaxation_cost != null && (
                <div className="mt-1 text-rose-600">
                  Cost: ${v.relaxation_cost.toLocaleString()}
                </div>
              )}
            </div>
          ))}
        </div>

        {report.cheapest_fix && (
          <div className="mt-4 rounded-md border border-emerald-200 bg-emerald-50 p-3">
            <div className="text-xs font-semibold text-emerald-900">Cheapest Fix</div>
            <p className="mt-1 text-xs text-emerald-800">{report.cheapest_fix}</p>
          </div>
        )}

        {report.suggestions.length > 0 && (
          <div className="mt-3 space-y-1">
            {report.suggestions.map((s, i) => (
              <p key={i} className="text-xs text-slate-600">{s}</p>
            ))}
          </div>
        )}

        <div className="mt-5 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md bg-slate-100 px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-200"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
