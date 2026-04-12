import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Loader2 } from 'lucide-react'

import { optimize } from '../../api/client'
import { useRefineryStore } from '../../stores/refineryStore'

interface DataPoint {
  conversion: number
  margin: number
}

const fmtK = (n: number) => `$${(n / 1000).toFixed(0)}k`

// Default profitable prices (must match services.py quick_optimize defaults)
const DEFAULT_PRICES: Record<string, number> = {
  gasoline: 95,
  diesel: 100,
  jet: 100,
  naphtha: 60,
  fuel_oil: 55,
  lpg: 50,
}

export function ConversionSlider() {
  const activeResult = useRefineryStore((s) => s.activeResult)
  const [data, setData] = useState<DataPoint[]>([])
  const [loading, setLoading] = useState(false)
  const [sliderVal, setSliderVal] = useState(80)
  const computed = useRef(false)

  const currentConv = activeResult?.periods[0]?.fcc_result?.conversion ?? 80

  // Sync slider to current optimal on first result
  useEffect(() => {
    if (activeResult) setSliderVal(Math.round(currentConv))
  }, [activeResult, currentConv])

  // Pre-compute margin at 3 representative points on first load
  useEffect(() => {
    if (computed.current || !activeResult) return
    computed.current = true
    setLoading(true)

    async function sweep() {
      const points: DataPoint[] = []
      for (const conv of [72, 80, 88]) {
        try {
          const r = await optimize({
            mode: 'hybrid',
            periods: [{ period_id: 0, duration_hours: 24, product_prices: DEFAULT_PRICES }],
            fixed_variables: { 'fcc_conversion[0]': conv },
            scenario_name: `Sweep ${conv}%`,
          })
          points.push({ conversion: conv, margin: r.total_margin })
        } catch {
          points.push({ conversion: conv, margin: 0 })
        }
      }
      setData(points)
      setLoading(false)
    }

    sweep()
  }, [activeResult])

  // On slider drag: update display only
  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setSliderVal(parseInt(e.target.value, 10))
    },
    [],
  )

  // On slider release: call API with fixed conversion, update flowsheet
  const handleRelease = useCallback(async () => {
    setLoading(true)
    try {
      const result = await optimize({
        mode: 'hybrid',
        periods: [{ period_id: 0, duration_hours: 24, product_prices: DEFAULT_PRICES }],
        fixed_variables: { 'fcc_conversion[0]': sliderVal },
        scenario_name: `Conv ${sliderVal}%`,
      })

      // Update the flowsheet with the new result
      useRefineryStore.getState().setActiveResult(result)

      // Add the new data point to the curve (merge + deduplicate + sort)
      setData((prev) => {
        const filtered = prev.filter((p) => p.conversion !== sliderVal)
        return [...filtered, { conversion: sliderVal, margin: result.total_margin }]
          .sort((a, b) => a.conversion - b.conversion)
      })
    } finally {
      setLoading(false)
    }
  }, [sliderVal])

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-900">Conversion Explorer</h3>
        {loading && <Loader2 size={14} className="animate-spin text-indigo-500" />}
      </div>

      {/* Chart */}
      {data.length > 0 && (
        <ResponsiveContainer width="100%" height={140}>
          <LineChart data={data} margin={{ left: 10, right: 10, top: 5, bottom: 5 }}>
            <XAxis
              dataKey="conversion"
              tick={{ fontSize: 10 }}
              label={{ value: 'Conversion %', position: 'insideBottom', offset: -2, fontSize: 10 }}
            />
            <YAxis tick={{ fontSize: 10 }} tickFormatter={fmtK} width={50} />
            <Tooltip formatter={(v) => fmtK(Number(v))} labelFormatter={(l) => `${l}%`} />
            <Line
              type="monotone"
              dataKey="margin"
              stroke="#6366f1"
              strokeWidth={2}
              dot={{ r: 3, fill: '#6366f1' }}
            />
            <ReferenceLine
              x={Math.round(currentConv)}
              stroke="#10b981"
              strokeDasharray="4 3"
              label={{ value: 'Optimal', position: 'top', fontSize: 9, fill: '#10b981' }}
            />
          </LineChart>
        </ResponsiveContainer>
      )}

      {/* Slider */}
      <div className="mt-3">
        <div className="flex items-center justify-between text-[10px] text-slate-500">
          <span>68%</span>
          <span className="font-medium text-slate-700">{sliderVal}%</span>
          <span>90%</span>
        </div>
        <input
          type="range"
          min={68}
          max={90}
          step={1}
          value={sliderVal}
          onChange={handleChange}
          onPointerUp={handleRelease}
          disabled={loading}
          className="mt-1 w-full accent-indigo-600 disabled:opacity-50"
        />
      </div>

      <p className="mt-2 text-[10px] text-slate-500">
        Current: {currentConv.toFixed(1)}%. Release slider to solve at {sliderVal}%.
      </p>
    </div>
  )
}
