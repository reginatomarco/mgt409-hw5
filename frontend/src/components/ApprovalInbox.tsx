import { useState } from 'react'
import { metaFor } from '../agents'
import { money } from '../format'
import type { Decision, PaymentRequest } from '../types'

interface Props {
  requests: PaymentRequest[]
  balance: number
  operator: string
  advice: Record<number, Decision>
  onApprove: (id: number) => Promise<void>
  onReject: (id: number, reason: string) => Promise<void>
  onNeedName: () => void
}

function Card({ r, balance, operator, advice, onApprove, onReject, onNeedName }: { r: PaymentRequest } & Omit<Props, 'requests'>) {
  const [armed, setArmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const short = r.amount > balance
  const tip = advice[r.id]
  const what = r.kind === 'rent' ? 'Rent' : r.is_purchase ? 'Purchase order' : 'Invoice'
  const blockedBy = r.pay_first ?? []

  const guard = (fn: () => Promise<void>) => async () => {
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
    <article className={`approval ${short ? 'is-short' : ''}`}>
      <div className="approval-top">
        <div>
          <div className="approval-title">{what} · {r.payee}</div>
          <div className="approval-sub muted">Leaves {money(balance - r.amount)}</div>
        </div>
        <span className="approval-amt">{money(r.amount, true)}</span>
      </div>

      {blockedBy.length > 0 && (
        <div className="pay-first">⚠ Approve invoice {blockedBy.join(', ')} first, then this order can go out.</div>
      )}

      {tip && (
        <div className={`boss-tip rec-${tip.recommend}`}>
          Boss: <b>{tip.recommend === 'yes' ? '✔ approve' : '✕ reject'}</b> · {tip.why}
        </div>
      )}

      <div className="approval-actions">
        <button
          className={`btn ${armed ? 'btn-confirm' : 'btn-approve'}`}
          disabled={busy || short}
          title={short ? 'Not enough cash in checking' : undefined}
          onClick={armed ? guard(() => onApprove(r.id)) : () => (operator.trim() ? setArmed(true) : onNeedName())}
        >
          {short ? '⚠ Not enough cash' : armed ? `Confirm ${money(r.amount, true)}` : '✔ Approve'}
        </button>
        <button
          className="btn btn-ghost"
          disabled={busy}
          onClick={guard(() => onReject(r.id, tip?.recommend === 'no' ? `Boss advised no: ${tip.why}` : 'Rejected on the desk board.'))}
        >
          ✕ Reject
        </button>
      </div>

      <details className="approval-more">
        <summary>Details</summary>
        <p>{r.for}</p>
        <p>{r.reason}</p>
        <p className="muted">Requested by {metaFor(r.requested_by).label} · due {r.due_date} · req #{r.id}</p>
      </details>
    </article>
  )
}

export function ApprovalInbox(props: Props) {
  const { requests } = props
  return (
    <section className="panel inbox" aria-label="Approvals">
      <div className="panel-head">
        <h2>
          Your call {requests.length > 0 && <span className="count">{requests.length}</span>}
        </h2>
      </div>
      {requests.length === 0 ? (
        <div className="empty">Nothing to approve.</div>
      ) : (
        <div className="approval-list">
          {requests.map((r) => (
            <Card key={r.id} r={r} {...props} />
          ))}
        </div>
      )}
    </section>
  )
}
