import type { Run } from '../types'
import { useSteps } from '../hooks/useSteps'
import { API_BASE } from '../apiBase'

interface LiveAgentViewProps {
  run: Run
}

const STATUS_CLASSES: Record<string, string> = {
  pending: 'bg-[#1a2d4d] text-info',
  running: 'bg-[#1a2d4d] text-info',
  completed: 'bg-[#1a4731] text-success',
  failed: 'bg-[#4d1a1a] text-danger',
}

export default function LiveAgentView({ run }: LiveAgentViewProps) {
  const active = run.status === 'pending' || run.status === 'running'
  const steps = useSteps(run.id, active)
  const latestStep = steps[steps.length - 1]

  const screenshotSrc = latestStep?.has_screenshot
    ? `${API_BASE}/runs/${run.id}/steps/${latestStep.step_num}/screenshot`
    : null

  return (
    <div className="bg-surface border border-border rounded-xl p-6 mb-8">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-4">
        <h2 className="text-lg font-semibold">Live Agent View — Run #{run.id}</h2>
        <span className={`${STATUS_CLASSES[run.status]} px-2 py-0.5 rounded text-xs font-bold uppercase`}>
          {run.status}
        </span>
      </div>
      <p className="text-muted text-sm break-all mb-4">{run.target_url}</p>

      {/* Current screenshot */}
      <div className="aspect-video bg-bg border border-border-muted rounded-lg flex items-center justify-center mb-4 overflow-hidden">
        {screenshotSrc ? (
          <img
            src={screenshotSrc}
            alt={`Screenshot at step ${latestStep.step_num}`}
            className="w-full h-full object-contain"
          />
        ) : (
          <span className="text-muted text-sm">
            {steps.length === 0
              ? 'Waiting for the first step…'
              : `Screenshot for step ${latestStep?.step_num ?? 0} not available`}
          </span>
        )}
      </div>

      <div className="flex items-center justify-between text-xs text-muted mb-2">
        <span>
          Step {latestStep?.step_num ?? 0} / {run.total_steps || '?'}
        </span>
        <span>{steps.filter(s => s.is_anomaly).length} anomalies flagged so far</span>
      </div>

      {/* Running commentary feed */}
      <div className="max-h-72 overflow-y-auto flex flex-col-reverse gap-2 border-t border-border-muted pt-3">
        {steps.length === 0 && (
          <p className="text-muted text-sm text-center py-4">No steps recorded yet.</p>
        )}
        {[...steps].reverse().map(step => (
          <div
            key={step.step_num}
            className={`bg-bg border rounded-md px-3 py-2 text-sm ${
              step.is_anomaly ? 'border-severity-high/50' : 'border-border-muted'
            }`}
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-mono text-muted">step {step.step_num}</span>
              {step.is_anomaly && (
                <span className="text-xs font-bold uppercase text-severity-high">anomaly</span>
              )}
            </div>
            <p className="leading-relaxed">{step.observation}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
