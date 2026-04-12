import { useState } from 'react'
import { Loader2, X } from 'lucide-react'

interface Props {
  parentId: string
  parentName: string
  onClose: () => void
  onBranch: (
    parentId: string,
    name: string,
    changes: { product_prices?: Record<string, number> },
  ) => Promise<void>
}

export function CreateScenarioDialog({ parentId, parentName, onClose, onBranch }: Props) {
  const [name, setName] = useState(`${parentName} — variant`)
  const [gasolinePrice, setGasolinePrice] = useState('')
  const [dieselPrice, setDieselPrice] = useState('')
  const [fuelOilPrice, setFuelOilPrice] = useState('')
  const [isBusy, setIsBusy] = useState(false)

  async function handleCreate() {
    setIsBusy(true)
    const prices: Record<string, number> = {}
    if (gasolinePrice) prices.gasoline = parseFloat(gasolinePrice)
    if (dieselPrice) prices.diesel = parseFloat(dieselPrice)
    if (fuelOilPrice) prices.fuel_oil = parseFloat(fuelOilPrice)

    try {
      await onBranch(parentId, name, {
        product_prices: Object.keys(prices).length > 0 ? prices : undefined,
      })
      onClose()
    } finally {
      setIsBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">Branch Scenario</h2>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X size={20} />
          </button>
        </div>
        <p className="mt-1 text-xs text-slate-500">From: {parentName}</p>

        <div className="mt-4 space-y-3">
          <div>
            <label className="block text-xs font-medium text-slate-700">Scenario Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div className="text-xs font-medium text-slate-700">Price Overrides ($/bbl)</div>
          <div className="grid grid-cols-3 gap-2">
            {([['Gasoline', gasolinePrice, setGasolinePrice],
               ['Diesel', dieselPrice, setDieselPrice],
               ['Fuel Oil', fuelOilPrice, setFuelOilPrice]] as const).map(([label, val, setter]) => (
              <div key={label}>
                <label className="block text-[10px] text-slate-500">{label}</label>
                <input
                  type="number"
                  placeholder="—"
                  value={val}
                  onChange={(e) => setter(e.target.value)}
                  className="mt-0.5 w-full rounded border border-slate-200 px-2 py-1 text-xs tabular-nums"
                />
              </div>
            ))}
          </div>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-200 px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleCreate}
            disabled={isBusy || !name.trim()}
            className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {isBusy && <Loader2 size={14} className="animate-spin" />}
            Create &amp; Optimize
          </button>
        </div>
      </div>
    </div>
  )
}
