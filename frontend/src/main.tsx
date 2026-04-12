import { Component, StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

class GlobalErrorBoundary extends Component<
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
        <div style={{ padding: 40, fontFamily: 'system-ui', maxWidth: 600, margin: '80px auto' }}>
          <h1 style={{ color: '#be123c', fontSize: 20 }}>Something went wrong</h1>
          <pre style={{ background: '#fff1f2', padding: 16, borderRadius: 8, fontSize: 12, overflow: 'auto', marginTop: 12 }}>
            {this.state.error.message}
          </pre>
          <pre style={{ background: '#f8fafc', padding: 16, borderRadius: 8, fontSize: 10, overflow: 'auto', marginTop: 8, color: '#64748b' }}>
            {this.state.error.stack}
          </pre>
          <button
            onClick={() => { this.setState({ error: null }); window.location.reload() }}
            style={{ marginTop: 16, padding: '8px 16px', background: '#6366f1', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13 }}
          >
            Reload App
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <GlobalErrorBoundary>
      <App />
    </GlobalErrorBoundary>
  </StrictMode>,
)
