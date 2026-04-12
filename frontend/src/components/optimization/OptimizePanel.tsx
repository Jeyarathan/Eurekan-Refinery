import { useCallback, useState } from 'react'
import { AlertTriangle, Play, Zap } from 'lucide-react'

import { quickOptimize } from '../../api/client'
import { useRefineryStore } from '../../stores/refineryStore'
import { LoadingSpinner } from '../common/LoadingSpinner'

type Mode = 'optimize' | 'simulate' | 'hybrid'

const MODES: { id: Mode; label: string }[] = [
  { id: 'optimize', label: 'Optimize' },
  { id: 'simulate', label: 'Simulate' },
  { id: 'hybrid', label: 'Hybrid' },
]

export function OptimizePanel() {
  const [mode, setMode] = useState<Mode>('optimize')
  const isOptimizing = useRefineryStore((s) => s.isOptimizing)
  const isStale = useRefineryStore((s) => s.isStale)
  const activeResult = useRefineryStore((s) => s.activeResult)
  const startOptimizing = useRefineryStore((s) => s.startOptimizing)
  const finishOptimizing = useRefineryStore((s) => s.finishOptimizing)

  const handleOptimize = useCallback(async () => {
    startOptimizing()
    try {
      const result = await quickOptimize({ scenario_name: `Quick ${mode}` })
      finishOptimizing(result)
    } catch {
      // Error: leave isOptimizing=false so the user can retry
      useRefineryStore.getState().reset()
    }
  }, [mode, startOptimizing, finishOptimizing])

  const margin = activeResult?.total_margin ?? 0
  const solveTime = activeResult?.solve_time_seconds ?? 0
  const status = activeResult?.solver_status ?? '—'

  return (
    <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
      {/* Stale banner */}
      {isStale && (
        <div className="flex items-center gap-2 rounded-t-lg bg-amber-50 px-4 py-2 text-xs font-medium text-amber-800 border-b border-amber-200">
          <AlertTriangle size={14} />
          Inputs changed — results may be outdated. Click Optimize to refresh.
        </div>
      )}

      <div className="flex items-center gap-4 px-4 py-3">
        {/* Mode selector */}
        <div className="flex rounded-md border border-slate-200 text-xs">
          {MODES.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              onClick={() => setMode(id)}
              className={`px-3 py-1.5 font-medium transition-colors first:rounded-l-md last:rounded-r-md ${
                id === mode
                  ? 'bg-indigo-600 text-white'
                  : 'bg-white text-slate-600 hover:bg-slate-50'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Optimize button */}
        <button
          type="button"
          onClick={handleOptimize}
          disabled={isOptimizing}
          className={`flex items-center gap-2 rounded-md px-5 py-2 text-sm font-semibold text-white shadow-sm transition-colors ${
            isOptimizing
              ? 'cursor-not-allowed bg-indigo-400'
              : 'bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800'
          }`}
        >
          {isOptimizing ? (
            <LoadingSpinner size={16} />
          ) : (
            <Zap size={16} strokeWidth={2.5} />
          )}
          {isOptimizing ? 'Solving…' : 'Optimize'}
        </button>

        {/* Results summary (inline) */}
        {activeResult && (
          <div className="ml-auto flex items-center gap-6 text-xs">
            <div className="text-center">
              <div className="text-[10px] uppercase tracking-wide text-slate-500">
                Margin
              </div>
              <div
                className={`text-lg font-bold tabular-nums ${
                  isStale ? 'text-slate-400' : 'text-emerald-600'
                }`}
              >
                ${(margin / 1000).toFixed(1)}k
                <span className="text-[10px] font-normal text-slate-500">/d</span>
              </div>
            </div>
            <div className="text-center">
              <div className="text-[10px] uppercase tracking-wide text-slate-500">
                Solve
              </div>
              <div className="text-sm font-semibold tabular-nums text-slate-700">
                {solveTime < 1 ? `${(solveTime * 1000).toFixed(0)}ms` : `${solveTime.toFixed(1)}s`}
              </div>
            </div>
            <div className="text-center">
              <div className="text-[10px] uppercase tracking-wide text-slate-500">
                Status
              </div>
              <div className="flex items-center gap-1">
                <Play
                  size={10}
                  className={
                    status === 'optimal'
                      ? 'fill-emerald-500 text-emerald-500'
                      : 'fill-amber-500 text-amber-500'
                  }
                />
                <span className="text-sm font-medium text-slate-700 capitalize">
                  {status}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
