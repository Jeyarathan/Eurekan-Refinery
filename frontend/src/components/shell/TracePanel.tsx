import { useState } from 'react'
import { TRACES } from './mockData'

const TYPE_STYLE: Record<string, string> = {
  out: 'bg-indigo-50 border-indigo-200 text-indigo-800',
  dom: 'bg-red-50 border-red-200 text-red-800',
  eq: 'bg-purple-50 border-purple-200 text-purple-800',
  in: 'bg-orange-50 border-orange-200 text-orange-800',
  ins: 'bg-emerald-50 border-emerald-200 text-emerald-800',
  c: 'bg-white border-slate-200 text-slate-700',
}

const traceKeys = Object.keys(TRACES)

export function TracePanel() {
  const [activeTab, setActiveTab] = useState(traceKeys[0])
  const trace = TRACES[activeTab]

  if (!trace) return null

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <h2 className="text-lg font-semibold text-slate-900">
        Equation Trace
      </h2>
      <p className="text-xs text-slate-500">
        Trace a constraint back through the model equations to understand what drives it.
      </p>

      {/* Tab selector */}
      <div className="flex gap-1 rounded-lg border border-slate-200 bg-slate-100 p-1">
        {traceKeys.map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setActiveTab(key)}
            className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              key === activeTab
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {key.charAt(0).toUpperCase() + key.slice(1)}
          </button>
        ))}
      </div>

      {/* Header */}
      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="text-sm font-semibold text-slate-900">
          {trace.label}
        </div>
        <div className="mt-1 flex items-center gap-4 text-xs text-slate-500">
          <span>Spec: {trace.spec}</span>
          <span>Margin: {trace.margin}</span>
          {trace.bind && (
            <span className="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-bold text-red-700">
              BINDING
            </span>
          )}
        </div>
      </div>

      {/* Steps tree */}
      <div className="space-y-1.5">
        {trace.steps.map((step, i) => (
          <div
            key={i}
            style={{ marginLeft: step.d * 22 }}
            className={`rounded-md border px-3 py-2 text-xs ${
              TYPE_STYLE[step.t] ?? TYPE_STYLE.c
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{step.l}</span>
              {step.v && (
                <span className="shrink-0 font-mono font-semibold">
                  {step.v}
                </span>
              )}
            </div>
            <div className="mt-0.5 text-[11px] opacity-75">
              {step.desc}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
