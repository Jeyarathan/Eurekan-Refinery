/**
 * Typed client for the Eurekan FastAPI backend.
 *
 * Every function returns a typed response and throws on a non-2xx status.
 * The base URL is `/api`, which is proxied to `http://localhost:8000` by Vite
 * during development.
 */

import type {
  BranchScenarioRequest,
  ConfigCompleteness,
  ConfigSummary,
  ConstraintDiagnostic,
  CrudeDisposition,
  CrudeSummary,
  MaterialFlowGraph,
  OracleRequest,
  OracleResult,
  PlanningResult,
  ProductSummary,
  QuickOptimizeRequest,
  ScenarioComparison,
  ScenarioSummary,
} from '../types'

const BASE = '/api'

class ApiError extends Error {
  readonly status: number
  readonly statusText: string
  readonly url: string
  readonly body: string

  constructor(status: number, statusText: string, url: string, body: string) {
    super(`API ${status} ${statusText} on ${url}: ${body.slice(0, 200)}`)
    this.name = 'ApiError'
    this.status = status
    this.statusText = statusText
    this.url = url
    this.body = body
  }
}

async function request<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<T> {
  const url = path.startsWith('/') ? path : `${BASE}/${path}`
  const init: RequestInit = {
    method,
    headers:
      body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }
  const response = await fetch(url, init)
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new ApiError(response.status, response.statusText, url, text)
  }
  // Allow empty bodies (204 etc.)
  const text = await response.text()
  return text ? (JSON.parse(text) as T) : (undefined as T)
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export interface HealthResponse {
  status: string
  crudes_loaded: number
  is_stale: boolean
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('GET', '/health')
}

// ---------------------------------------------------------------------------
// Optimize
// ---------------------------------------------------------------------------

export function optimize(body: {
  mode: 'optimize' | 'simulate' | 'hybrid'
  periods: Array<{ period_id: number; duration_hours: number; product_prices?: Record<string, number>; crude_prices?: Record<string, number> }>
  fixed_variables?: Record<string, number>
  scenario_name?: string
}): Promise<PlanningResult> {
  return request<PlanningResult>('POST', `${BASE}/optimize`, body)
}

export function quickOptimize(
  params?: QuickOptimizeRequest,
): Promise<PlanningResult> {
  return request<PlanningResult>(
    'POST',
    `${BASE}/optimize/quick`,
    params ?? {},
  )
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

export function getConfig(): Promise<ConfigSummary> {
  return request<ConfigSummary>('GET', `${BASE}/config`)
}

export function getCrudes(): Promise<CrudeSummary[]> {
  return request<CrudeSummary[]>('GET', `${BASE}/config/crudes`)
}

export function getProducts(): Promise<ProductSummary[]> {
  return request<ProductSummary[]>('GET', `${BASE}/config/products`)
}

export function getCompleteness(): Promise<ConfigCompleteness> {
  return request<ConfigCompleteness>('GET', `${BASE}/config/completeness`)
}

export function updateCrudePrice(
  crudeId: string,
  price: number,
): Promise<{ crude_id: string; price: number; is_stale: boolean }> {
  return request('PUT', `${BASE}/config/crude/${crudeId}/price`, { price })
}

export function updateProductPrice(
  productId: string,
  price: number,
): Promise<{ product_id: string; price: number; is_stale: boolean }> {
  return request('PUT', `${BASE}/config/product/${productId}/price`, { price })
}

// ---------------------------------------------------------------------------
// Scenarios
// ---------------------------------------------------------------------------

export function getScenarios(): Promise<ScenarioSummary[]> {
  return request<ScenarioSummary[]>('GET', `${BASE}/scenarios`)
}

export function getScenario(scenarioId: string): Promise<PlanningResult> {
  return request<PlanningResult>('GET', `${BASE}/scenarios/${scenarioId}`)
}

export function branchScenario(
  scenarioId: string,
  body: BranchScenarioRequest,
): Promise<PlanningResult> {
  return request<PlanningResult>(
    'POST',
    `${BASE}/scenarios/${scenarioId}/branch`,
    body,
  )
}

export function compareScenarios(
  baseId: string,
  comparisonId: string,
): Promise<ScenarioComparison> {
  const url = `${BASE}/scenarios/compare?base=${encodeURIComponent(
    baseId,
  )}&comparison=${encodeURIComponent(comparisonId)}`
  return request<ScenarioComparison>('GET', url)
}

export function getFlowGraph(scenarioId: string): Promise<MaterialFlowGraph> {
  return request<MaterialFlowGraph>(
    'GET',
    `${BASE}/scenarios/${scenarioId}/flow`,
  )
}

export function getDiagnostics(
  scenarioId: string,
): Promise<ConstraintDiagnostic[]> {
  return request<ConstraintDiagnostic[]>(
    'GET',
    `${BASE}/scenarios/${scenarioId}/diagnostics`,
  )
}

export function getCrudeDisposition(
  scenarioId: string,
  crudeId: string,
): Promise<CrudeDisposition> {
  return request<CrudeDisposition>(
    'GET',
    `${BASE}/scenarios/${scenarioId}/crude-disposition/${crudeId}`,
  )
}

// ---------------------------------------------------------------------------
// Oracle
// ---------------------------------------------------------------------------

export function runOracle(body: OracleRequest): Promise<OracleResult> {
  return request<OracleResult>('POST', `${BASE}/oracle`, body)
}

export { ApiError }
