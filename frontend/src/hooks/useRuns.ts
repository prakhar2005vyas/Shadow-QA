import { useCallback, useEffect, useState } from 'react'
import type { Run } from '../types'
import { API_BASE as API } from '../apiBase'

export function useRuns() {
  const [runs, setRuns] = useState<Run[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchRuns = useCallback(async () => {
    try {
      const res = await fetch(`${API}/runs`)
      if (res.ok) setRuns(await res.json())
    } catch {
      // silent — backend may not be ready yet
    }
  }, [])

  useEffect(() => {
    fetchRuns()
  }, [fetchRuns])

  const startRun = useCallback(async (targetUrl: string) => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API}/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_url: targetUrl }),
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
          setRuns(prev => prev.map(x => (x.id === updated.id ? updated : x)))
          if (updated.status === 'completed' || updated.status === 'failed') {
            clearInterval(intervalId)
          }
        }
      }, 3000)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  return { runs, loading, error, startRun }
}
