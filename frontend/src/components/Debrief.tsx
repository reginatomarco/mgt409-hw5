import { useState } from 'react'
import { AGENTS } from '../agents'
import { TICKET_STATUS, money } from '../format'
import type { AgentEvent, Decision, PaymentRequest, Ticket } from '../types'
import { Avatar } from './AgentFloor'

interface Props {
  ticket: Ticket | null
  ticketEvents: AgentEvent[]
  pending: PaymentRequest[]
  balance: number
  operator: string
  onNeedName: () => void
  onApprove: (id: number) => Promise<void>
  onReject: (id: number, reason: string) => Promise<void>
  onDecide: (ticketId: number, ask: string, answer: 'yes' | 'no') => Promise<void>
}

/** One Boss question with real buttons. Payments go through approve/reject; others are saved as owner decisions. */
function DecisionRow({ d, ticketId, answered, pending, balance, operator, onNeedName, onApprove, onReject, onDecide }: {
  d: Decision
  ticketId: number
  answered: 'yes' | 'no' | undefined
} & Omit<Props, 'ticket' | 'ticketEvents'>) {
  const [armed, setArmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const isPayment = d.request_id != null
  const req = isPayment ? pending.find((p) => p.id === d.request_id) : undefined
  const short = !!req && req.amount > balance
  const done = isPayment ? !req : !!answered

  const run = (fn: () => Promise<void>) => async () => {
    if (!operator.trim()) return onNeedName()
    setBusy(true)
    try {
      await fn()
    } finally {
      setBusy(false)
      setArmed(false)
    }
  }

  return (
    <li className={`decision ${done ? 'is-done' : ''}`}>
      <div className="decision-text">
        <div className="ask">
          {d.ask} {d.amount != null && <b>{money(d.amount, true)}</b>}
        </div>
        <div className="why muted">
          <span className={`tip rec-${d.recommend}`}>Boss suggests {d.recommend === 'yes' ? 'yes' : 'no'}</span> · {d.why}
        </div>
      </div>
      <div className="decision-actions">
        {done ? (
          <span className="decided">{isPayment ? '✔ Decided' : answered === 'yes' ? '✔ You said yes' : '✕ You said no'}</span>
        ) : isPayment ? (
          <>
            <button
              className={`btn btn-sm ${armed ? 'btn-confirm' : 'btn-approve'}`}
              disabled={busy || short}
              title={short ? 'Not enough cash in checking' : undefined}
              onClick={armed ? run(() => onApprove(req!.id)) : () => (operator.trim() ? setArmed(true) : onNeedName())}
            >
              {short ? '⚠ No cash' : armed ? 'Confirm' : 'Approve'}
            </button>
            <button className="btn btn-sm btn-ghost" disabled={busy} onClick={run(() => onReject(req!.id, `Owner said no: ${d.ask}`))}>
              Reject
            </button>
          </>
        ) : (
          <>
            <button className="btn btn-sm btn-approve" disabled={busy} onClick={run(() => onDecide(ticketId, d.ask, 'yes'))}>
              Yes
            </button>
            <button className="btn btn-sm btn-ghost" disabled={busy} onClick={run(() => onDecide(ticketId, d.ask, 'no'))}>
              No
            </button>
          </>
        )}
      </div>
    </li>
  )
}

/** The Boss's latest word on this ticket: a headline and at most 3 yes/no calls you can click. */
export function Debrief(props: Props) {
  const { ticket, ticketEvents } = props
  const latest: Record<string, AgentEvent> = {}
  const answered: Record<string, 'yes' | 'no'> = {}
  for (const e of ticketEvents) {
    if (e.event === 'run_end') latest[e.agent] = e
    if (e.event === 'owner_decision' && e.said) {
      const m = e.said.match(/^OWNER DECISION: (YES|NO) to "(.*)"$/s)
      if (m) answered[m[2]] = m[1] === 'YES' ? 'yes' : 'no'
    }
  }
  const boss = latest.boss?.output
  // Runs from before the short format have a long summary_for_human: show its first sentence only.
  const legacy = (boss as { summary_for_human?: string } | undefined)?.summary_for_human
  const headline = boss?.headline ?? (legacy ? legacy.split(/(?<=[.!?])\s/)[0] : '')
  const outcome = boss?.tickets?.find((t) => t.ticket_id === ticket?.id)
  const status = outcome ? TICKET_STATUS[outcome.status] ?? TICKET_STATUS.open : null
  const specialists = AGENTS.filter((a) => a.name !== 'boss' && latest[a.name])

  return (
    <section className="panel debrief" aria-label="Ticket debrief">
      <div className="panel-head">
        <h2>Boss says {ticket && <span className="muted mono">#{ticket.id}</span>}</h2>
        {status && (
          <span className={`status status-${status.tone}`}>
            {status.icon} {status.label}
          </span>
        )}
      </div>

      {!boss ? (
        <div className="empty">Nothing yet. The Boss's summary lands here after a run.</div>
      ) : (
        <div className="debrief-body">
          <div className="boss-note" style={{ ['--agent' as string]: AGENTS[0].color }}>
            <div className="debrief-who">
              <Avatar meta={AGENTS[0]} size={24} /> <b className="headline">{headline}</b>
            </div>
            {outcome && <p className="next">Next: {outcome.next_step}</p>}
          </div>

          {!!boss.decisions?.length && ticket && (
            <ul className="decisions">
              {boss.decisions.map((d, i) => (
                <DecisionRow key={i} d={d} ticketId={ticket.id} answered={answered[d.ask]} {...props} />
              ))}
            </ul>
          )}

          {specialists.length > 0 && (
            <details className="agent-details">
              <summary>What each agent did</summary>
              {specialists.map((a) => (
                <div key={a.name} className="agent-note" style={{ ['--agent' as string]: a.color }}>
                  <div className="debrief-who">
                    <Avatar meta={a} size={20} /> <b>{a.label}</b>
                  </div>
                  <p>{latest[a.name].output?.summary}</p>
                </div>
              ))}
            </details>
          )}
        </div>
      )}
    </section>
  )
}
