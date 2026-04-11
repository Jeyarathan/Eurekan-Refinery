import { useState } from 'react'
import { GitBranch, LayoutDashboard, Sparkles } from 'lucide-react'

type View = 'flowsheet' | 'scenarios' | 'oracle'

interface NavItem {
  id: View
  label: string
  Icon: typeof LayoutDashboard
}

const NAV_ITEMS: NavItem[] = [
  { id: 'flowsheet', label: 'Flowsheet', Icon: LayoutDashboard },
  { id: 'scenarios', label: 'Scenarios', Icon: GitBranch },
  { id: 'oracle', label: 'Oracle', Icon: Sparkles },
]

function App() {
  const [activeView, setActiveView] = useState<View>('flowsheet')

  return (
    <div className="flex h-screen bg-slate-50 text-slate-800">
      {/* Sidebar */}
      <aside className="flex w-60 flex-col border-r border-slate-200 bg-white">
        <div className="flex items-center gap-3 border-b border-slate-200 px-6 py-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600 font-bold text-white">
            E
          </div>
          <div>
            <div className="text-sm font-semibold tracking-tight text-slate-900">
              Eurekan
            </div>
            <div className="text-xs text-slate-500">Refinery Planner</div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4">
          <ul className="space-y-1">
            {NAV_ITEMS.map(({ id, label, Icon }) => {
              const isActive = id === activeView
              return (
                <li key={id}>
                  <button
                    type="button"
                    onClick={() => setActiveView(id)}
                    className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-indigo-50 text-indigo-700'
                        : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                    }`}
                  >
                    <Icon size={18} strokeWidth={2} />
                    {label}
                  </button>
                </li>
              )
            })}
          </ul>
        </nav>

        <div className="border-t border-slate-200 px-6 py-4 text-xs text-slate-400">
          v0.2.0 · Stage 2A
        </div>
      </aside>

      {/* Main column */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-14 items-center justify-between border-b border-slate-200 bg-white px-6">
          <h1 className="text-base font-semibold text-slate-900">
            Eurekan Refinery Planner
          </h1>
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
            API connected
          </div>
        </header>

        <main className="flex-1 overflow-auto bg-slate-50 p-6">
          <ViewPlaceholder view={activeView} />
        </main>
      </div>
    </div>
  )
}

function ViewPlaceholder({ view }: { view: View }) {
  const titles: Record<View, string> = {
    flowsheet: 'Refinery Flowsheet',
    scenarios: 'Scenarios',
    oracle: 'Oracle Analysis',
  }
  const subtitles: Record<View, string> = {
    flowsheet: 'Material flow graph from the active planning result.',
    scenarios: 'Browse and branch scenarios.',
    oracle: 'Compare actual operations against the optimal plan.',
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-10 text-center shadow-sm">
      <h2 className="text-2xl font-semibold text-slate-900">{titles[view]}</h2>
      <p className="mt-2 text-sm text-slate-500">{subtitles[view]}</p>
      <p className="mt-6 inline-block rounded-md bg-slate-100 px-3 py-1 text-xs text-slate-500">
        Shell only — components arrive in Sprint 6.2+
      </p>
    </div>
  )
}

export default App
