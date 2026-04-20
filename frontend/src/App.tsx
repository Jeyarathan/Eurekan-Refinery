import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertCircle,
  BarChart3,
  Eye,
  GitBranch,
  LayoutDashboard,
  Loader2,
  Network,
  Droplets,
  Play,
  Search,
  Settings2,
  Sparkles,
  Zap,
} from 'lucide-react'

import { quickOptimize } from './api/client'
import { RefineryFlowsheet } from './components/flowsheet/RefineryFlowsheet'
import { ScenarioComparison } from './components/scenarios/ScenarioComparison'
import { ScenarioTree } from './components/scenarios/ScenarioTree'
import { GroupedView } from './components/shell/GroupedView'
import { ImpactPanel } from './components/shell/ImpactPanel'
import { InspectorDrawer } from './components/shell/InspectorDrawer'
import { CHAIN_PRESETS, DOMAIN_PRESETS } from './components/shell/mockData'
import { TracePanel } from './components/shell/TracePanel'
import { useRefineryStore } from './stores/refineryStore'
import { useScenarioStore } from './stores/scenarioStore'

type Page = 'flowsheet' | 'impact' | 'trace' | 'scenarios' | 'oracle'
type ViewMode = 'full' | 'grouped'
type PresetMode = 'chain' | 'domain'
type Lens = 'bottleneck' | 'sensitivity' | 'economics' | null
type Mode = 'optimize' | 'simulate' | 'hybrid'

interface NavItem {
  id: Page
  label: string
  Icon: typeof LayoutDashboard
}

const NAV_ITEMS: NavItem[] = [
  { id: 'flowsheet', label: 'Flowsheet', Icon: LayoutDashboard },
  { id: 'impact', label: 'Impact Ranking', Icon: BarChart3 },
  { id: 'trace', label: 'Equation Trace', Icon: Search },
  { id: 'scenarios', label: 'Scenarios', Icon: GitBranch },
  { id: 'oracle', label: 'Oracle', Icon: Sparkles },
]

const MODES: { id: Mode; label: string }[] = [
  { id: 'optimize', label: 'Optimize' },
  { id: 'simulate', label: 'Simulate' },
  { id: 'hybrid', label: 'Hybrid' },
]

function App() {
  const [page, setPage] = useState<Page>('flowsheet')
  const [view, setView] = useState<ViewMode>('full')
  const [presetMode, setPresetMode] = useState<PresetMode>('chain')
  const [activeGrp, setActiveGrp] = useState<string | null>(null)
  const [lens, setLens] = useState<Lens>(null)
  const [inspectUid, setInspectUid] = useState<string | null>(null)
  const [showMinor, setShowMinor] = useState(false)
  const [mode, setMode] = useState<Mode>('optimize')
  const [error, setError] = useState<string | null>(null)

  const activeResult = useRefineryStore((s) => s.activeResult)
  const isOptimizing = useRefineryStore((s) => s.isOptimizing)
  const isStale = useRefineryStore((s) => s.isStale)
  const showFullDiagram = useRefineryStore((s) => s.showFullDiagram)
  const toggleFullDiagram = useRefineryStore((s) => s.toggleFullDiagram)
  const showH2Network = useRefineryStore((s) => s.showH2Network)
  const toggleH2Network = useRefineryStore((s) => s.toggleH2Network)
  const showUtilities = useRefineryStore((s) => s.showUtilities)
  const toggleUtilities = useRefineryStore((s) => s.toggleUtilities)
  const startOptimizing = useRefineryStore((s) => s.startOptimizing)
  const finishOptimizing = useRefineryStore((s) => s.finishOptimizing)

  // Mutex ref survives StrictMode double-mount
  const fetchStarted = useRef(false)

  useEffect(() => {
    if (fetchStarted.current) return
    fetchStarted.current = true

    useRefineryStore.getState().startOptimizing()
    quickOptimize({ scenario_name: 'Initial' })
      .then((result) => {
        useRefineryStore.getState().finishOptimizing(result)
        useScenarioStore.getState().loadScenarios()
      })
      .catch((e) => {
        useRefineryStore.setState({ isOptimizing: false })
        setError(e instanceof Error ? e.message : String(e))
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleOptimize = useCallback(async () => {
    startOptimizing()
    try {
      const result = await quickOptimize({ scenario_name: `Quick ${mode}` })
      finishOptimizing(result)
    } catch {
      useRefineryStore.getState().reset()
    }
  }, [mode, startOptimizing, finishOptimizing])

  const margin = activeResult?.total_margin ?? 0
  const status = activeResult?.solver_status ?? '\u2014'

  const presets = presetMode === 'chain' ? CHAIN_PRESETS : DOMAIN_PRESETS

  const handleNodeClick = useCallback((id: string | null) => {
    useRefineryStore.getState().setHighlightedNode(id)
    if (id) setInspectUid(id)
  }, [])

  // Toggle lens
  const toggleLens = (l: Lens) => setLens((prev) => (prev === l ? null : l))

  return (
    <div className="flex h-screen bg-slate-50 text-slate-800">
      {/* ====== TOP BAR (46px) ====== */}
      <header className="fixed top-0 left-0 right-0 z-40 flex h-[46px] items-center border-b border-slate-200 bg-white px-4 gap-4">
        {/* Logo */}
        <div className="flex items-center gap-2 shrink-0">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-indigo-600 text-xs font-bold text-white">
            E
          </div>
          <span className="text-sm font-semibold tracking-tight text-slate-900 hidden sm:inline">
            Eurekan Refinery Planner
          </span>
        </div>

        {/* Mode selector */}
        <div className="flex rounded-md border border-slate-200 text-[11px]">
          {MODES.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              onClick={() => setMode(id)}
              className={`px-2.5 py-1 font-medium transition-colors first:rounded-l-md last:rounded-r-md ${
                id === mode
                  ? 'bg-indigo-600 text-white'
                  : 'bg-white text-slate-600 hover:bg-slate-50'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Optimize button */}
        <button
          type="button"
          onClick={handleOptimize}
          disabled={isOptimizing}
          className={`flex items-center gap-1.5 rounded-md px-4 py-1.5 text-xs font-semibold text-white shadow-sm transition-colors ${
            isOptimizing
              ? 'cursor-not-allowed bg-indigo-400'
              : 'bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800'
          }`}
        >
          {isOptimizing ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Zap size={14} strokeWidth={2.5} />
          )}
          {isOptimizing ? 'Solving\u2026' : 'Optimize'}
        </button>

        {/* Live Flow / Full Diagram toggle */}
        <button
          type="button"
          onClick={toggleFullDiagram}
          className={`flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-[11px] font-medium transition-colors ${
            showFullDiagram
              ? 'border-indigo-300 bg-indigo-50 text-indigo-700'
              : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
          }`}
        >
          {showFullDiagram ? <Network size={12} /> : <Eye size={12} />}
          {showFullDiagram ? 'Full' : 'Live'}
        </button>

        {/* H2 Network overlay toggle */}
        <button
          type="button"
          onClick={toggleH2Network}
          className={`flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-[11px] font-medium transition-colors ${
            showH2Network
              ? 'border-pink-300 bg-pink-50 text-pink-700'
              : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
          }`}
        >
          <Droplets size={12} />
          {showH2Network ? 'Hide H2' : 'Show H2'}
        </button>

        {/* Utilities lane toggle */}
        <button
          type="button"
          onClick={toggleUtilities}
          className={`flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-[11px] font-medium transition-colors ${
            showUtilities
              ? 'border-slate-400 bg-slate-100 text-slate-800'
              : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
          }`}
        >
          <Settings2 size={12} />
          {showUtilities ? 'Hide Utilities' : 'Show Utilities'}
        </button>

        {/* Stale indicator */}
        {isStale && (
          <span className="rounded bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-700">
            STALE
          </span>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Margin display */}
        {activeResult && (
          <div className="flex items-center gap-4 text-xs">
            <div className="text-right">
              <div className="text-[9px] uppercase tracking-wide text-slate-400">
                Margin
              </div>
              <div
                className={`text-base font-bold tabular-nums ${
                  isStale ? 'text-slate-400' : 'text-emerald-600'
                }`}
              >
                ${(margin / 1_000_000).toFixed(2)}M
                <span className="text-[9px] font-normal text-slate-400">/d</span>
              </div>
            </div>

            {/* Status */}
            <div className="flex items-center gap-1">
              <Play
                size={10}
                className={
                  status === 'optimal'
                    ? 'fill-emerald-500 text-emerald-500'
                    : 'fill-amber-500 text-amber-500'
                }
              />
              <span className="text-xs font-medium text-slate-700 capitalize">
                {status}
              </span>
            </div>
          </div>
        )}
      </header>

      {/* ====== SIDEBAR (195px) ====== */}
      <aside className="fixed left-0 top-[46px] bottom-0 z-20 flex w-[195px] flex-col border-r border-slate-200 bg-white overflow-hidden">
        {/* Navigation */}
        <nav className="px-2 py-3">
          <ul className="space-y-0.5">
            {NAV_ITEMS.map(({ id, label, Icon }) => {
              const isActive = id === page
              return (
                <li key={id}>
                  <button
                    type="button"
                    onClick={() => setPage(id)}
                    className={`flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors ${
                      isActive
                        ? 'bg-indigo-50 text-indigo-700'
                        : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                    }`}
                  >
                    <Icon size={15} strokeWidth={2} />
                    {label}
                  </button>
                </li>
              )
            })}
          </ul>
        </nav>

        {/* Flowsheet-specific controls */}
        {page === 'flowsheet' && (
          <div className="flex-1 overflow-auto border-t border-slate-200 px-2 py-3 space-y-3">
            {/* LENS section */}
            <div>
              <div className="px-1 text-[9px] uppercase tracking-widest text-slate-400 font-semibold mb-1.5">
                Lens
              </div>
              <div className="space-y-0.5">
                {(['bottleneck', 'sensitivity', 'economics'] as const).map((l) => (
                  <button
                    key={l}
                    type="button"
                    onClick={() => toggleLens(l)}
                    className={`flex w-full items-center rounded px-2 py-1 text-[11px] font-medium transition-colors ${
                      lens === l
                        ? 'bg-indigo-50 text-indigo-700'
                        : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'
                    }`}
                  >
                    {l.charAt(0).toUpperCase() + l.slice(1)}
                  </button>
                ))}
              </div>
            </div>

            {/* View tabs */}
            <div>
              <div className="px-1 text-[9px] uppercase tracking-widest text-slate-400 font-semibold mb-1.5">
                View
              </div>
              <div className="flex rounded-md border border-slate-200 text-[11px]">
                {(['full', 'grouped'] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setView(v)}
                    className={`flex-1 px-2 py-1 font-medium transition-colors first:rounded-l-md last:rounded-r-md ${
                      v === view
                        ? 'bg-indigo-600 text-white'
                        : 'bg-white text-slate-600 hover:bg-slate-50'
                    }`}
                  >
                    {v.charAt(0).toUpperCase() + v.slice(1)}
                  </button>
                ))}
              </div>
            </div>

            {/* Preset mode (only in grouped view) */}
            {view === 'grouped' && (
              <>
                <div>
                  <div className="px-1 text-[9px] uppercase tracking-widest text-slate-400 font-semibold mb-1.5">
                    Select Mode
                  </div>
                  <div className="flex rounded-md border border-slate-200 text-[10px]">
                    {(['chain', 'domain'] as const).map((m) => (
                      <button
                        key={m}
                        type="button"
                        onClick={() => {
                          setPresetMode(m)
                          setActiveGrp(null)
                        }}
                        className={`flex-1 px-2 py-1 font-medium transition-colors first:rounded-l-md last:rounded-r-md ${
                          m === presetMode
                            ? 'bg-indigo-600 text-white'
                            : 'bg-white text-slate-600 hover:bg-slate-50'
                        }`}
                      >
                        {m === 'chain' ? 'Product' : 'Domain'}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Preset groups list */}
                <div>
                  <div className="px-1 text-[9px] uppercase tracking-widest text-slate-400 font-semibold mb-1.5">
                    {presetMode === 'chain' ? 'Product Chains' : 'Domains'}
                  </div>
                  <div className="space-y-0.5">
                    {presets.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => setActiveGrp(p.id)}
                        className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-[11px] font-medium transition-colors ${
                          activeGrp === p.id
                            ? 'bg-indigo-50 text-indigo-700'
                            : 'text-slate-600 hover:bg-slate-50'
                        }`}
                      >
                        <span
                          className="h-2.5 w-2.5 rounded-full shrink-0"
                          style={{ backgroundColor: p.color }}
                        />
                        {p.name}
                      </button>
                    ))}
                  </div>
                </div>

                {/* MY GROUPS placeholder */}
                <div>
                  <div className="px-1 text-[9px] uppercase tracking-widest text-slate-400 font-semibold mb-1.5">
                    My Groups
                  </div>
                  <p className="px-1 text-[10px] text-slate-400 italic">
                    None yet
                  </p>
                </div>
              </>
            )}

            {/* Stream filter toggle */}
            <div>
              <button
                type="button"
                onClick={() => setShowMinor(!showMinor)}
                className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-[11px] font-medium transition-colors ${
                  showMinor
                    ? 'bg-indigo-50 text-indigo-700'
                    : 'text-slate-500 hover:bg-slate-50'
                }`}
              >
                <span
                  className={`h-3 w-3 rounded border-2 flex items-center justify-center ${
                    showMinor ? 'border-indigo-600 bg-indigo-600' : 'border-slate-300'
                  }`}
                >
                  {showMinor && (
                    <svg viewBox="0 0 12 12" className="h-2 w-2 text-white" fill="none" stroke="currentColor" strokeWidth={3}>
                      <polyline points="2,6 5,9 10,3" />
                    </svg>
                  )}
                </span>
                Show minor streams
              </button>
            </div>
          </div>
        )}

        {/* NET MARGIN box at bottom */}
        {activeResult && (
          <div className="mt-auto border-t border-slate-200 px-3 py-3">
            <div className="rounded-md bg-slate-50 px-3 py-2 text-center">
              <div className="text-[9px] uppercase tracking-widest text-slate-400">
                Net Margin
              </div>
              <div className={`text-lg font-bold tabular-nums ${isStale ? 'text-slate-400' : 'text-emerald-600'}`}>
                ${(margin / 1_000_000).toFixed(2)}M
                <span className="text-[9px] font-normal text-slate-400">/d</span>
              </div>
            </div>
          </div>
        )}

        <div className="border-t border-slate-200 px-3 py-2 text-[10px] text-slate-400">
          v0.3.0
        </div>
      </aside>

      {/* ====== MAIN CONTENT ====== */}
      <main className="ml-[195px] mt-[46px] flex flex-1 flex-col overflow-hidden">
        {page === 'flowsheet' && view === 'full' && (
          <div className="flex flex-1 flex-col min-h-0">
            <FlowsheetView
              isOptimizing={isOptimizing}
              error={error}
              hasResult={activeResult != null}
              onNodeClick={handleNodeClick}
            />
          </div>
        )}

        {page === 'flowsheet' && view === 'grouped' && activeGrp && (
          <div className="flex-1 overflow-auto">
            <GroupedView presetMode={presetMode} activeGrp={activeGrp} />
          </div>
        )}

        {page === 'flowsheet' && view === 'grouped' && !activeGrp && (
          <div className="flex flex-1 items-center justify-center text-sm text-slate-500">
            Select a group from the sidebar.
          </div>
        )}

        {page === 'impact' && (
          <div className="flex-1 overflow-auto">
            <ImpactPanel />
          </div>
        )}

        {page === 'trace' && (
          <div className="flex-1 overflow-auto">
            <TracePanel />
          </div>
        )}

        {page === 'scenarios' && (
          <div className="flex-1 overflow-auto p-4">
            <ScenariosView />
          </div>
        )}

        {page === 'oracle' && (
          <div className="flex-1 overflow-auto p-4">
            <OraclePlaceholder />
          </div>
        )}
      </main>

      {/* ====== Inspector drawer ====== */}
      {inspectUid && page === 'flowsheet' && (
        <InspectorDrawer
          uid={inspectUid}
          onClose={() => {
            setInspectUid(null)
            useRefineryStore.getState().setHighlightedNode(null)
          }}
        />
      )}
    </div>
  )
}

/* =========================================================================
 * Sub-views
 * ========================================================================= */

function FlowsheetView({
  isOptimizing,
  error,
  hasResult,
  onNodeClick,
}: {
  isOptimizing: boolean
  error: string | null
  hasResult: boolean
  onNodeClick: (id: string | null) => void
}) {
  const activeResult = useRefineryStore((s) => s.activeResult)
  const showFull = useRefineryStore((s) => s.showFullDiagram)
  const showH2 = useRefineryStore((s) => s.showH2Network)
  const showUtilitiesLane = useRefineryStore((s) => s.showUtilities)
  const highlightedNodeId = useRefineryStore((s) => s.highlightedNodeId)

  if (error) {
    return (
      <div className="flex flex-1 items-center justify-center">
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
      <div className="flex flex-1 items-center justify-center">
        <div className="text-center">
          <Loader2 className="mx-auto h-10 w-10 animate-spin text-indigo-600" />
          <p className="mt-3 text-sm text-slate-600">
            Solving the refinery NLP...
          </p>
        </div>
      </div>
    )
  }

  if (!activeResult) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-slate-500">
        No result yet.
      </div>
    )
  }

  return (
    <div className="flex-1 min-h-0 overflow-hidden">
      <RefineryFlowsheet
        result={activeResult}
        showFullDiagram={showFull}
        showH2Network={showH2}
        showUtilities={showUtilitiesLane}
        highlightedNodeId={highlightedNodeId}
        onNodeClick={onNodeClick}
      />
    </div>
  )
}

function ScenariosView() {
  return (
    <div className="grid h-full grid-cols-2 gap-4">
      <div className="overflow-auto rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <ScenarioTree />
      </div>
      <div className="overflow-auto rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <ScenarioComparison />
      </div>
    </div>
  )
}

function OraclePlaceholder() {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-10 text-center shadow-sm">
      <h2 className="text-2xl font-semibold text-slate-900">
        Oracle Analysis
      </h2>
      <p className="mt-2 text-sm text-slate-500">
        Compare actual operations against the optimal plan.
      </p>
      <p className="mt-6 inline-block rounded-md bg-slate-100 px-3 py-1 text-xs text-slate-500">
        Coming soon
      </p>
    </div>
  )
}

export default App
