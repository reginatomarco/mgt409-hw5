// Polls the backend and keeps the whole desk in one place.
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { AgentEvent, Cash, PaymentRequest, RunInfo, Ticket } from './types'

const FAST_MS = 1500 // while a run is live
const SLOW_MS = 4000

export interface Desk {
  online: boolean
  tickets: Ticket[]
  runs: RunInfo[]
  activeRun: RunInfo | null
  events: AgentEvent[]
  payments: PaymentRequest[]
  cash: Cash | null
  refresh: () => Promise<void>
}

export function useDesk(): Desk {
  const [online, setOnline] = useState(true)
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [runs, setRuns] = useState<RunInfo[]>([])
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [payments, setPayments] = useState<PaymentRequest[]>([])
  const [cash, setCash] = useState<Cash | null>(null)
  const lastEventId = useRef(-1)
  const busy = useRef(false)

  const refresh = useCallback(async () => {
    if (busy.current) return
    busy.current = true
    try {
      const [t, r, ev, p, c] = await Promise.all([
        api.tickets(),
        api.runs(),
        api.events(lastEventId.current),
        api.payments(),
        api.cash(),
      ])
      setTickets(t)
      setRuns(r)
      if (ev.length) {
        lastEventId.current = ev[ev.length - 1].id
        setEvents((prev) => [...prev, ...ev])
      }
      setPayments(p.requests)
      setCash(c)
      setOnline(true)
    } catch {
      setOnline(false)
    } finally {
      busy.current = false
    }
  }, [])

  const activeRun = runs.find((r) => r.status === 'running') ?? null

  useEffect(() => {
    refresh()
    const id = window.setInterval(refresh, activeRun ? FAST_MS : SLOW_MS)
    return () => window.clearInterval(id)
  }, [refresh, activeRun?.run_id])

  return { online, tickets, runs, activeRun, events, payments, cash, refresh }
}
