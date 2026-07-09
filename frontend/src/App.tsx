import { useState, useEffect } from 'react'

const API = '/api'

interface Finding {
  id: number
  step_num: number
  description: string
  severity: string
  category: string
  has_screenshot: boolean
  report_title?: string
  report_summary?: string
}

interface Run {
  id: number
  target_url: string
  status: string
  total_steps: number
  findings: Finding[]
  error_msg?: string
}

const SEVERITY_COLOR: Record<string, string> = {
  critical: '#ff4444',
  high: '#ff8c00',
  medium: '#ffd700',
  low: '#00cc88',
}

function SeverityBadge({ sev }: { sev: string }) {
  return (
    <span style={{
      background: SEVERITY_COLOR[sev] || '#666',
      color: '#000',
      padding: '2px 8px',
      borderRadius: 4,
      fontSize: '0.75rem',
      fontWeight: 700,
      textTransform: 'uppercase',
    }}>
      {sev}
    </span>
  )
}

export default function App() {
  const [url, setUrl] = useState('http://fixture-app:80')
  const [runs, setRuns] = useState<Run[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [polling, setPolling] = useState<number | null>(null)

  useEffect(() => {
    fetchRuns()
  }, [])

  async function fetchRuns() {
    try {
      const res = await fetch(`${API}/runs`)
      if (res.ok) setRuns(await res.json())
    } catch {
      // silent — backend may not be ready yet
    }
  }

  async function startRun() {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API}/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_url: url }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Failed to start run')
      }
      const run: Run = await res.json()
      setRuns(prev => [run, ...prev])

      // Poll until done
      const intervalId = window.setInterval(async () => {
        const r = await fetch(`${API}/runs/${run.id}`)
        if (r.ok) {
          const updated: Run = await r.json()
          setRuns(prev => prev.map(x => x.id === updated.id ? updated : x))
          if (updated.status === 'completed' || updated.status === 'failed') {
            clearInterval(intervalId)
            setPolling(null)
          }
        }
      }, 3000)
      setPolling(intervalId)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '2rem 1rem' }}>
      {/* Header */}
      <header style={{ marginBottom: '2rem' }}>
        <h1 style={{ fontSize: '1.8rem', fontWeight: 800, color: '#e94560' }}>
          🕵️ Shadow QA
        </h1>
        <p style={{ color: '#8b949e', marginTop: '0.3rem' }}>
          Autonomous visual QA · Gemma 4 on AMD MI300X · Fireworks AI reports
        </p>
      </header>

      {/* Run form */}
      <div style={{
        background: '#161b22',
        borderRadius: 10,
        padding: '1.5rem',
        marginBottom: '2rem',
        border: '1px solid #30363d',
      }}>
        <h2 style={{ marginBottom: '1rem', fontSize: '1.1rem' }}>Start a New Run</h2>
        <div style={{ display: 'flex', gap: '0.8rem', flexWrap: 'wrap' }}>
          <input
            id="target-url-input"
            type="url"
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://target-app.example.com"
            style={{
              flex: 1,
              minWidth: 280,
              padding: '0.6rem 1rem',
              background: '#0d1117',
              border: '1px solid #30363d',
              borderRadius: 6,
              color: '#e6edf3',
              fontSize: '0.95rem',
            }}
          />
          <button
            id="start-run-btn"
            onClick={startRun}
            disabled={loading || !url}
            style={{
              padding: '0.6rem 1.5rem',
              background: loading ? '#444' : '#e94560',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              fontWeight: 700,
              cursor: loading ? 'not-allowed' : 'pointer',
              fontSize: '0.95rem',
            }}
          >
            {loading ? 'Starting…' : 'Run Agent'}
          </button>
        </div>
        {error && (
          <p style={{ color: '#ff4444', marginTop: '0.8rem', fontSize: '0.9rem' }}>
            ⚠ {error}
          </p>
        )}
        {polling !== null && (
          <p style={{ color: '#8b949e', marginTop: '0.8rem', fontSize: '0.85rem' }}>
            ⏳ Agent running… polling for results…
          </p>
        )}
      </div>

      {/* Runs list */}
      <h2 style={{ marginBottom: '1rem', fontSize: '1.1rem' }}>
        Runs ({runs.length})
      </h2>
      {runs.length === 0 && (
        <p style={{ color: '#8b949e' }}>No runs yet. Start one above.</p>
      )}
      {runs.map(run => (
        <div key={run.id} style={{
          background: '#161b22',
          border: '1px solid #30363d',
          borderRadius: 10,
          padding: '1.2rem',
          marginBottom: '1rem',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
            <div>
              <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>Run #{run.id}</span>
              <span style={{
                marginLeft: '0.8rem',
                padding: '2px 8px',
                borderRadius: 4,
                fontSize: '0.75rem',
                fontWeight: 700,
                background: run.status === 'completed' ? '#1a4731' : run.status === 'failed' ? '#4d1a1a' : '#1a2d4d',
                color: run.status === 'completed' ? '#3fb950' : run.status === 'failed' ? '#ff4444' : '#79c0ff',
              }}>
                {run.status.toUpperCase()}
              </span>
            </div>
            <span style={{ color: '#8b949e', fontSize: '0.85rem' }}>{run.total_steps} steps</span>
          </div>
          <p style={{ color: '#8b949e', fontSize: '0.85rem', marginTop: '0.3rem', wordBreak: 'break-all' }}>
            {run.target_url}
          </p>
          {run.error_msg && (
            <p style={{ color: '#ff4444', fontSize: '0.85rem', marginTop: '0.5rem' }}>
              Error: {run.error_msg}
            </p>
          )}

          {run.findings.length > 0 && (
            <div style={{ marginTop: '1rem' }}>
              <p style={{ fontSize: '0.85rem', color: '#8b949e', marginBottom: '0.5rem' }}>
                {run.findings.length} finding{run.findings.length !== 1 ? 's' : ''}
              </p>
              {run.findings.map(f => (
                <div key={f.id} style={{
                  background: '#0d1117',
                  border: '1px solid #21262d',
                  borderRadius: 6,
                  padding: '0.8rem',
                  marginBottom: '0.5rem',
                }}>
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap', marginBottom: '0.4rem' }}>
                    <SeverityBadge sev={f.severity} />
                    <span style={{ fontSize: '0.8rem', color: '#8b949e' }}>{f.category}</span>
                    <span style={{ fontSize: '0.8rem', color: '#8b949e' }}>step {f.step_num}</span>
                  </div>
                  <p style={{ fontSize: '0.9rem', lineHeight: 1.5 }}>{f.description}</p>
                  {f.report_title && (
                    <p style={{ fontSize: '0.8rem', color: '#8b949e', marginTop: '0.4rem' }}>
                      📄 {f.report_title}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
