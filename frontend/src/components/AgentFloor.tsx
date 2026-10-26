import { AGENTS, AGENT_BY_NAME, TOOL_LABELS, type AgentMeta, type AgentState } from '../agents'
import { argsLine } from '../format'

interface Props {
  states: Record<string, AgentState>
  live: boolean
}

function describe(s: AgentState): { line: string; detail?: string; busy: boolean } {
  switch (s.kind) {
    case 'idle':
      return { line: 'At desk', busy: false }
    case 'reading':
      return { line: 'Picked up a task', detail: s.text, busy: true }
    case 'thinking':
      return { line: 'Thinking…', busy: true }
    case 'tool':
      return { line: TOOL_LABELS[s.tool] ?? s.tool, detail: `${s.tool}(${argsLine(s.args)})`, busy: true }
    case 'delegating':
      return { line: `Waiting on ${AGENT_BY_NAME[s.to]?.label ?? s.to}`, detail: s.task, busy: true }
    case 'reporting':
      return { line: 'Filing the report', busy: true }
    case 'done':
      return { line: 'Done', detail: s.summary ?? undefined, busy: false }
    case 'error':
      return { line: 'Error', detail: s.message, busy: false }
  }
}

export function Avatar({ meta, size = 40, pulse = false }: { meta: AgentMeta; size?: number; pulse?: boolean }) {
  return (
    <div
      className={`avatar ${pulse ? 'is-pulsing' : ''}`}
      style={{ width: size, height: size, ['--agent' as string]: meta.color, fontSize: size * 0.42 }}
      aria-hidden
    >
      {meta.monogram}
    </div>
  )
}

function Station({ meta, state, big }: { meta: AgentMeta; state: AgentState; big?: boolean }) {
  const d = describe(state)
  return (
    <article
      className={`station ${big ? 'station-big' : ''} ${d.busy ? 'is-busy' : ''} station-${state.kind}`}
      style={{ ['--agent' as string]: meta.color }}
      aria-label={`${meta.label}: ${d.line}`}
    >
      <div className="station-head">
        <Avatar meta={meta} size={big ? 48 : 38} pulse={d.busy} />
        <div className="station-who">
          <div className="station-name">{meta.label}</div>
          <div className="station-title">{meta.title}</div>
        </div>
        <div className={`station-state state-${state.kind}`}>
          {d.busy && <span className="spinner" aria-hidden />}
          {state.kind === 'done' && <span aria-hidden>✔ </span>}
          {state.kind === 'error' && <span aria-hidden>✕ </span>}
          {d.line}
        </div>
      </div>
      {d.detail && <p className={`station-detail ${state.kind === 'tool' ? 'mono' : ''}`}>{d.detail}</p>}
    </article>
  )
}

export function AgentFloor({ states, live }: Props) {
  const [boss, ...team] = AGENTS
  const working = AGENTS.filter((a) => {
    const k = states[a.name]?.kind
    return k && k !== 'idle' && k !== 'done' && k !== 'error'
  }).length
  return (
    <section className="panel floor" aria-label="Agent floor">
      <div className="panel-head">
        <h2>The Floor</h2>
        <span className="muted">
          {live
            ? `${working} agent${working === 1 ? '' : 's'} working`
            : AGENTS.some((a) => states[a.name]?.kind !== 'idle')
              ? 'Showing the last run on this ticket'
              : 'Pick a ticket and deploy the team'}
        </span>
      </div>
      <Station meta={boss} state={states.boss ?? { kind: 'idle' }} big />
      <div className="station-grid">
        {team.map((a) => (
          <Station key={a.name} meta={a} state={states[a.name] ?? { kind: 'idle' }} />
        ))}
      </div>
    </section>
  )
}
