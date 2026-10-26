// Shapes returned by backend/main.py (see backend/models.py).

export type AgentName = 'boss' | 'inventory' | 'accounting' | 'facilities' | 'customer_service'

export interface Ticket {
  id: number
  type: string
  requester: string
  subject: string
  status: 'open' | 'in_progress' | 'waiting_approval' | 'closed' | string
  state: 'open' | 'resolved'
}

export interface PaymentRef {
  request_id: number
  kind: 'invoice' | 'rent' | 'purchase'
  ref_id: number
  amount: number
}

export interface TicketOutcome {
  ticket_id: number
  owner: AgentName
  status: string
  resolution: string
  next_step: string
}

export interface Decision {
  ask: string
  request_id: number | null
  amount: number | null
  recommend: 'yes' | 'no'
  why: string
}

export interface TeamReport {
  date_today: string
  headline: string
  decisions: Decision[]
  tickets: TicketOutcome[]
  cash_before: number
  cash_if_all_approved: number
}

export interface AgentReport {
  agent: AgentName
  ticket_ids: number[]
  summary: string
  facts: string[]
  actions_taken: string[]
  payment_requests: PaymentRef[]
  blocked_on: string[]
}

export interface RunInfo {
  run_id: string
  ticket_id: number
  status: 'running' | 'done' | 'error'
  started_utc: string
  finished_utc: string | null
  report: TeamReport | null
  usage: { requests: number; input_tokens: number; output_tokens: number } | null
  error: string | null
}

export interface ToolEntry {
  tool: string
  args?: Record<string, unknown>
  result?: string | null
  error?: string | null
}

export interface AgentEvent {
  id: number
  ts_utc: string
  run_id: string | null
  ticket_id: number | null
  depth: number | null
  agent: AgentName | 'human' | string
  event: string
  said: string | null
  tools: ToolEntry[]
  output: (Partial<AgentReport> & Partial<TeamReport>) | null
}

export interface PaymentRequest {
  id: number
  kind: 'invoice' | 'rent' | 'purchase'
  ref_id: number
  amount: number
  reason: string
  requested_by: string
  status: 'pending' | 'approved' | 'rejected'
  created_at: string
  decided_by: string | null
  payee: string
  for: string
  due_date: string
  is_purchase: boolean
  pay_first?: number[]
}

export interface Cash {
  account: string
  balance: number
  as_of: string
  shop_date: string
}
