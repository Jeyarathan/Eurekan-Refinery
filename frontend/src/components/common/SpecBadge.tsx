interface Props {
  name: string
  value: number
  limit: number
  /** 'min' for specs like RON >= 87; 'max' for specs like sulfur <= 0.10 */
  direction: 'min' | 'max'
  unit?: string
}

export function SpecBadge({ name, value, limit, direction, unit = '' }: Props) {
  const margin =
    direction === 'min' ? value - limit : limit - value
  const marginPct = limit !== 0 ? (margin / Math.abs(limit)) * 100 : 0

  let status: 'pass' | 'tight' | 'fail'
  if (margin < 0) {
    status = 'fail'
  } else if (marginPct < 10) {
    status = 'tight'
  } else {
    status = 'pass'
  }

  const colors = {
    pass: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    tight: 'bg-amber-50 text-amber-700 border-amber-200',
    fail: 'bg-rose-50 text-rose-700 border-rose-200',
  }

  const icons = { pass: '\u2713', tight: '\u26A0', fail: '\u2717' }

  const display =
    value >= 100
      ? value.toFixed(1)
      : value >= 1
        ? value.toFixed(2)
        : value.toFixed(4)

  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium ${colors[status]}`}
      title={`${name}: ${display}${unit} (${direction === 'min' ? '>=' : '<='} ${limit}${unit})`}
    >
      {name} {display}{unit} {icons[status]}
    </span>
  )
}
