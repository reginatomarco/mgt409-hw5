import { useEffect, useRef } from 'react'
import { AGENT_BY_NAME, TOOL_LABELS, metaFor } from '../agents'
import { argsLine, clock } from '../format'
import type { AgentEvent } from '../types'
import { Avatar } from './AgentFloor'

interface Props {
  events: AgentEvent[]
  runIds: string[]
  runId: string | null
  onPickRun: (id: string) => void
  live: boolean
}

function Line({ e }: { e: AgentEvent }) {
  const meta = metaFor(e.agent)
  const indent = { paddingLeft: `${(e.depth ?? 0) * 14}px` }

  if (e.event === 'run_start') {
    return (
      <li className="tx tx-start" style={indent}>
        <Avatar meta={meta} size={22} />
        <div>
          <div className="tx-who" style={{ color: meta.color }}>{meta.label} <span className="muted">picked up</span></div>
          <div className="tx-said">{e.said}</div>
        </div>
      </li>
    )
  }
  if (e.event === 'model_response') {
    return (
      <>
        {e.said && (
          <li className="tx" style={indent}>
            <Avatar meta={meta} size={22} />
            <div className="tx-said bubble">{e.said}</div>
          </li>
        )}
        {e.tools.map((t, i) =>
          t.tool === 'delegate' ? (
            <li key={i} className="tx tx-delegate" style={indent}>
              <Avatar meta={meta} size={22} />
              <div>
                <div className="tx-who">
                  <span style={{ color: meta.color }}>{meta.label}</span>
                  <span className="arrow"> → </span>
                  <span style={{ color: AGENT_BY_NAME[String(t.args?.to)]?.color }}>
                    {AGENT_BY_NAME[String(t.args?.to)]?.label ?? String(t.args?.to)}
                  </span>
                </div>
                <div className="tx-said">{String(t.args?.task ?? '')}</div>
              </div>
            </li>
          ) : t.tool === 'final_result' ? null : (
            <li key={i} className="tx tx-tool" style={indent}>
              <span className="tool-dot" style={{ background: meta.color }} aria-hidden />
              <div>
                <span className="muted">{meta.label} · {TOOL_LABELS[t.tool] ?? 'Tool'}</span>
                <code className="tool-call">{t.tool}({argsLine(t.args)})</code>
              </div>
            </li>
          ),
        )}
      </>
    )
  }
  if (e.event === 'model_request') {
    const shown = e.tools.filter((t) => t.tool !== 'delegate' && t.tool !== 'final_result')
    if (!shown.length) return null
    return (
      <>
        {shown.map((t, i) => (
          <li key={i} className={`tx tx-result ${t.error ? 'is-error' : ''}`} style={indent}>
            <span className="tool-dot ghost" aria-hidden />
            <details>
              <summary>
                {t.error ? '✕ ' : '↩ '}
                <code>{t.tool}</code> {t.error ? 'refused' : 'returned'}
              </summary>
              <pre>{t.error ?? t.result}</pre>
            </details>
          </li>
        ))}
      </>
    )
  }
  if (e.event === 'run_end') {
    return (
      <li className="tx tx-end" style={indent}>
        <Avatar meta={meta} size={22} />
        <div className="bubble bubble-end" style={{ ['--agent' as string]: meta.color }}>
          <div className="tx-who" style={{ color: meta.color }}>{meta.label} reports</div>
          {e.said}
        </div>
      </li>
    )
  }
  if (e.event === 'delegation_refused') {
    return <li className="tx tx-warn" style={indent}>⚠ {meta.label}: {e.said}</li>
  }
  if (e.event === 'run_error') {
    return <li className="tx tx-error" style={indent}>✕ {meta.label} hit an error: {e.said}</li>
  }
  return null
}

export function Transcript({ events, runIds, runId, onPickRun, live }: Props) {
  const end = useRef<HTMLLIElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: live ? 'smooth' : 'auto', block: 'end' })
  }, [events.length, live, runId])

  return (
    <section className="panel transcript" aria-label="Live transcript">
      <div className="panel-head">
        <h2>Transcript</h2>
        <div className="run-tabs">
          {runIds.map((id, i) => (
            <button key={id} className={`run-tab ${id === runId ? 'is-on' : ''}`} onClick={() => onPickRun(id)}>
              Run {i + 1}
            </button>
          ))}
        </div>
      </div>
      <ol className="tx-list" aria-live="polite">
        {events.map((e) => (
          <Line key={e.id} e={e} />
        ))}
        {events.length === 0 && <li className="empty">Nothing yet. Deploy the team and their conversation streams in here.</li>}
        {live && (
          <li className="tx tx-typing" aria-hidden>
            <span /><span /><span />
          </li>
        )}
        <li ref={end} className="tx-sentinel" aria-hidden />
      </ol>
      {events[0] && <div className="tx-foot muted mono">run {runId} · started {clock(events[0].ts_utc)}</div>}
    </section>
  )
}
