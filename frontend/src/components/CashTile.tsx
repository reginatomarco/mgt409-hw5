import { useEffect, useRef, useState } from 'react'
import { money } from '../format'
import type { Cash } from '../types'
import { useTweened } from './useTick'

interface Props {
  cash: Cash | null
  pendingTotal: number
}

export function CashTile({ cash, pendingTotal }: Props) {
  const balance = cash?.balance ?? 0
  const shown = useTweened(balance)
  const prev = useRef<number | null>(null)
  const [delta, setDelta] = useState<{ amount: number; key: number } | null>(null)

  useEffect(() => {
    if (cash === null) return
    if (prev.current !== null && cash.balance !== prev.current) {
      setDelta({ amount: cash.balance - prev.current, key: Date.now() })
    }
    prev.current = cash.balance
  }, [cash?.balance])

  const after = balance - pendingTotal
  const share = balance > 0 ? Math.min(1, pendingTotal / balance) : pendingTotal > 0 ? 1 : 0
  const tone = pendingTotal > balance ? 'critical' : share > 0.85 ? 'serious' : share > 0.5 ? 'warning' : 'accent'

  return (
    <section className="panel cash" aria-label="Checking balance">
      <div className="panel-head">
        <h2>Checking</h2>
        <span className="muted">as of {cash?.as_of ?? '—'}</span>
      </div>
      <div className="hero" aria-live="polite">
        {money(shown)}
        {delta && (
          <span key={delta.key} className={`hero-delta ${delta.amount < 0 ? 'down' : 'up'}`}>
            {delta.amount < 0 ? '▼ −' : '▲ +'}
            {money(Math.abs(delta.amount))}
          </span>
        )}
      </div>
      <div className="cash-sub muted">No revenue modeled · cash only goes out</div>

      <div className="meter-block">
        <div className="meter-labels">
          <span>Awaiting your approval</span>
          <b>{money(pendingTotal)}</b>
        </div>
        <div
          className={`meter meter-${tone}`}
          role="meter"
          aria-valuemin={0}
          aria-valuemax={balance}
          aria-valuenow={Math.min(pendingTotal, balance)}
          aria-label="Pending payments as share of checking"
        >
          <div className="meter-fill" style={{ width: `${share * 100}%` }} />
        </div>
        <div className="meter-labels">
          <span>Left if all approved</span>
          <b className={after < 0 ? 'text-critical' : ''}>
            {after < 0 && <span aria-hidden>⚠ </span>}
            {money(after)}
          </b>
        </div>
      </div>
    </section>
  )
}
