export const money = (n: number, cents = false) =>
  n.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: cents ? 2 : 0,
    maximumFractionDigits: cents ? 2 : 0,
  })

export const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })

export function elapsed(fromIso: string, toIso?: string | null): string {
  const s = Math.max(0, Math.round(((toIso ? Date.parse(toIso) : Date.now()) - Date.parse(fromIso)) / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** Status = state: reserved status hues, always with an icon + label. */
export const TICKET_STATUS: Record<string, { label: string; icon: string; tone: string }> = {
  open: { label: 'Open', icon: '●', tone: 'neutral' },
  in_progress: { label: 'In progress', icon: '◐', tone: 'warning' },
  waiting_approval: { label: 'Needs approval', icon: '⏸', tone: 'serious' },
  closed: { label: 'Resolved', icon: '✔', tone: 'good' },
}

export const TICKET_KIND: Record<string, { label: string; icon: string }> = {
  customer_order: { label: 'Customer order', icon: '👕' },
  rent_notice: { label: 'Rent notice', icon: '🏠' },
  price_override: { label: 'Price override', icon: '🏷️' },
}

export const PAY_KIND: Record<string, string> = {
  rent: 'Rent',
  invoice: 'Invoice',
}

export function argsLine(args?: Record<string, unknown>): string {
  if (!args) return ''
  return Object.entries(args)
    .filter(([k]) => !['requested_by', 'sent_by', 'updated_by'].includes(k))
    .map(([k, v]) => `${k}=${typeof v === 'string' ? JSON.stringify(v.length > 40 ? v.slice(0, 40) + '…' : v) : JSON.stringify(v)}`)
    .join(', ')
}
