import RunForm from './components/RunForm'
import LiveAgentView from './components/LiveAgentView'
import ReportView from './components/ReportView'
import { useRuns } from './hooks/useRuns'

export default function App() {
  const { runs, loading, error, startRun, cancelRun, clearHistory } = useRuns()

  const inProgress = runs.filter(r => r.status === 'pending' || r.status === 'running')
  const finished = runs.filter(r => ['completed', 'failed', 'cancelled'].includes(r.status))

  const handleClearHistory = () => {
    if (window.confirm('Clear all past runs? This cannot be undone.')) {
      clearHistory()
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <header className="mb-8">
        <h1 className="text-2xl font-extrabold text-accent">🕵️ Shadow QA</h1>
        <p className="text-muted mt-1">
          Autonomous visual QA · Gemma 4 on AMD MI300X · Fireworks AI reports
        </p>
      </header>

      <RunForm onSubmit={startRun} loading={loading} error={error} />

      {inProgress.map(run => (
        <LiveAgentView key={run.id} run={run} onCancel={cancelRun} />
      ))}

      {finished.length > 0 && (
        <>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold">Reports ({finished.length})</h2>
            <button
              onClick={handleClearHistory}
              className="px-3 py-1.5 rounded-md text-xs font-bold text-muted border border-border hover:text-danger hover:border-danger transition-colors"
            >
              Clear History
            </button>
          </div>
          {finished.map(run => (
            <ReportView key={run.id} run={run} />
          ))}
        </>
      )}

      {runs.length === 0 && <p className="text-muted">No runs yet. Start one above.</p>}
    </div>
  )
}
