# Campus Customs MCP Server

## What it is for

This server gives the Campus Customs agents tools for reading and acting on the shop's data. It is built on [FastMCP](https://gofastmcp.com) and speaks the Model Context Protocol (MCP). Agents never write SQL themselves; they call these tools. That keeps every answer tied to rows that actually exist in the database, so agents can't make up stock levels, prices, or due dates. The server also enforces the shop's rules in one place:

- "Today" is `desk.date_today`, not the real clock.
- A vendor with an open invoice can't ship a new order.

- Agents can only *request* payments. Money moves only through `approve_payment`, which needs a named human and is never given to an agent.
- Messages and vendor orders are simulated: they are written to `outbox`, never sent.

## Database

| File | Role |
|---|---|
| `data/campus_customs_new.db` | **The working copy.** Every tool works on this file. Read tools open it read-only. Write tools also create two extra tables here: `payment_requests` and `outbox`. |
| `data/campus_customs.db` | The untouched original. The server never opens it. Before each full run, it is copied over `campus_customs_new.db` to reset the data. |

If `campus_customs_new.db` is missing, each tool returns an error rather than creating an empty database.

## Tools

18 tools in total: 15 for agents (11 read, 4 write), 1 for the backend API (`list_tickets`), and 2 human-only payment tools. Each agent's allowed subset is listed in `output/harness.md`, together with the tables each tool reads and writes.

### Original 3 (Problem 3)

| Tool | Arguments | Returns | Used for |
|---|---|---|---|
| `get_open_tickets` | none | `desk.date_today` plus every ticket not yet closed, each with its linked inventory, pricing, lease, and invoice (with vendor) rows | Finding the work queue. It is the only path to #102's lease (rent $2,400, due 2026-09-02). |
| `check_inventory` | `sku`, optional `size` | Stock on hand and location for each size, plus `unit_cost` and `list_price` | #103: 8 of the 20 requested size-M hoodies are in stock, and the cost is $22. #101: 0 size-S tees in stock. |
| `get_vendor_status` | `vendor_id` | The vendor's `lead_days`, its open invoices (each flagged `overdue` against `desk.date_today`), `can_ship_new_order`, and `arrival_if_ordered_today` | #101: Bulldog Print Co is blocked by overdue invoice 501 ($840). Its lead time is 5 days. |

### Added in Problem 5: read tools

| Tool | Arguments | Returns | Used by |
|---|---|---|---|
| `list_tickets` | none | Every ticket in any status, with `resolved` = status is closed | Backend API only (`GET /tickets`) |
| `get_ticket` | `ticket_id` | One ticket in any status (including closed), its linked rows, and its outbox history | Boss, Inventory, Facilities, Customer Service |
| `list_inventory` | none | Every item with pricing, the out-of-stock list, and all vendors | Inventory |
| `get_lease` | `lease_id` | The lease, `days_until_due` from `desk.date_today`, and past rent payments | Facilities |
| `get_cash_position` | none | Checking balance and every bill competing for it, each listed once (open invoices, rent due within 7 days, pending purchases), plus a one-sentence `summary` and `everything_fits`, so agents never do their own cash math. Upcoming rent is listed separately and not counted. | Boss, Accounting, Facilities |
| `quote_price` | `sku`, `qty`, `discount_pct` | Unit and total price, margin, and `allowed` (false if at or below `unit_cost`) | Customer Service |
| `list_payment_requests` | optional `status` | Payment requests and the human's decisions | Boss, Accounting, Facilities |
| `list_payments` | none | Every payment actually made, with `approved_by`, and the total paid | Boss, Accounting |
| `list_outbox` | optional `ticket_id` | Simulated messages and vendor orders already written | Boss, Inventory, Customer Service |

### Added in Problem 5: write tools (agents)

| Tool | Writes | Guard |
|---|---|---|
| `request_payment` | A `pending` row in `payment_requests` | The amount is read from the DB. Duplicates and non-open invoices are refused. Rent is refused unless due within 7 days (no paying next month early). **No money moves.** |
| `propose_vendor_order` | A pending **purchase** request (qty × `unit_cost` per line) in `payment_requests` | Inventory only. **Nothing is ordered** until a human approves; approval places and pays the order in one step. A rejected purchase orders nothing. One pending purchase per vendor. |
| `send_message` | A simulated customer or landlord message in `outbox` | Nothing is emailed |
| `update_ticket` | `tickets.status`, plus a dated line in `tickets.notes` | Status must be `open`, `in_progress`, `waiting_approval`, or `closed` |

### Human only (never given to an agent; called by `backend/approvals.py` and the API's approve/reject routes)

| Tool | What it does |
|---|---|
| `approve_payment` | In one transaction: inserts a `payments` row with `approved_by`, lowers the checking balance, and marks the invoice `paid` or moves the lease's `next_due` ahead one month. Refused if cash would go negative or the request isn't pending. |
| `reject_payment` | Marks a request `rejected`, with the human's name and reason. No money moves. |

## Running

The vibe coder (Claude Code) starts it from `.mcp.json`. The agent team starts it from `backend/config.py`. Both run it over stdio:

```bash
pip install -r requirements.txt
python mcp_server/server.py
```
