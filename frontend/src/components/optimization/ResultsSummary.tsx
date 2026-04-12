import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { PlanningResult } from '../../types'

const PRODUCT_COLORS: Record<string, string> = {
  gasoline: '#6366f1',
  diesel: '#0891b2',
  jet: '#0d9488',
  naphtha: '#d97706',
  fuel_oil: '#64748b',
  lpg: '#a855f7',
}

const fmt = (n: number) => {
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`
  if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}k`
  return `$${n.toFixed(0)}`
}

const fmtVol = (n: number) =>
  n >= 1000 ? `${(n / 1000).toFixed(1)}k` : n.toFixed(0)

interface Props {
  result: PlanningResult
  isStale?: boolean
}

export function ResultsSummary({ result, isStale }: Props) {
  const period = result.periods[0]
  if (!period) return null

  const margin = period.margin
  const revenue = period.revenue
  const crudeCost = period.crude_cost
  const operatingCost = period.operating_cost

  // Revenue breakdown by product
  const defaultPrices: Record<string, number> = {
    gasoline: 95,
    diesel: 100,
    jet: 100,
    naphtha: 60,
    fuel_oil: 70,
    lpg: 50,
  }
  const revenueByProduct = Object.entries(period.product_volumes)
    .map(([product, volume]) => ({
      product: product.replace(/_/g, ' '),
      revenue: volume * (defaultPrices[product] ?? 0),
      volume,
      color: PRODUCT_COLORS[product] ?? '#94a3b8',
    }))
    .filter((d) => d.revenue > 0)
    .sort((a, b) => b.revenue - a.revenue)

  const staleClass = isStale ? 'opacity-50' : ''

  return (
    <div className={`space-y-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm ${staleClass}`}>
      {/* Headline margin */}
      <div className="text-center">
        <div className="text-[10px] uppercase tracking-widest text-slate-500">
          Net Margin
        </div>
        <div className="text-3xl font-bold tabular-nums text-emerald-600">
          {fmt(margin)}
          <span className="text-sm font-normal text-slate-500">/day</span>
        </div>
      </div>

      {/* Economics breakdown */}
      <div className="grid grid-cols-3 gap-2 text-center text-xs">
        <div>
          <div className="text-[10px] uppercase text-slate-500">Revenue</div>
          <div className="font-semibold tabular-nums text-slate-900">
            {fmt(revenue)}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-slate-500">Crude cost</div>
          <div className="font-semibold tabular-nums text-slate-900">
            {fmt(crudeCost)}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-slate-500">Opex</div>
          <div className="font-semibold tabular-nums text-slate-900">
            {fmt(operatingCost)}
          </div>
        </div>
      </div>

      {/* Revenue chart */}
      <div>
        <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">
          Revenue by product
        </div>
        <ResponsiveContainer width="100%" height={120}>
          <BarChart
            data={revenueByProduct}
            layout="vertical"
            margin={{ left: 60, right: 10, top: 0, bottom: 0 }}
          >
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="product"
              tick={{ fontSize: 10, fill: '#64748b' }}
              width={60}
            />
            <Tooltip
              formatter={(value) => fmt(Number(value))}
              labelFormatter={(label) => String(label)}
            />
            <Bar dataKey="revenue" radius={[0, 4, 4, 0]} barSize={14}>
              {revenueByProduct.map((entry, i) => (
                <Cell key={i} fill={entry.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Product volumes table */}
      <div>
        <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">
          Product volumes
        </div>
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-slate-100 text-left text-slate-500">
              <th className="py-1 font-medium">Product</th>
              <th className="py-1 text-right font-medium">bbl/d</th>
              <th className="py-1 text-right font-medium">$/d</th>
            </tr>
          </thead>
          <tbody>
            {revenueByProduct.map((d) => (
              <tr key={d.product} className="border-b border-slate-50">
                <td className="py-1 capitalize text-slate-700">{d.product}</td>
                <td className="py-1 text-right tabular-nums text-slate-700">
                  {fmtVol(d.volume)}
                </td>
                <td className="py-1 text-right tabular-nums text-slate-700">
                  {fmt(d.revenue)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
