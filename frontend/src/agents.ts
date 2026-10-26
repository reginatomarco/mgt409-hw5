// The five desk agents. Identity is carried by name + monogram first; the color
// (validated categorical slots 1-5, dark steps) only reinforces it.
import type { AgentEvent, AgentName } from './types'

export interface AgentMeta {
  name: AgentName
  label: string
  title: string
  monogram: string
  color: string
}

export const AGENTS: AgentMeta[] = [
  { name: 'boss', label: 'Boss', title: 'Store manager', monogram: 'B', color: '#3987e5' },
  { name: 'inventory', label: 'Inventory', title: 'Stock & vendors', monogram: 'I', color: '#d95926' },
  { name: 'accounting', label: 'Accounting', title: 'Cash & invoices', monogram: 'A', color: '#199e70' },
  { name: 'facilities', label: 'Facilities', title: 'Lease & rent', monogram: 'F', color: '#c98500' },
  { name: 'customer_service', label: 'Customer Service', title: 'Orders & quotes', monogram: 'C', color: '#d55181' },
]

export const AGENT_BY_NAME: Record<string, AgentMeta> = Object.fromEntries(AGENTS.map((a) => [a.name, a]))

export const HUMAN: AgentMeta = {
  name: 'boss',
  label: 'You',
  title: 'Owner',
  monogram: '★',
  color: '#f0efec',
}

export const metaFor = (agent: string): AgentMeta => AGENT_BY_NAME[agent] ?? HUMAN

export const TOOL_LABELS: Record<string, string> = {
  get_open_tickets: 'Reading the ticket queue',
  get_ticket: 'Pulling the ticket file',
  list_tickets: 'Listing tickets',
  check_inventory: 'Checking stock',
  list_inventory: 'Scanning the catalogue',
  get_vendor_status: 'Checking the vendor',
  get_lease: 'Reading the lease',
  get_cash_position: 'Checking cash',
  quote_price: 'Pricing a quote',
  list_payment_requests: 'Checking approvals',
  list_payments: 'Checking payments made',
  list_outbox: 'Checking the outbox',
  request_payment: 'Requesting your approval',
  propose_vendor_order: 'Proposing a purchase',
  send_message: 'Writing a message',
  update_ticket: 'Updating the ticket',
  delegate: 'Delegating',
  final_result: 'Filing the report',
}

export type AgentState =
  | { kind: 'idle' }
  | { kind: 'reading'; text: string }
  | { kind: 'thinking' }
  | { kind: 'tool'; tool: string; args?: Record<string, unknown> }
  | { kind: 'delegating'; to: string; task: string }
  | { kind: 'reporting' }
  | { kind: 'done'; summary: string | null }
  | { kind: 'error'; message: string }

/** What each agent is doing right now, from the events of one run. */
export function agentStates(events: AgentEvent[]): Record<string, AgentState> {
  const out: Record<string, AgentState> = {}
  for (const a of AGENTS) out[a.name] = { kind: 'idle' }
  for (const e of events) {
    if (!AGENT_BY_NAME[e.agent]) continue
    switch (e.event) {
      case 'run_start':
        out[e.agent] = { kind: 'reading', text: e.said ?? '' }
        break
      case 'model_request':
        out[e.agent] = { kind: 'thinking' }
        break
      case 'model_response': {
        const call = e.tools[e.tools.length - 1]
        if (!call) out[e.agent] = { kind: 'thinking' }
        else if (call.tool === 'delegate')
          out[e.agent] = { kind: 'delegating', to: String(call.args?.to ?? ''), task: String(call.args?.task ?? '') }
        else if (call.tool === 'final_result') out[e.agent] = { kind: 'reporting' }
        else out[e.agent] = { kind: 'tool', tool: call.tool, args: call.args }
        break
      }
      case 'run_end':
        out[e.agent] = { kind: 'done', summary: e.said }
        break
      case 'run_error':
        out[e.agent] = { kind: 'error', message: e.said ?? 'Error' }
        break
    }
  }
  return out
}
