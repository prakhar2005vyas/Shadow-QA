export type RunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export type Severity = 'low' | 'medium' | 'high' | 'critical'

export type Category =
  | 'broken_interaction'
  | 'visual_layout'
  | 'accessibility'
  | 'error_state'
  | 'dead_link'
  | 'other'

export interface Finding {
  id: number
  step_num: number
  description: string
  severity: Severity
  category: Category
  has_screenshot: boolean
  report_title?: string
  report_summary?: string
  report_raw?: string
}

export interface Run {
  id: number
  target_url: string
  status: RunStatus
  total_steps: number
  findings: Finding[]
  error_msg?: string
}

/** A single perceive-decide-act step from the agent loop, as returned by GET /runs/{id}/steps. */
export interface AgentStepEvent {
  step_num: number
  observation: string
  is_anomaly: boolean
  action_type: string
  action_selector?: string | null
  action_reason: string
  has_screenshot: boolean
}
