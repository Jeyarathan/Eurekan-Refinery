import { Component, useEffect, useRef, useState, type ReactNode } from 'react'
import {
  AlertCircle,
  GitBranch,
  LayoutDashboard,
  Loader2,
  Sparkles,
} from 'lucide-react'

import { quickOptimize } from './api/client'
import { RefineryFlowsheet } from './components/flowsheet/RefineryFlowsheet'
import { OptimizePanel } from './components/optimization/OptimizePanel'
import { ResultsSummary } from './components/optimization/ResultsSummary'
import { useRefineryStore } from './stores/refineryStore'

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
  const [error, setError] = useState<string | null>(null)
  const activeResult = useRefineryStore((s) => s.activeResult)
  const isOptimizing = useRefineryStore((s) => s.isOptimizing)
  const isStale = useRefineryStore((s) => s.isStale)

  // Mutex ref survives StrictMode double-mount — prevents the second
  // useEffect invocation from firing a duplicate API call that would
  // queue behind the first on the single-worker backend and hang.
  const fetchStarted = useRef(false)

  useEffect(() => {
    if (fetchStarted.current) return
    fetchStarted.current = true

    useRefineryStore.getState().startOptimizing()
    quickOptimize({ scenario_name: 'Initial' })
      .then((result) => {
        useRefineryStore.getState().finishOptimizing(result)
      })
      .catch((e) => {
        useRefineryStore.setState({ isOptimizing: false })
        setError(e instanceof Error ? e.message : String(e))
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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

        {/* Results sidebar panel */}
        {activeResult && (
          <div className="border-t border-slate-200 p-3">
            <ResultsSummary result={activeResult} isStale={isStale} />
          </div>
        )}

        <div className="border-t border-slate-200 px-6 py-4 text-xs text-slate-400">
          v0.2.0 · Stage 2A
        </div>
      </aside>

      {/* Main column */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Optimize panel (fixed at top) */}
        <div className="border-b border-slate-200 bg-white">
          <OptimizePanel />
        </div>

        <main className="flex-1 overflow-hidden bg-slate-50 p-4">
          {activeView === 'flowsheet' && (
            <FlowsheetView
              isOptimizing={isOptimizing}
              error={error}
              hasResult={activeResult != null}
            />
          )}
          {activeView !== 'flowsheet' && <ViewPlaceholder view={activeView} />}
        </main>
      </div>
    </div>
  )
}

function FlowsheetView({
  isOptimizing,
  error,
  hasResult,
}: {
  isOptimizing: boolean
  error: string | null
  hasResult: boolean
}) {
  // All hooks MUST be called before any early returns (Rules of Hooks)
  const activeResult = useRefineryStore((s) => s.activeResult)
  const showFull = useRefineryStore((s) => s.showFullDiagram)

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="max-w-md rounded-lg border border-rose-200 bg-rose-50 p-6 text-center">
          <AlertCircle className="mx-auto h-10 w-10 text-rose-500" />
          <h2 className="mt-3 text-lg font-semibold text-rose-900">
            Could not reach the API
          </h2>
          <p className="mt-2 text-sm text-rose-700">{error}</p>
          <p className="mt-3 text-xs text-rose-600">
            Make sure the FastAPI backend is running on port 8000.
          </p>
        </div>
      </div>
    )
  }

  if (isOptimizing && !hasResult) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <Loader2 className="mx-auto h-10 w-10 animate-spin text-indigo-600" />
          <p className="mt-3 text-sm text-slate-600">
            Solving the refinery NLP…
          </p>
        </div>
      </div>
    )
  }

  if (!activeResult) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-500">
        No result yet.
      </div>
    )
  }

  return (
    <ErrorBoundary>
      <RefineryFlowsheet result={activeResult} showFullDiagram={showFull} />
    </ErrorBoundary>
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
        Coming in Sprint 7+
      </p>
    </div>
  )
}

// ErrorBoundary catches render crashes and shows them instead of a white screen.
class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full items-center justify-center p-8">
          <div className="max-w-lg rounded-lg border border-rose-200 bg-rose-50 p-6">
            <h2 className="text-lg font-semibold text-rose-900">
              Render error
            </h2>
            <pre className="mt-2 overflow-auto whitespace-pre-wrap text-xs text-rose-700">
              {this.state.error.message}
            </pre>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

export default App
