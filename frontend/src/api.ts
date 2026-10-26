// Thin client for the FastAPI backend (backend/main.py).
import type { AgentEvent, Cash, PaymentRequest, RunInfo, Ticket } from './types'

export const API_URL: string = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

const post = <T>(path: string, body?: unknown) =>
  req<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  tickets: () => req<Ticket[]>('/tickets'),
  runTicket: (id: number) => post<RunInfo>(`/tickets/${id}/run`),
  resolveTicket: (id: number, resolved_by: string) => post<unknown>(`/tickets/${id}/resolve`, { resolved_by }),
  runs: () => req<RunInfo[]>('/runs'),
  decide: (id: number, ask: string, answer: 'yes' | 'no', decided_by: string) =>
    post<unknown>(`/tickets/${id}/decision`, { ask, answer, decided_by }),
  events: (after: number, limit = 500) => req<AgentEvent[]>(`/events?after=${after}&limit=${limit}`),
  payments: () => req<{ requests: PaymentRequest[] }>('/payments?status=pending'),
  approve: (id: number, approved_by: string) => post<Record<string, unknown>>(`/payments/${id}/approve`, { approved_by }),
  reject: (id: number, rejected_by: string, reason: string) =>
    post<Record<string, unknown>>(`/payments/${id}/reject`, { rejected_by, reason }),
  cash: () => req<Cash>('/cash'),
  reset: () => post<{ reset: boolean }>('/reset'),
}
