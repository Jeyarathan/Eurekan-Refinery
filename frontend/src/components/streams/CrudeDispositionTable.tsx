import { useRefineryStore } from '../../stores/refineryStore'

const fmtK = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : n.toFixed(0))
const fmtMoney = (n: number) =>
  Math.abs(n) >= 1e6 ? `$${(n / 1e6).toFixed(2)}M` : `$${(n / 1000).toFixed(1)}k`

export function CrudeDispositionTable() {
  const result = useRefineryStore((s) => s.activeResult)
  const highlightedNodeId = useRefineryStore((s) => s.highlightedNodeId)
  const setHighlightedNode = useRefineryStore((s) => s.setHighlightedNode)

  if (!result || result.crude_valuations.length === 0) {
    return <p className="text-xs text-slate-500">No crude data available.</p>
  }

  const valuations = [...result.crude_valuations].sort((a, b) => b.total_volume - a.total_volume)

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="mb-2 text-sm font-semibold text-slate-900">Crude Disposition</h3>
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-slate-100 text-left text-slate-500">
            <th className="py-1 font-medium">Crude</th>
            <th className="py-1 text-right font-medium">Volume</th>
            <th className="py-1 text-right font-medium">Value</th>
            <th className="py-1 text-right font-medium">Cost</th>
            <th className="py-1 text-right font-medium">Net</th>
          </tr>
        </thead>
        <tbody>
          {valuations.map((cv) => {
            const nodeId = `crude_${cv.crude_id}`
            const isHighlighted = highlightedNodeId === nodeId
            return (
              <tr
                key={cv.crude_id}
                onClick={() => setHighlightedNode(isHighlighted ? null : nodeId)}
                className={`cursor-pointer border-b border-slate-50 transition-colors ${
                  isHighlighted ? 'bg-indigo-50' : 'hover:bg-slate-50'
                }`}
              >
                <td className="py-1 font-medium text-slate-900">{cv.crude_id}</td>
                <td className="py-1 text-right tabular-nums text-slate-700">
                  {fmtK(cv.total_volume)}
                </td>
                <td className="py-1 text-right tabular-nums text-slate-700">
                  {fmtMoney(cv.value_created)}
                </td>
                <td className="py-1 text-right tabular-nums text-slate-700">
                  {fmtMoney(cv.crude_cost)}
                </td>
                <td
                  className={`py-1 text-right tabular-nums font-medium ${
                    cv.net_margin >= 0 ? 'text-emerald-600' : 'text-rose-600'
                  }`}
                >
                  {fmtMoney(cv.net_margin)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
