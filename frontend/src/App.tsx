import RunForm from './components/RunForm'
import LiveAgentView from './components/LiveAgentView'
import ReportView from './components/ReportView'
import { useRuns } from './hooks/useRuns'

export default function App() {
  const { runs, loading, error, startRun } = useRuns()

  const inProgress = runs.filter(r => r.status === 'pending' || r.status === 'running')
  const finished = runs.filter(r => r.status === 'completed' || r.status === 'failed')

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
        <LiveAgentView key={run.id} run={run} />
      ))}

      {finished.length > 0 && (
        <>
          <h2 className="text-lg font-semibold mb-3">Reports ({finished.length})</h2>
          {finished.map(run => (
            <ReportView key={run.id} run={run} />
          ))}
        </>
      )}

      {runs.length === 0 && <p className="text-muted">No runs yet. Start one above.</p>}
    </div>
  )
}
