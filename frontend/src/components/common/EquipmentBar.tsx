interface Props {
  label: string
  current: number
  limit: number
  unit?: string
}

export function EquipmentBar({ label, current, limit, unit = '' }: Props) {
  const pct = limit > 0 ? Math.min((current / limit) * 100, 100) : 0
  const color =
    pct >= 95
      ? 'bg-rose-500'
      : pct >= 80
        ? 'bg-amber-500'
        : 'bg-emerald-500'

  const fmtVal = (n: number) =>
    n >= 10000 ? `${(n / 1000).toFixed(1)}k` : n.toLocaleString(undefined, { maximumFractionDigits: 0 })

  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between text-[11px]">
        <span className="font-medium text-slate-700">{label}</span>
        <span className="tabular-nums text-slate-500">
          {fmtVal(current)}{unit} / {fmtVal(limit)}{unit}{' '}
          <span className="font-semibold text-slate-700">({pct.toFixed(0)}%)</span>
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full rounded-full ${color} transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
