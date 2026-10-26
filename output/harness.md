# Campus Customs Agent Harness

- **Original database:** `data/campus_customs.db`. Read-only; never modified.
- **Working copy:** `data/campus_customs_new.db`. All agent work runs here.
- **Shop's "today":** `desk.date_today` = **2026-08-31**
- **Model:** every agent uses `gpt-6-luna` via Portkey (hardcoded in `backend/config.py`; key read from the course-root `.env`, never committed)
- **MCP server:** `mcp_server/server.py` (FastMCP, stdio). Claude Code connects through `.mcp.json` at the project root; the backend keeps one long-lived client to the same server.

| Piece | Where |
|---|---|
| MCP server (18 tools) | `mcp_server/server.py`, `mcp_server/README.md` |
| Agents + prompts | `backend/agents/*.py`, `backend/prompts/*.md` (one per agent) |
| Data types | `backend/models.py` |
| API | `backend/main.py` (FastAPI) |
| Dashboard | `frontend/` (React + Vite + TS), design notes in `output/design.md` |
| CLI versions | `backend/run_team.py`, `backend/approvals.py` |
| Evidence | `output/mcp_smoke.json`, `output/audit_trail.json`, `output/desk_tickets.html`, `output/resolved_tickets.json`, `output/resolved_board.html` |

---

## 1. Database tables

### `desk`
**Fields:** `date_today`, `notes`
> The shop's clock. Agents use it, not the real date, to judge what is due or overdue.

### `tickets`
**Fields:** `id`, `type`, `requester`, `subject`, `sku`, `size`, `qty`, `lease_id`, `invoice_id`, `status`, `notes`, `created_at`
> The work queue. Each open ticket is a task for the agents to route, resolve, and close.

### `inventory`
**Fields:** `sku`, `name`, `size`, `qty`, `location`
> Tells agents whether an order can be filled from stock or needs a vendor reorder.

### `pricing`
**Fields:** `sku`, `unit_cost`, `list_price`
> Sets order totals, and the cost floor that any discount must stay above.

### `vendors`
**Fields:** `id`, `name`, `specialty`, `lead_days`
> Who can restock an item, and how many days it takes (drives delivery dates).

### `invoices`
**Fields:** `id`, `vendor_id`, `amount`, `due_date`, `status`, `description`
> Bills owed. An open invoice blocks that vendor from new orders. An approved purchase adds a *paid* invoice here as its record.

### `leases`
**Fields:** `id`, `space_name`, `landlord`, `monthly_rent`, `next_due`, `notes`
> Rent the agents must schedule for payment.

### `cash_accounts`
**Fields:** `name`, `balance`, `date`
> Cash available. Every payment draws it down; no revenue is modeled.

### `payments`
**Fields:** `id`, `kind`, `ref_id`, `amount`, `account`, `paid_at`, `approved_by`
> Record of money paid out. Each row must name the human who approved the payment.

### `payment_requests` *(added by the MCP server, working copy only)*
**Fields:** `id`, `kind`, `ref_id`, `amount`, `reason`, `requested_by`, `status`, `created_at`, `decided_by`, `decided_at`, `decision_note`, `details`
> Payments an agent asked for: `invoice`, `rent`, or `purchase` (a proposed restock; `details` holds its order lines and ticket ids). `pending` until a human approves or rejects it. The amount is copied from the DB, not typed by an agent.

### `outbox` *(added by the MCP server, working copy only)*
**Fields:** `id`, `kind`, `recipient`, `ticket_id`, `subject`, `body`, `sent_by`, `created_at`, `simulated`
> Every customer message, landlord message, and vendor order. All simulated: nothing is ever sent.

---

## 2. Agents

All five are pydantic-ai agents in `backend/agents/`, with one prompt file each in `backend/prompts/`. Each one sees **only** the MCP tools listed here, plus `delegate`, which lets it hand a task to any other agent.

| Agent | Role | MCP tools it can call | Output |
|---|---|---|---|
| **Boss** (`boss`) | Triages tickets, assigns owners, checks the cash plan, reports to the human | `get_open_tickets`, `get_ticket`, `get_cash_position`, `list_payment_requests`, `list_payments`, `list_outbox` | `TeamReport` |
| **Inventory** (`inventory`) | Stock by SKU/size, restock vendor, can-ship check, arrival dates, simulated orders | `get_ticket`, `check_inventory`, `list_inventory`, `get_vendor_status`, `propose_vendor_order`, `list_outbox` | `AgentReport` |
| **Accounting** (`accounting`) | Cash, vendor invoices, invoice payment requests | `get_cash_position`, `get_vendor_status`, `request_payment`, `list_payment_requests`, `list_payments` | `AgentReport` |
| **Facilities** (`facilities`) | Lease, rent schedule, rent payment requests, landlord messages | `get_ticket`, `get_lease`, `get_cash_position`, `request_payment`, `list_payment_requests`, `send_message`, `update_ticket` | `AgentReport` |
| **Customer Service** (`customer_service`) | Customer orders, quotes and discounts above cost, customer replies, ticket status | `get_ticket`, `check_inventory`, `quote_price`, `send_message`, `update_ticket`, `list_outbox` | `AgentReport` |
| **Human** (not an agent) | Approves or rejects every payment | `approve_payment`, `reject_payment` via the board's **Your call** panel (or `backend/approvals.py`); yes/no answers to the Boss via `POST /tickets/{id}/decision` | n/a |

**Delegation:** connectivity is full (any agent *can* delegate to any other), but the Boss is the dispatcher. Hand-off rules, enforced in code:
- One owner per action. Only Accounting requests invoice/bill payments and only Facilities requests rent; the MCP server refuses anyone else. Only Inventory orders, and only the ticket's owner messages the customer or landlord or changes ticket status (by tool allowlist).
- The Boss delegates to each specialist **at most once per run**.
- Specialists talk to each other **directly** on three routes, once per task: **Inventory → Accounting** (an unpaid invoice blocks the vendor), **Customer Service → Inventory** (missing stock or arrival date), and **Facilities → Accounting** (can cash cover rent alongside other bills). Anything else goes in `blocked_on` for the Boss.
- No self or circular hand-offs, and at most 3 levels deep. Every refusal is logged.
- **The next step is computed, not guessed.** `get_ticket` returns `next_step`, `next_agent` and `owner_waiting`, worked out by the MCP server from the data (requests, approvals, messages already sent). The Boss follows it: if the owner must decide, no agent is called; otherwise exactly the named agent acts. Customer orders get one short update per run; a bulk-discount ticket gets exactly one message once everything is decided. (Added after the Boss skipped closing #102 after rent was paid.)

**Loop:** `backend/run_team.py` resets the working DB, then the Boss runs and delegates. Payments end as `pending`. Restocks are purchase proposals the owner approves before anything is ordered, one proposal per ticket, so each is its own yes/no. No agent can change a pending request's amount. The human approves or rejects on the board (or with `backend/approvals.py`). Then a follow-up run (**▶ Run follow-up** on the board, or `run_team.py --continue`) finishes the work those approvals unblock: restock order, customer update, landlord confirmation, and ticket closure.

---

## 3. MCP tools and the tables they use

All 18 tools are in `mcp_server/server.py`. Agents never touch the DB directly: every shop fact goes through these tools. R = reads, W = writes.

| Tool | Type | Tables | Used by |
|---|---|---|---|
| `get_open_tickets` | read | R: `desk`, `tickets`, `inventory`, `pricing`, `leases`, `invoices`, `vendors` | Boss |
| `list_tickets` | read | R: `desk`, `tickets` | Backend API (`GET /tickets`) |
| `get_ticket` | read | R: `desk`, `tickets`, `inventory`, `pricing`, `leases`, `invoices`, `vendors`, `outbox` | Boss, Inventory, Facilities, Customer Service |
| `check_inventory` | read | R: `inventory`, `pricing` | Inventory, Customer Service |
| `list_inventory` | read | R: `inventory`, `pricing`, `vendors` | Inventory |
| `get_vendor_status` | read | R: `desk`, `vendors`, `invoices` | Inventory, Accounting |
| `get_lease` | read | R: `desk`, `leases`, `payments` | Facilities |
| `get_cash_position` | read | R: `desk`, `cash_accounts`, `invoices`, `vendors`, `leases`, `payment_requests` | Boss, Accounting, Facilities |
| `quote_price` | read | R: `pricing` | Customer Service |
| `list_payment_requests` | read | R: `payment_requests` | Boss, Accounting, Facilities |
| `list_payments` | read | R: `payments` | Boss, Accounting |
| `list_outbox` | read | R: `outbox` | Boss, Inventory, Customer Service |
| `request_payment` | write | R: `desk`, `invoices` or `leases` · W: `payment_requests` | Accounting (invoices), Facilities (rent). Rent is refused unless due within 7 days. |
| `propose_vendor_order` | write | R: `desk`, `vendors`, `inventory`, `pricing`, `invoices`, `payment_requests` · W: `payment_requests` (a pending **purchase**; nothing is ordered) | Inventory |
| `send_message` | write (simulated) | R: `desk` · W: `outbox` | Facilities, Customer Service |
| `update_ticket` | write | R: `desk`, `tickets` · W: `tickets` | Facilities, Customer Service |
| `approve_payment` | **human only** | R: `desk`, `payment_requests`, `cash_accounts`, `invoices`/`leases`, `vendors` · W: `payments`, `cash_accounts`, `invoices` or `leases`, `payment_requests`, and for a purchase a new paid `invoices` row + `outbox` vendor order | Human |
| `reject_payment` | **human only** | R: `desk` · W: `payment_requests` | Human |

### 3a. The first three tools, tied to tickets (Problem 3)

These three are read-only and query `data/campus_customs_new.db`.

#### `get_open_tickets()`: unlocks ticket **#102**
*(also the starting point for #101 and #103)*

**Reads:**
- `desk.date_today`
- `tickets` (all fields, where `status = 'open'`)
- each ticket's linked rows:
  - `leases` via `lease_id` (`monthly_rent`, `next_due`)
  - `inventory` via `sku` + `size` (`qty`, `location`)
  - `pricing` via `sku` (`unit_cost`, `list_price`)
  - `invoices` via `invoice_id` (`amount`, `due_date`, `status`)
  - `vendors` via `invoices.vendor_id` (`name`, `lead_days`)

**Why it's the right tool:** It's the only tool that follows `tickets.lease_id` to `leases`. That is how an agent learns #102's rent is **$2,400** for the Chapel Street shop, due **2026-09-02**, two days after `desk.date_today`. It also returns #101's link to invoice 501 and #103's requested size and quantity.

#### `check_inventory(sku, size)`: unlocks ticket **#103**
*(also confirms #101)*

**Reads:**
- `inventory` (`sku`, `size`, `qty`, `location`)
- `pricing` (`unit_cost`, `list_price`)

**Why it's the right tool:** It shows only **8** size-M `CC-HOOD-NAVY` hoodies in stock against the **20** the Yale AI Club wants (**12 short**). It also gives the **$22** unit cost as the floor for any bulk discount off the **$58** list price. For #101, it confirms the size-S `CC-TEE-WHITE` tee is at **0**, so that order can't be filled from stock.

#### `get_vendor_status(vendor_id)`: unlocks ticket **#101**
*(also blocks the restock for #103)*

**Reads:**
- `desk.date_today`
- `vendors` (`name`, `specialty`, `lead_days`)
- `invoices` for that vendor (`id`, `amount`, `due_date`, `status`)

**Why it's the right tool:** The size-S tee for #101 has to come from Bulldog Print Co. This tool shows that vendor's invoice 501 (**$840, due 2026-08-28**) is still open and overdue against `desk.date_today`, so it returns `can_ship_new_order = false`. It also returns the vendor's **5-day** lead time. The agent then knows to request payment approval for 501 first, and can promise the tee around **2026-09-05**.


---

## 4. Ticket to tool summary

| Ticket | Request | Key tool | What the tool reveals |
|---|---|---|---|
| **#101** | 1 Bulldog tee, size S | `get_vendor_status(1)` | Vendor blocked by overdue invoice 501 ($840); 5-day lead time |
| **#102** | Rent notice | `get_open_tickets()` | $2,400 rent due 2026-09-02 |
| **#103** | 20 hoodies, size M, bulk discount | `check_inventory("CC-HOOD-NAVY", "M")` | Only 8 in stock; $22 cost floor vs. $58 list price |

---

## 5. Backend routes (FastAPI)

`backend/main.py`. Start it from `backend/` with `uvicorn main:app --reload --port 8000`; interactive docs are at `/docs`. Every shop fact comes through the MCP server, over one long-lived connection opened at startup. CORS allows the Vite board at `http://localhost:5173`.

- `GET /tickets`: all three tickets, each with its raw status and `open` or `resolved`.
- `POST /tickets/{ticket_id}/run`: starts the agent team on one ticket in the background and returns a `run_id`. Only one run at a time (otherwise 409); uses gpt-6-luna.
- `POST /tickets/{ticket_id}/resolve`: the human marks a ticket resolved from the board (body: `resolved_by`). Uses the MCP tool `update_ticket` and is logged as a human event. Refused (409) for a customer ticket whose customer hasn't been messaged yet.
- `POST /tickets/{ticket_id}/decision`: the owner answers a Boss yes/no question that isn't a payment, e.g. "10% discount?" (body: `ask`, `answer`, `decided_by`). Saved on the ticket as an `OWNER DECISION:` note through `update_ticket`, so the next run sees it.
- `GET /runs`: runs from this server session, newest first. The board uses it to find a live run after a page reload.
- `GET /runs/{run_id}`: a run's status (`running` / `done` / `error`), plus the Boss's TeamReport and token usage when it finishes.
- `GET /events?limit=&after=&run_id=&ticket_id=`: recent agent events from the audit trail, with which tools each agent called and its final report (raw model text stays in the audit trail and is not shown). `after` returns only newer events, for board refresh.
- `GET /payments?status=pending`: payment requests (rent, invoices, and purchase bills) waiting for a human.
- `POST /payments/{request_id}/approve`: the human clicked Approve (body: `approved_by`). Pays and updates `payments`, cash, and the invoice or lease. Logged as a human event.
- `POST /payments/{request_id}/reject`: the human clicked Reject (body: `rejected_by`, `reason`). No money moves.
- `GET /cash`: the current checking balance from `cash_accounts`, plus the shop date (`desk.date_today`).
- `POST /reset`: re-copies `data/campus_customs.db` over the working copy for a fresh run (blocked during a run). The audit trail is kept.

---

## 6. Audit trail

`output/audit_trail.json` is a JSON array that is **only ever appended to**. Each event is written in place just before the closing `]` (no rewrite or temp-file swap, which Windows sometimes blocked), with short retries if a reader holds the file. Nothing is ever wiped; `POST /reset` resets the database, not the log. Every event has `ts_utc`, `run_id` (one per team run), `agent`, `chain`, and `depth`.

| Event | Records |
|---|---|
| `run_start` | The task the agent was given and the limits in force |
| `model_request` | What went into the model: tool results (clipped at 4,000 chars, original length kept), retry/validation errors |
| `model_response` | What came out: model name, input/output tokens, each tool call with full arguments, any text |
| `delegation_refused` | Blocked hand-offs (loop or depth limit) and why |
| `run_end` | The agent's structured output and the team's cumulative usage |
| `run_error` | Any exception, before it stops the run |
| `payment_approved` / `payment_rejected` | Human decisions from `approvals.py` or the API: who, which request, and the result |
| `owner_decision` | The owner's yes/no on a Boss question (e.g. the #103 discount) |
| `ticket_resolved` | The human closed a ticket from the board |
| `db_reset` | A reset of the working DB through `POST /reset` (the board shows only events after the last one) |
| `resolution_summary` | Wrap-up after the final runs: run ids per ticket, final statuses, start and end cash |

---

## 7. Token and cost limits

| Limit | Value | Where |
|---|---|---|
| Model calls per team run (Boss + all delegated agents, shared) | **30** | `USAGE_LIMITS.request_limit` |
| Calls/tokens before delegated agents must stop (reserve for the Boss's report) | **26** calls / **70,000** tokens | `SUB_AGENT_LIMITS` |
| Total tokens per team run (shared) | **80,000** | `USAGE_LIMITS.total_tokens_limit` |
| Max output tokens per model response | **800** (was 1,500) | `MODEL_SETTINGS.max_tokens` |
| Delegation depth | **3** hand-offs | `MAX_DELEGATION_DEPTH` |
| Output-validation retries per agent (bad schema or garbled text) | **2** | `retries=2` |
| HTTP retries on a failed call | **0** (failures are not re-billed) | `max_retries=0` |
| Request timeout | **90 s** | `httpx.Timeout` |

If a delegated agent hits its limit, `delegate` catches it and tells the caller to report with what it has, so the Boss always returns a report. Only if the Boss itself hits the team cap does the run stop with `run_error`.

**Why the limits were cut:** the first 8 real runs used about 500k input and 17k output tokens. One #103 run made 36 calls and hit the old 200k cap. Most of it was agents re-checking things (`get_ticket` was called 46 times), and every call resends the whole history. The prompts now say: check each thing once, delegate once per specialist, Boss aims for 8 calls or fewer and specialists for 5 or fewer. The Boss report is also capped at a 15-word headline plus at most 3 yes/no decisions.

---

## 8. Safety: guardrails for real customers and money

What this harness already does, and what a real business would add before letting agents act for real.

**Money**
- **Human approval for every payment.** Agents can only request a payment. Approval is a separate human step, through a tool no agent can see. *Real business:* two-person approval above a set amount; payees chosen only from a vetted vendor list; bank changes confirmed out of band.
- **No paying rent early.** Rent can only be requested within 7 days of its due date. Once a month is paid, `next_due` moves ahead, so next month's rent is refused, and the cash view lists it as *upcoming*, not owed. (Added after a test run where the post-payment view made it look like rent was still unpaid.)
- **No agent cash math.** `get_cash_position` lists each bill once and returns a ready-made `summary` and `everything_fits`. Agents quote it and never add numbers themselves. (Added after the Boss double-counted invoice 501 and wrongly advised rejecting rent.)
- **Amounts come from the books.** The payment amount is copied from the invoice or lease, so an agent can't type one. Duplicate requests, double approvals, and paying more than the cash balance are all refused. *Real business:* daily and per-vendor spend caps, and reconciliation against bank statements.
- **Approve before ordering.** Inventory only *proposes* a restock purchase, priced at cost. The order is placed and paid in one step only when the owner approves it; a rejected purchase orders nothing. A purchase from a vendor with an unpaid invoice can't be approved until that invoice is paid.
- **Every payment is recorded once.** In one transaction: a `payments` row with `approved_by`, the new balance, and the invoice or lease update.

**Customers and outside parties**
- **Nothing leaves the building.** Customer, landlord, and vendor contact is simulated in `outbox`. *Real business:* a send queue that a human reviews before release, at least until quality is proven; approved templates; a ban on internal data (costs, margins, invoices) in customer text; opt-out and privacy compliance.
- **Garbage-output guard.** The model occasionally emits garbled tokens (a run printed Chinese junk next to a valid report). Agent reports and outgoing messages containing non-English scripts are rejected and rewritten, and the board shows only actions and final reports, never raw model text (raw text stays in the audit trail).
- **No internal details to customers.** `send_message` refuses customer messages that mention invoices, vendors, approvals, "pending", margins, or costs; the agent must rewrite. Discounted prices go out only after the owner says yes. (Added after a run leaked "pending invoice #501" to the Yale AI Club.)
- **Price floor.** `quote_price` blocks any price at or below unit cost, and discounts are proposals that need sign-off. *Real business:* a written discount policy with caps by order size.

**Agent control**
- **Least privilege.** Each agent sees only the tools its role needs, and none can reach the database except through MCP.
- **Loop and cost limits.** No self or circular delegation, a depth cap, and one shared token and request budget (section 7).
- **Isolation.** All writes go to a working copy that is reset from the untouched original before each full run. *Real business:* a staging environment and a dry-run mode before production.
- **Full audit trail.** Every model call, tool call, argument, result, and human decision is appended (section 6). *Real business:* tamper-evident storage, retention rules, and regular review of agent actions.
- **Grounding.** Prompts forbid invented data, "today" comes only from `desk.date_today`, and every number must trace back to a tool result.
- **Kill switch.** *Real business:* the ability to pause all agents at once, alerts on unusual activity (a spend spike, many refusals), and a named human owner for the system.

---

## 9. Dashboard (React board)

`frontend/` is React 19 + Vite + TypeScript. Start it with `npm run dev` in `frontend/` (port 5173); it polls the API on port 8000. Design choices are in `output/design.md`.

| Panel | What it shows / does |
|---|---|
| **Top bar** | Shop date, model (`gpt-6-luna`), API status, signed-in name (stamped on every approval), **Reset DB** |
| **Queue** | The three tickets with status and a RESOLVED stamp. On the selected ticket: **▶ Deploy team** / **▶ Run follow-up** (paid run) and **✔ Mark resolved** |
| **The Floor** | One card per agent (Boss + four specialists): idle, working, or done, with its one-line report |
| **Transcript** | Each run on the ticket as plain steps (e.g. "Inventory · Checking stock" + the tool call), hand-offs, and each agent's report. Run tabs switch between runs |
| **Checking** | Cash from `cash_accounts`, what's awaiting approval, and what's left if all is approved |
| **Your call** | Pending payments and purchases with Approve / Reject (two-step confirm), the Boss's tip, and a "pay first" warning when a purchase is blocked by an unpaid invoice |
| **Boss says** | The Boss's headline and at most 3 clickable yes/no decisions; agent notes collapsed |

---

## 10. Running it

1. Backend: from `backend/`, `uvicorn main:app --port 8000`. Frontend: from `frontend/`, `npm run dev`, then open http://localhost:5173.
2. **Reset DB** (clones `data/campus_customs.db` into `data/campus_customs_new.db`).
3. For each ticket: **▶ Deploy team** → answer **Your call** / **Boss says** → **▶ Run follow-up** until the ticket is closed.

Every ticket follows the same loop: `get_ticket.next_step` says who acts, agents propose, the owner decides, and a follow-up finishes the work.

---

## 11. Results of the final real runs

Six real runs after the 2026-10-26 18:03 UTC reset (two per ticket), with no errors, retries, or refused hand-offs. Details are in `output/resolved_tickets.json`, board screenshots in `output/resolved_board.html`, and the itemized Cash tab in `output/desk_tickets.html`.

| Ticket | Direct agent-to-agent hand-off | Owner decided | Cash |
|---|---|---|---|
| **#101** Bulldog tee | Inventory → Accounting | Approved invoice 501 ($840) and tee purchase ($8) | −$848 |
| **#102** Rent due | Facilities → Accounting | Approved rent ($2,400) | −$2,400 |
| **#103** Bulk hoodies | Inventory → Accounting | Rejected restock ($264); no to 10% discount | $0 |

Checking: **$3,400 → $152**, matching `cash_accounts` in `data/campus_customs_new.db`. All three tickets are `closed`. Simulated outbox: Tauhid 2 messages, the landlord 2, the Yale AI Club 1, and 1 vendor order.
