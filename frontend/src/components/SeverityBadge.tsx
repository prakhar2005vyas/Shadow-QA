import type { Severity } from '../types'

const SEVERITY_CLASSES: Record<Severity, string> = {
  critical: 'bg-severity-critical',
  high: 'bg-severity-high',
  medium: 'bg-severity-medium',
  low: 'bg-severity-low',
}

export default function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span
      className={`${SEVERITY_CLASSES[severity] ?? 'bg-muted'} px-2 py-0.5 rounded text-xs font-bold uppercase text-black`}
    >
      {severity}
    </span>
  )
}
