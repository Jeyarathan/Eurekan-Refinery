import { CHAIN_PRESETS, DOMAIN_PRESETS } from './mockData'

const STATUS_COLORS: Record<string, string> = {
  binding: 'bg-red-100 text-red-700',
  tight: 'bg-amber-100 text-amber-700',
  ok: 'bg-emerald-100 text-emerald-700',
}

interface Props {
  presetMode: 'chain' | 'domain'
  activeGrp: string
}

export function GroupedView({ presetMode, activeGrp }: Props) {
  if (presetMode === 'chain') {
    const preset = CHAIN_PRESETS.find((p) => p.id === activeGrp)
    if (!preset) return <EmptyState />
    return <ChainView preset={preset} />
  }

  const preset = DOMAIN_PRESETS.find((p) => p.id === activeGrp)
  if (!preset) return <EmptyState />
  return <DomainView preset={preset} />
}

function EmptyState() {
  return (
    <div className="flex h-full items-center justify-center text-sm text-slate-500">
      Select a group from the sidebar.
    </div>
  )
}

function ChainView({ preset }: { preset: (typeof CHAIN_PRESETS)[number] }) {
  return (
    <div className="space-y-4 p-4 overflow-auto">
      {/* Unit strip */}
      <UnitStrip units={preset.units} color={preset.color} />

      {/* Product header */}
      <div className="rounded-lg border bg-white p-4 shadow-sm" style={{ borderColor: preset.color + '40' }}>
        <div className="text-sm font-semibold text-slate-900">{preset.name}</div>
        <div className="text-xs text-slate-500 mt-0.5">{preset.product}</div>
      </div>

      {/* Flow panel */}
      {preset.flow.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-2">
            Material Flow
          </div>
          <div className="space-y-1">
            {preset.flow.map((f, i) => (
              <div
                key={i}
                className="flex items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-slate-50"
              >
                <span className="font-medium text-slate-700 w-28 shrink-0 truncate">
                  {f.f}
                </span>
                <span className="text-slate-400">&rarr;</span>
                <span className="font-medium text-slate-700 w-28 shrink-0 truncate">
                  {f.t}
                </span>
                <span className="ml-auto text-slate-500">{f.s}</span>
                <div className="w-20">
                  <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.min((f.v / 80) * 100, 100)}%`,
                        backgroundColor: preset.color,
                      }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Specs table */}
      {preset.specs.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-2">
            Product Specifications
          </div>
          <DataTable
            headers={['Spec', 'Value', 'Limit', 'Margin', 'Status']}
            rows={preset.specs.map((s) => [s.sp, s.val, s.lim, s.mar, s.st])}
            statusCol={4}
          />
        </div>
      )}

      {/* Blend table */}
      {preset.blend.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-2">
            Blend Components
          </div>
          <DataTable
            headers={['Component', 'Volume', '%', 'RON', 'Sulfur']}
            rows={preset.blend.map((b) => [b.c, b.vol, b.pct, b.ron, b.s])}
          />
        </div>
      )}
    </div>
  )
}

function DomainView({ preset }: { preset: (typeof DOMAIN_PRESETS)[number] }) {
  return (
    <div className="space-y-4 p-4 overflow-auto">
      {/* Unit strip */}
      <UnitStrip units={preset.units} color={preset.color} />

      {/* Domain header */}
      <div className="rounded-lg border bg-white p-4 shadow-sm" style={{ borderColor: preset.color + '40' }}>
        <div className="text-sm font-semibold text-slate-900">{preset.name}</div>
        <div className="text-xs text-slate-500 mt-0.5">{preset.desc}</div>
      </div>

      {/* Decisions */}
      {preset.decisions.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-2">
            Key Decisions
          </div>
          <div className="space-y-2">
            {preset.decisions.map((dec, i) => (
              <div
                key={i}
                className="rounded-md border border-slate-100 bg-slate-50 px-3 py-2 text-xs"
              >
                <div className="font-medium text-slate-800">{dec.d}</div>
                <div className="text-slate-600 mt-0.5">{dec.c}</div>
                <div className="text-indigo-600 mt-0.5 italic">{dec.i}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Data table */}
      {preset.data.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-2">
            Details
          </div>
          <DataTable headers={preset.headers} rows={preset.data} />
        </div>
      )}
    </div>
  )
}

function UnitStrip({ units, color }: { units: string[]; color: string }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {units.map((u) => (
        <span
          key={u}
          className="rounded px-2 py-1 text-[10px] font-medium text-white"
          style={{ backgroundColor: color }}
        >
          {u}
        </span>
      ))}
    </div>
  )
}

function DataTable({
  headers,
  rows,
  statusCol,
}: {
  headers: string[]
  rows: string[][]
  statusCol?: number
}) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="border-b border-slate-200">
          {headers.map((h) => (
            <th
              key={h}
              className="px-2 py-1.5 text-left text-[10px] uppercase tracking-wide text-slate-500 font-medium"
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, ri) => (
          <tr
            key={ri}
            className={ri % 2 === 1 ? 'bg-slate-50' : ''}
          >
            {row.map((cell, ci) => (
              <td key={ci} className="px-2 py-1.5 text-slate-700">
                {statusCol !== undefined && ci === statusCol ? (
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                      STATUS_COLORS[cell] ?? 'bg-slate-100 text-slate-600'
                    }`}
                  >
                    {cell}
                  </span>
                ) : (
                  cell
                )}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
