import { useEffect, useState } from 'react'
import type { AgentStepEvent } from '../types'

const API = '/api'

/**
 * Polls GET /runs/{runId}/steps for the live agent view. Polls on an interval
 * while `active` is true (run still pending/running), and just fetches once
 * otherwise (e.g. to show the final step trail after completion).
 */
export function useSteps(runId: number | null, active: boolean) {
  const [steps, setSteps] = useState<AgentStepEvent[]>([])

  useEffect(() => {
    if (runId === null) {
      setSteps([])
      return
    }

    let cancelled = false
    const fetchSteps = async () => {
      try {
        const res = await fetch(`${API}/runs/${runId}/steps`)
        if (res.ok && !cancelled) setSteps(await res.json())
      } catch {
        // silent — transient network hiccup, next poll will retry
      }
    }

    fetchSteps()
    const intervalId = active ? window.setInterval(fetchSteps, 2000) : null

    return () => {
      cancelled = true
      if (intervalId !== null) clearInterval(intervalId)
    }
  }, [runId, active])

  return steps
}
