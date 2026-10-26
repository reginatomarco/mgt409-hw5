import { useState } from 'react'
import { TICKET_KIND, TICKET_STATUS } from '../format'
import type { RunInfo, Ticket } from '../types'

interface Props {
  tickets: Ticket[]
  selected: number | null
  onSelect: (id: number) => void
  activeRun: RunInfo | null
  runCounts: Record<number, number>
  onDeploy: (id: number) => Promise<void>
  onResolve: (id: number) => Promise<void>
}

export function TicketQueue({ tickets, selected, onSelect, activeRun, runCounts, onDeploy, onResolve }: Props) {
  const [pending, setPending] = useState<number | null>(null)
  const open = tickets.filter((t) => t.state === 'open').length

  return (
    <section className="panel queue" aria-label="Ticket queue">
      <div className="panel-head">
        <h2>Queue</h2>
        <span className="muted">{open} open · {tickets.length - open} resolved</span>
      </div>

      <div className="queue-list" role="listbox" aria-label="Tickets">
        {tickets.map((t, i) => {
          const status = TICKET_STATUS[t.status] ?? TICKET_STATUS.open
          const kind = TICKET_KIND[t.type] ?? { label: t.type, icon: '•' }
          const isSel = t.id === selected
          const isLive = activeRun?.ticket_id === t.id
          const runs = runCounts[t.id] ?? 0
          return (
            <div
              key={t.id}
              role="option"
              aria-selected={isSel}
              tabIndex={0}
              className={`ticket ${isSel ? 'is-selected' : ''} ${isLive ? 'is-live' : ''} ${t.state === 'resolved' ? 'is-resolved' : ''}`}
              onClick={() => onSelect(t.id)}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onSelect(t.id)}
            >
              <div className="ticket-top">
                <span className="ticket-id mono">#{t.id}</span>
                <span className={`status status-${status.tone}`}>
                  <span aria-hidden>{status.icon}</span> {status.label}
                </span>
              </div>
              <div className="ticket-subject">
                <span aria-hidden>{kind.icon}</span> {t.subject}
              </div>
              <div className="ticket-meta">
                {t.requester} · {kind.label}
                <span className="kbd" aria-hidden>{i + 1}</span>
              </div>
              {t.state === 'resolved' && <div className="stamp" aria-hidden>RESOLVED</div>}

              {isSel && t.state !== 'resolved' && (
                <div className="ticket-actions" onClick={(e) => e.stopPropagation()}>
                  <button
                    className="btn btn-primary"
                    disabled={!!activeRun || pending !== null}
                    title={activeRun ? `Team is busy on #${activeRun.ticket_id}` : 'Runs gpt-6-luna (paid)'}
                    onClick={async () => {
                      setPending(t.id)
                      try {
                        await onDeploy(t.id)
                      } finally {
                        setPending(null)
                      }
                    }}
                  >
                    {isLive ? 'Team working…' : runs ? '▶ Run follow-up' : '▶ Deploy team'}
                  </button>
                  <button
                    className="btn btn-ghost"
                    disabled={!!activeRun}
                    onClick={() => onResolve(t.id)}
                  >
                    ✔ Mark resolved
                  </button>
                  <div className="hint">
                    {runs ? `${runs} run${runs > 1 ? 's' : ''} so far · ` : ''}uses gpt-6-luna (paid)
                  </div>
                </div>
              )}
            </div>
          )
        })}
        {tickets.length === 0 && <div className="empty">No tickets yet. Is the API running?</div>}
      </div>
    </section>
  )
}
