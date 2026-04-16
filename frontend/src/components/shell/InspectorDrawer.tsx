import { useState } from 'react'
import { X } from 'lucide-react'
import { BINDS, FCC_EQS } from './mockData'

type Tab = 'overview' | 'equations' | 'calibration'

const UNIT_NAMES: Record<string, string> = {
  cdu_1: 'CDU 1 (Crude Distillation)',
  fcc_1: 'FCC 1 (Fluid Catalytic Cracker)',
  reformer_1: 'Catalytic Reformer',
  nht_1: 'Naphtha Hydrotreater',
  kht_1: 'Kerosene Hydrotreater',
  dht_1: 'Diesel Hydrotreater',
  alky_1: 'Alkylation Unit',
  scanfiner_1: 'Scanfiner (FCC Naphtha HDS)',
  splitter_1: 'Naphtha Splitter',
  goht_1: 'Gas Oil Hydrotreater',
  vacuum_1: 'Vacuum Distillation',
  coker_1: 'Delayed Coker',
}

interface Props {
  uid: string
  onClose: () => void
}

export function InspectorDrawer({ uid, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('overview')
  const displayName = UNIT_NAMES[uid] ?? uid
  const isFCC = uid === 'fcc_1'

  const unitBinds = BINDS.filter((b) => b.unit === uid)

  return (
    <div className="fixed right-0 top-[46px] bottom-0 z-30 flex w-[360px] flex-col border-l border-slate-200 bg-white shadow-lg">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">
            {displayName}
          </div>
          <div className="text-[10px] text-slate-400 font-mono">{uid}</div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
        >
          <X size={18} />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-200">
        {(['overview', 'equations', 'calibration'] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`flex-1 px-3 py-2 text-xs font-medium transition-colors ${
              t === tab
                ? 'border-b-2 border-indigo-600 text-indigo-700'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-4 text-xs">
        {tab === 'overview' && (
          <OverviewTab uid={uid} binds={unitBinds} />
        )}
        {tab === 'equations' && (
          <EquationsTab isFCC={isFCC} />
        )}
        {tab === 'calibration' && (
          <CalibrationTab isFCC={isFCC} />
        )}
      </div>
    </div>
  )
}

function OverviewTab({
  uid,
  binds,
}: {
  uid: string
  binds: typeof BINDS
}) {
  // Derive a mock utilization from binds or default
  const mainBind = binds.find((b) => b.unit === uid)
  const util = mainBind?.util ?? 65

  return (
    <div className="space-y-4">
      {/* Utilization bar */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-slate-600 font-medium">Utilization</span>
          <span className="font-bold text-slate-900">{util}%</span>
        </div>
        <div className="h-3 w-full rounded-full bg-slate-100 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              util >= 95
                ? 'bg-red-500'
                : util >= 80
                  ? 'bg-amber-400'
                  : 'bg-emerald-400'
            }`}
            style={{ width: `${Math.min(util, 100)}%` }}
          />
        </div>
      </div>

      {/* Binding constraints */}
      {binds.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-2">
            Binding Constraints
          </div>
          <div className="space-y-2">
            {binds.map((b) => (
              <div
                key={b.name}
                className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-slate-800">{b.name}</span>
                  <span className="font-mono text-indigo-600">
                    ${b.shadow.toFixed(2)}
                  </span>
                </div>
                <div className="mt-0.5 text-[11px] text-slate-500">
                  {b.desc}
                </div>
                <div className="mt-1 h-2 w-full rounded-full bg-slate-200 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      b.util >= 95 ? 'bg-red-400' : 'bg-amber-400'
                    }`}
                    style={{ width: `${b.util}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {binds.length === 0 && (
        <p className="text-slate-500 italic">
          No binding constraints on this unit.
        </p>
      )}
    </div>
  )
}

function EquationsTab({ isFCC }: { isFCC: boolean }) {
  if (!isFCC) {
    return (
      <div className="text-slate-500 italic">
        Linear yield splits — no nonlinear equations for this unit.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">
        FCC Correlation Equations
      </div>
      {FCC_EQS.map((eq) => (
        <div
          key={eq.n}
          className="rounded-md border border-slate-200 bg-slate-50 p-3"
        >
          <div className="font-medium text-slate-800">{eq.n}</div>
          <div className="mt-1 font-mono text-[11px] text-purple-700 break-all">
            {eq.eq}
          </div>
          <div className="mt-1 flex items-center justify-between">
            <span className="text-slate-500">{eq.vars}</span>
            <span className="font-bold text-slate-900">{eq.v}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

function CalibrationTab({ isFCC }: { isFCC: boolean }) {
  if (!isFCC) {
    return (
      <div className="text-slate-500 italic">
        Calibration data not available for this unit.
      </div>
    )
  }

  const params = [
    { label: 'Gasoline yield cal', value: '1.02', range: [0.9, 1.1] },
    { label: 'Coke yield cal', value: '1.00', range: [0.9, 1.1] },
    { label: 'Regen temp offset', value: '0', range: [-20, 20] },
    { label: 'RON offset', value: '0.0', range: [-2, 2] },
  ]

  return (
    <div className="space-y-4">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">
        FCC Calibration Parameters
      </div>
      {params.map((p) => (
        <div key={p.label}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-slate-700 font-medium">{p.label}</span>
            <span className="font-mono text-slate-900">{p.value}</span>
          </div>
          <input
            type="range"
            min={p.range[0]}
            max={p.range[1]}
            step={0.01}
            defaultValue={Number(p.value)}
            className="w-full accent-indigo-600"
          />
          <div className="flex justify-between text-[10px] text-slate-400">
            <span>{p.range[0]}</span>
            <span>{p.range[1]}</span>
          </div>
        </div>
      ))}
      <button
        type="button"
        className="w-full rounded bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700"
      >
        Re-optimize with Calibration
      </button>
    </div>
  )
}
