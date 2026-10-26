import { useState } from 'react'
import { elapsed } from '../format'
import type { RunInfo } from '../types'
import { useTick } from './useTick'

interface Props {
  online: boolean
  shopDate: string | null
  activeRun: RunInfo | null
  operator: string
  setOperator: (v: string) => void
  onReset: () => Promise<void>
}

export function TopBar({ online, shopDate, activeRun, operator, setOperator, onReset }: Props) {
  useTick(activeRun ? 1000 : null)
  const [armed, setArmed] = useState(false)

  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark" aria-hidden>CC</div>
        <div>
          <div className="brand-name">Campus Customs</div>
          <div className="brand-sub">Operations Desk · Chapel Street</div>
        </div>
      </div>

      <div className="topbar-center">
        {activeRun ? (
          <div className="live-pill" role="status">
            <span className="live-dot" /> LIVE · Ticket #{activeRun.ticket_id} · {elapsed(activeRun.started_utc)}
          </div>
        ) : (
          <div className="idle-pill">Desk idle</div>
        )}
        <div className="chip">Shop date <b>{shopDate ?? '—'}</b></div>
        <div className="chip mono">gpt-6-luna</div>
        <div className={`chip ${online ? 'chip-good' : 'chip-bad'}`}>
          {online ? '● API online' : '✕ API offline'}
        </div>
      </div>

      <div className="topbar-right">
        <label className="operator">
          <span>Signed in as</span>
          <input
            value={operator}
            onChange={(e) => setOperator(e.target.value)}
            placeholder="Your full name"
            aria-label="Your full name (used for approvals)"
          />
        </label>
        <button
          className={`btn btn-ghost ${armed ? 'btn-danger' : ''}`}
          disabled={!!activeRun}
          title={activeRun ? 'Wait for the run to finish' : 'Re-copy the original database'}
          onClick={async () => {
            if (!armed) {
              setArmed(true)
              window.setTimeout(() => setArmed(false), 4000)
              return
            }
            setArmed(false)
            await onReset()
          }}
        >
          {armed ? 'Confirm reset?' : '↺ Reset DB'}
        </button>
      </div>
    </header>
  )
}
