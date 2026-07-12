import { useState } from 'react'

interface RunFormProps {
  onSubmit: (targetUrl: string) => void
  loading: boolean
  error: string
}

export default function RunForm({ onSubmit, loading, error }: RunFormProps) {
  const [url, setUrl] = useState('')

  return (
    <div className="bg-surface border border-border rounded-xl p-6 mb-8">
      <h2 className="text-lg font-semibold mb-4">Start a New Run</h2>
      <div className="flex flex-wrap gap-3">
        <input
          id="target-url-input"
          type="url"
          value={url}
          onChange={e => setUrl(e.target.value)}
          placeholder="https://target-app.example.com"
          className="flex-1 min-w-[280px] bg-bg border border-border rounded-md px-4 py-2.5 text-text text-sm focus:outline-none focus:ring-2 focus:ring-accent"
        />
        <button
          id="start-run-btn"
          onClick={() => onSubmit(url)}
          disabled={loading || !url}
          className="px-6 py-2.5 rounded-md font-bold text-sm text-white bg-accent disabled:bg-border disabled:cursor-not-allowed transition-colors"
        >
          {loading ? 'Starting…' : 'Run Agent'}
        </button>
      </div>
      {error && <p className="text-danger text-sm mt-3">⚠ {error}</p>}
    </div>
  )
}
