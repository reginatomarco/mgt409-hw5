import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { agentStates } from './agents'
import { api, API_URL } from './api'
import { AgentFloor } from './components/AgentFloor'
import { ApprovalInbox } from './components/ApprovalInbox'
import { CashTile } from './components/CashTile'
import { Debrief } from './components/Debrief'
import { TicketQueue } from './components/TicketQueue'
import { TopBar } from './components/TopBar'
import { Transcript } from './components/Transcript'
import { money } from './format'
import type { Decision } from './types'
import { useDesk } from './useDesk'

interface Toast {
  id: number
  tone: 'good' | 'bad' | 'info'
  text: string
}

export default function App() {
  const desk = useDesk()
  const [selected, setSelected] = useState<number | null>(null)
  const [pickedRun, setPickedRun] = useState<string | null>(null)
  const [operator, setOperatorState] = useState(() => localStorage.getItem('cc-operator') ?? '')
  const [toasts, setToasts] = useState<Toast[]>([])
  const [nameNudge, setNameNudge] = useState(false)

  const setOperator = (v: string) => {
    setOperatorState(v)
    localStorage.setItem('cc-operator', v)
  }

  const toast = useCallback((tone: Toast['tone'], text: string) => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, tone, text }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000)
  }, [])

  // Default selection: the live ticket, else the first ticket.
  useEffect(() => {
    if (selected === null && desk.tickets.length) setSelected(desk.activeRun?.ticket_id ?? desk.tickets[0].id)
  }, [desk.tickets, desk.activeRun, selected])

  // Keyboard: 1/2/3 pick a ticket.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === 'INPUT') return
      const t = desk.tickets[Number(e.key) - 1]
      if (t) setSelected(t.id)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [desk.tickets])

  // Toast when a run finishes.
  const wasActive = useRef<string | null>(null)
  useEffect(() => {
    const now = desk.activeRun?.run_id ?? null
    if (wasActive.current && !now) {
      const done = desk.runs.find((r) => r.run_id === wasActive.current)
      if (done?.status === 'error') toast('bad', `Run on #${done.ticket_id} failed: ${done.error}`)
      else if (done) toast('good', `Team finished ticket #${done.ticket_id}. Check the debrief and approvals.`)
    }
    wasActive.current = now
  }, [desk.activeRun, desk.runs, toast])

  // The audit trail is append-only, so the board shows only what happened since the last DB reset.
  const events = useMemo(() => {
    let cut = -1
    for (const e of desk.events) if (e.event === 'db_reset') cut = e.id
    return desk.events.filter((e) => e.id > cut)
  }, [desk.events])

  const ticket = desk.tickets.find((t) => t.id === selected) ?? null
  const ticketEvents = useMemo(() => events.filter((e) => e.ticket_id === selected), [events, selected])
  const runIds = useMemo(() => [...new Set(ticketEvents.map((e) => e.run_id).filter(Boolean) as string[])], [ticketEvents])

  const runCounts = useMemo(() => {
    const seen: Record<number, Set<string>> = {}
    for (const e of events) {
      if (e.ticket_id == null || !e.run_id) continue
      ;(seen[e.ticket_id] ??= new Set()).add(e.run_id)
    }
    return Object.fromEntries(Object.entries(seen).map(([k, v]) => [Number(k), v.size]))
  }, [events])

  // Which run the transcript shows: the live one for this ticket, a picked one, or the latest.
  const liveHere = desk.activeRun?.ticket_id === selected ? desk.activeRun.run_id : null
  const runId = liveHere ?? (pickedRun && runIds.includes(pickedRun) ? pickedRun : runIds[runIds.length - 1] ?? null)
  const runEvents = useMemo(() => events.filter((e) => e.run_id === runId), [events, runId])
  const states = useMemo(() => agentStates(runEvents), [runEvents])
  const pendingTotal = desk.payments.reduce((s, p) => s + p.amount, 0)

  // The Boss's latest yes/no advice per payment request, from any ticket's run.
  const advice = useMemo(() => {
    const out: Record<number, Decision> = {}
    for (const e of events)
      if (e.event === 'run_end' && e.agent === 'boss')
        for (const d of e.output?.decisions ?? []) if (d.request_id != null) out[d.request_id] = d
    return out
  }, [events])

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn()
      toast('good', ok)
    } catch (e) {
      toast('bad', e instanceof Error ? e.message : String(e))
    } finally {
      await desk.refresh()
    }
  }

  const approve = (id: number) => {
    const r = desk.payments.find((p) => p.id === id)
    return act(() => api.approve(id, operator.trim()), `Paid ${r ? money(r.amount, true) : ''} to ${r?.payee ?? 'payee'}.`)
  }
  const reject = (id: number, reason: string) => act(() => api.reject(id, operator.trim(), reason), `Request #${id} rejected.`)

  const needName = () => {
    setNameNudge(true)
    toast('info', 'Sign in with your full name (top right) before approving anything.')
    window.setTimeout(() => setNameNudge(false), 2500)
  }

  return (
    <div className={`desk ${nameNudge ? 'nudge-name' : ''}`}>
      <TopBar
        online={desk.online}
        shopDate={desk.cash?.shop_date ?? null}
        activeRun={desk.activeRun}
        operator={operator}
        setOperator={setOperator}
        onReset={() => act(api.reset, 'Database reset to the original. Fresh start.')}
      />

      {!desk.online && (
        <div className="offline">
          Can't reach the API at <code>{API_URL}</code>. Start it from <code>backend/</code> with{' '}
          <code>uvicorn main:app --reload --port 8000</code>.
        </div>
      )}

      <main className="grid">
        <TicketQueue
          tickets={desk.tickets}
          selected={selected}
          onSelect={(id) => {
            setSelected(id)
            setPickedRun(null)
          }}
          activeRun={desk.activeRun}
          runCounts={runCounts}
          onDeploy={(id) =>
            act(async () => {
              const run = await api.runTicket(id)
              setPickedRun(run.run_id)
            }, `Team deployed on #${id}.`)
          }
          onResolve={(id) => (operator.trim() ? act(() => api.resolveTicket(id, operator.trim()), `Ticket #${id} marked resolved.`) : Promise.resolve(needName()))}
        />

        <div className="center">
          <AgentFloor states={states} live={!!liveHere} />
          <Transcript events={runEvents} runIds={runIds} runId={runId} onPickRun={setPickedRun} live={!!liveHere} />
        </div>

        <aside className="side">
          <CashTile cash={desk.cash} pendingTotal={pendingTotal} />
          <ApprovalInbox
            requests={desk.payments}
            balance={desk.cash?.balance ?? 0}
            operator={operator}
            advice={advice}
            onNeedName={needName}
            onApprove={approve}
            onReject={reject}
          />
          <Debrief
            ticket={ticket}
            ticketEvents={ticketEvents}
            pending={desk.payments}
            balance={desk.cash?.balance ?? 0}
            operator={operator}
            onNeedName={needName}
            onApprove={approve}
            onReject={reject}
            onDecide={(id, ask, answer) =>
              act(() => api.decide(id, ask, answer, operator.trim()), `Saved: you said ${answer} on #${id}. Run a follow-up to act on it.`)
            }
          />
        </aside>
      </main>

      <div className="toasts" aria-live="assertive">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.tone}`}>{t.text}</div>
        ))}
      </div>
    </div>
  )
}
