import { useState } from 'react'
import type { Finding, Run } from '../types'
import SeverityBadge from './SeverityBadge'
import { API_BASE } from '../apiBase'

const STATUS_CLASSES: Record<string, string> = {
  pending: 'bg-[#1a2d4d] text-info',
  running: 'bg-[#1a2d4d] text-info',
  completed: 'bg-[#1a4731] text-success',
  failed: 'bg-[#4d1a1a] text-danger',
}

function FindingCard({ runId, finding }: { runId: number; finding: Finding }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="bg-bg border border-border-muted rounded-md p-3 mb-2">
      <div className="flex items-center gap-2 flex-wrap mb-2">
        <SeverityBadge severity={finding.severity} />
        <span className="text-xs text-muted">{finding.category}</span>
        <span className="text-xs text-muted">step {finding.step_num}</span>
      </div>

      {finding.has_screenshot && (
        <img
          src={`${API_BASE}/runs/${runId}/findings/${finding.id}/screenshot`}
          alt={`Screenshot for finding ${finding.id}`}
          className="rounded-md border border-border-muted mb-2 max-h-56 w-full object-contain bg-surface"
        />
      )}

      <p className="text-sm leading-relaxed">{finding.description}</p>

      {finding.report_title && (
        <button
          onClick={() => setExpanded(v => !v)}
          className="text-xs text-muted mt-2 hover:text-text transition-colors"
        >
          📄 {finding.report_title} {expanded ? '▲ hide report' : '▼ view full report'}
        </button>
      )}

      {expanded && finding.report_raw && (
        <pre className="mt-2 text-xs whitespace-pre-wrap bg-surface border border-border-muted rounded-md p-3 leading-relaxed">
          {finding.report_raw}
        </pre>
      )}
    </div>
  )
}

export default function ReportView({ run }: { run: Run }) {
  return (
    <div className="bg-surface border border-border rounded-xl p-6 mb-4">
      <div className="flex justify-between flex-wrap gap-2 mb-1">
        <div>
          <span className="font-bold text-sm">Run #{run.id}</span>
          <span
            className={`${STATUS_CLASSES[run.status]} ml-3 px-2 py-0.5 rounded text-xs font-bold uppercase`}
          >
            {run.status}
          </span>
        </div>
        <span className="text-muted text-sm">{run.total_steps} steps</span>
      </div>
      <p className="text-muted text-sm break-all mt-1">{run.target_url}</p>

      {run.error_msg && <p className="text-danger text-sm mt-2">Error: {run.error_msg}</p>}

      {run.findings.length > 0 ? (
        <div className="mt-4">
          <p className="text-sm text-muted mb-2">
            {run.findings.length} finding{run.findings.length !== 1 ? 's' : ''}
          </p>
          {run.findings.map(f => (
            <FindingCard key={f.id} runId={run.id} finding={f} />
          ))}
        </div>
      ) : (
        <p className="text-muted text-sm mt-4">No findings recorded for this run.</p>
      )}
    </div>
  )
}
