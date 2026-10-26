"""Campus Customs MCP server.

Exposes the shop database to the agents as MCP tools. Every tool works on the
working clone `data/campus_customs_new.db`; the original `campus_customs.db`
is never opened. Tools only return rows that exist in the database -- nothing
is invented. "Today" is always `desk.date_today`, never the real clock.

Write rules enforced here (not just in prompts):
- Agents can only *request* payments. Money moves only in `approve_payment`,
  which requires a named human approver and is never given to an agent.
- Messages to customers, vendors, and the landlord are simulated: they are
  written to the `outbox` table and never sent.
- A vendor with an open invoice cannot receive a new (simulated) order.
"""

import calendar
import json
import re
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP
from pydantic import BaseModel, Field
from fastmcp.exceptions import ToolError

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "campus_customs_new.db"

# Extra tables the agents write to. They exist only in the working clone.
AUX_SCHEMA = """
CREATE TABLE IF NOT EXISTS payment_requests (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,              -- 'invoice', 'rent', or 'purchase'
    ref_id INTEGER NOT NULL,         -- invoices.id, leases.id, or vendors.id (purchase)
    amount REAL NOT NULL,            -- copied from the DB, never typed by an agent
    reason TEXT NOT NULL,
    requested_by TEXT NOT NULL,      -- agent name
    status TEXT NOT NULL,            -- 'pending', 'approved', 'rejected'
    created_at TEXT NOT NULL,        -- desk.date_today
    decided_by TEXT,                 -- human name
    decided_at TEXT,
    decision_note TEXT,
    details TEXT                     -- purchase: JSON lines + ticket_ids
);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,              -- 'customer_message', 'landlord_message', 'vendor_order'
    recipient TEXT NOT NULL,
    ticket_id INTEGER,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_by TEXT NOT NULL,           -- agent name
    created_at TEXT NOT NULL,        -- desk.date_today
    simulated INTEGER NOT NULL DEFAULT 1
);
"""

TICKET_STATUSES = ("open", "in_progress", "waiting_approval", "closed")

# Rent counts as owed (and can be requested) only when due within this many days of
# desk.date_today. After a rent payment, next_due moves a month ahead, so this blocks
# paying the following month early by mistake.
RENT_WINDOW_DAYS = 7

# Words that reveal internal business to a customer. send_message refuses customer messages containing them.
INTERNAL_TERMS = ("invoice", "vendor", "supplier", "pending", "approval", "approve", "margin",
                  "unit cost", "our cost", "payment request", "bill #")

mcp = FastMCP(
    "campus-customs",
    instructions=(
        "Tools for Campus Customs, a Yale apparel shop. All data comes from the "
        "shop database; 'today' is desk.date_today."
    ),
)


def _connect_readonly() -> sqlite3.Connection:
    """Open the working DB read-only (mode=ro also fails if the file is missing)."""
    if not DB_PATH.exists():
        raise ToolError(f"Working database not found: {DB_PATH}. Clone campus_customs.db first.")
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _connect_rw() -> sqlite3.Connection:
    """Open the working DB for writing (mode=rw never creates a new file)."""
    if not DB_PATH.exists():
        raise ToolError(f"Working database not found: {DB_PATH}. Clone campus_customs.db first.")
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=rw", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(AUX_SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(payment_requests)")}
    if "details" not in cols:  # working DBs created before purchase requests existed
        conn.execute("ALTER TABLE payment_requests ADD COLUMN details TEXT")
    return conn


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


def _today(conn: sqlite3.Connection) -> str:
    return conn.execute("SELECT date_today FROM desk").fetchone()["date_today"]


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def _add_days(iso: str, days: int) -> str:
    return (date.fromisoformat(iso) + timedelta(days=days)).isoformat()


def _add_month(iso: str) -> str:
    d = date.fromisoformat(iso)
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return d.replace(year=year, month=month, day=min(d.day, calendar.monthrange(year, month)[1])).isoformat()


def _require_text(value: str, field: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ToolError(f"{field} is required.")
    return value


# --------------------------------------------------------------------------
# Read tools
# --------------------------------------------------------------------------

def _ticket_with_links(conn: sqlite3.Connection, t: sqlite3.Row) -> dict:
    """A ticket plus its inventory (sku + size), pricing (sku), lease, and invoice + vendor rows."""
    ticket = dict(t)
    ticket["inventory"] = _row(conn.execute(
        "SELECT * FROM inventory WHERE sku = ? AND size = ?", (t["sku"], t["size"])
    ).fetchone())
    ticket["pricing"] = _row(conn.execute(
        "SELECT * FROM pricing WHERE sku = ?", (t["sku"],)
    ).fetchone())
    ticket["lease"] = _row(conn.execute(
        "SELECT * FROM leases WHERE id = ?", (t["lease_id"],)
    ).fetchone())
    invoice = _row(conn.execute(
        "SELECT * FROM invoices WHERE id = ?", (t["invoice_id"],)
    ).fetchone())
    if invoice is not None:
        invoice["vendor"] = _row(conn.execute(
            "SELECT * FROM vendors WHERE id = ?", (invoice["vendor_id"],)
        ).fetchone())
    ticket["invoice"] = invoice
    return ticket


@mcp.tool
def get_open_tickets() -> dict:
    """List every ticket that is not closed, with the rows it links to.

    For each ticket, attaches the matching inventory row (sku + size), pricing
    row (sku), lease (lease_id), and invoice plus its vendor (invoice_id).
    Links that don't apply are null.
    """
    with closing(_connect_readonly()) as conn:
        today = _today(conn)
        tickets = [
            _ticket_with_links(conn, t)
            for t in conn.execute("SELECT * FROM tickets WHERE status != 'closed' ORDER BY id")
        ]
    return {"date_today": today, "open_ticket_count": len(tickets), "tickets": tickets}


@mcp.tool
def list_tickets() -> dict:
    """List every ticket in any status (id, type, requester, subject, status, created_at).

    `resolved` is true when status is 'closed'.
    """
    with closing(_connect_readonly()) as conn:
        today = _today(conn)
        rows = [
            {**dict(r), "resolved": r["status"] == "closed"}
            for r in conn.execute(
                "SELECT id, type, requester, subject, sku, size, qty, status, created_at "
                "FROM tickets ORDER BY id"
            )
        ]
    return {"date_today": today, "tickets": rows}



def _requests_for_ticket(conn: sqlite3.Connection, t: sqlite3.Row) -> list[dict]:
    """Payment/purchase requests that belong to this ticket (rent by lease, invoice by id, purchases by ticket)."""
    if not _has_table(conn, "payment_requests"):
        return []
    out = []
    for r in conn.execute("SELECT * FROM payment_requests ORDER BY id"):
        r = dict(r)
        if r["kind"] == "rent" and r["ref_id"] == t["lease_id"]:
            out.append(r)
        elif r["kind"] == "invoice" and r["ref_id"] == t["invoice_id"]:
            out.append(r)
        elif r["kind"] == "purchase" and t["id"] in json.loads(r.get("details") or "{}").get("ticket_ids", []):
            out.append(r)
    return out


def _next_step(conn: sqlite3.Connection, t: sqlite3.Row, outbox: list[dict]) -> dict:
    """Deterministic next step for a ticket, from the data. The Boss follows it.

    `owner_waiting` is true when nothing can happen until the owner decides; then
    `next_step` names what they must decide and no agent should be called.
    """
    today = _today(conn)
    if t["status"] == "closed":
        return {"state": "done", "owner_waiting": False, "next_agent": None, "next_step": "Closed. Nothing to do."}
    reqs = _requests_for_ticket(conn, t)
    pending = [r for r in reqs if r["status"] == "pending"]
    told = [m for m in outbox if m["kind"] == "customer_message"]
    notes = t["notes"] or ""

    if t["type"] == "rent_notice":
        rent = [r for r in reqs if r["kind"] == "rent"]
        if any(r["status"] == "approved" for r in rent):
            return {"state": "rent_paid", "owner_waiting": False, "next_agent": "facilities",
                    "next_step": "Rent is PAID. Facilities: send the landlord one short confirmation, then close the ticket."}
        if pending:
            return {"state": "waiting_owner", "owner_waiting": True, "next_agent": None,
                    "next_step": f"Waiting for the owner to approve rent request {pending[0]['id']} (${pending[0]['amount']:,.0f})."}
        if any(r["status"] == "rejected" for r in rent):
            return {"state": "rent_rejected", "owner_waiting": False, "next_agent": "facilities",
                    "next_step": "Owner rejected the rent. Facilities: keep the ticket open and report days left until due."}
        return {"state": "new", "owner_waiting": False, "next_agent": "facilities",
                "next_step": "Facilities: request the rent (due within 7 days), send the landlord one note, set waiting_approval."}

    inv = conn.execute("SELECT * FROM inventory WHERE sku = ? AND size = ?", (t["sku"], t["size"])).fetchone()
    on_hand = inv["qty"] if inv else 0
    short = max(0, (t["qty"] or 0) - on_hand)
    purchases = [r for r in reqs if r["kind"] == "purchase"]
    bought = [r for r in purchases if r["status"] == "approved"]
    refused = [r for r in purchases if r["status"] == "rejected"]
    eta = None
    if bought:
        vendor = conn.execute("SELECT lead_days FROM vendors WHERE id = ?", (bought[-1]["ref_id"],)).fetchone()
        eta = _add_days(bought[-1]["decided_at"] or today, vendor["lead_days"])

    if t["type"] == "customer_order":
        if short == 0 and not purchases:
            return {"state": "in_stock", "owner_waiting": False, "next_agent": "customer_service",
                    "next_step": "In stock. Customer Service: tell the customer it's held for them, then close."}
        if not purchases:
            return {"state": "new", "owner_waiting": False, "next_agent": "inventory",
                    "next_step": f"Out of stock (short {short}). Inventory: propose a restock for this ticket (and get Accounting to request any blocking invoice). Then Customer Service: tell the customer it's out of stock and we'll let them know. Set in_progress."}
        if bought:
            return {"state": "ordered", "owner_waiting": False, "next_agent": "customer_service",
                    "next_step": f"Restock approved and ordered, arriving about {eta}. Customer Service: tell the customer it's on the way (about {eta}), then close."}
        if refused and not pending:
            return {"state": "restock_rejected", "owner_waiting": False, "next_agent": "customer_service",
                    "next_step": "Owner rejected the restock. Customer Service: tell the customer it's unavailable, then close."}
        step = "Waiting for the owner to decide: " + ", ".join(f"request {r['id']} ({r['kind']} ${r['amount']:,.2f})" for r in pending) + "."
        if not told:
            return {"state": "waiting_owner", "owner_waiting": False, "next_agent": "customer_service",
                    "next_step": step + " Customer Service has not replied yet: tell the customer it's out of stock and we'll let them know."}
        return {"state": "waiting_owner", "owner_waiting": True, "next_agent": None, "next_step": step}

    # price_override (bulk discount): exactly one customer message, once everything is decided.
    decided = "OWNER DECISION:" in notes
    proposal = "discount proposal" in notes.lower() or "quote" in notes.lower()
    if told:
        return {"state": "customer_told", "owner_waiting": False, "next_agent": "customer_service",
                "next_step": "The customer already has their one message. Customer Service: close the ticket (send nothing)."}
    if not proposal and not decided:
        who = "Inventory: propose a restock for the shortfall" if short and not purchases else "Inventory: report stock"
        return {"state": "new", "owner_waiting": False, "next_agent": "inventory",
                "next_step": f"{on_hand} on hand, short {short}. {who}. Then Customer Service: price a discount proposal and note it on the ticket (send NOTHING to the customer). Set waiting_approval."}
    if pending or not decided:
        waits = [f"request {r['id']} ({r['kind']} ${r['amount']:,.2f})" for r in pending]
        if not decided:
            waits.append("the discount (a yes/no decision in your report)")
        return {"state": "waiting_owner", "owner_waiting": True, "next_agent": None,
                "next_step": "Waiting for the owner to decide: " + ", ".join(waits) + "."}
    qty = on_hand + (short if bought else 0)
    when = f", the rest arriving about {eta}" if bought else ""
    return {"state": "ready_to_reply", "owner_waiting": False, "next_agent": "customer_service",
            "next_step": f"Everything is decided. Customer Service: send the ONE message: price per the OWNER DECISION, {qty} hoodies ({on_hand} now{when}). Then close."}


@mcp.tool
def get_ticket(ticket_id: int) -> dict:
    """Return one ticket (any status) with its linked rows, outbox history, and its NEXT STEP.

    `next_step` / `next_agent` / `owner_waiting` are computed from the data (requests,
    approvals, messages already sent). Follow them: if `owner_waiting` is true, nothing
    can happen until the owner decides, so don't call any agent.

    Args:
        ticket_id: tickets.id.
    """
    with closing(_connect_readonly()) as conn:
        today = _today(conn)
        t = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            raise ToolError(f"No ticket with id={ticket_id}.")
        ticket = _ticket_with_links(conn, t)
        ticket["outbox"] = [dict(r) for r in conn.execute(
            "SELECT * FROM outbox WHERE ticket_id = ? ORDER BY id", (ticket_id,)
        )] if _has_table(conn, "outbox") else []
        nxt = _next_step(conn, t, ticket["outbox"])
    return {"date_today": today, **nxt, "ticket": ticket}


@mcp.tool
def check_inventory(sku: str, size: str | None = None) -> dict:
    """Return stock on hand and pricing for a SKU.

    Args:
        sku: Product SKU, e.g. "CC-TEE-WHITE".
        size: Optional size ("S", "M", "L", "XL", "OS"). Omit to get all sizes.
    """
    with closing(_connect_readonly()) as conn:
        if size is None:
            rows = conn.execute(
                "SELECT * FROM inventory WHERE sku = ? ORDER BY size", (sku,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM inventory WHERE sku = ? AND size = ?", (sku, size)
            ).fetchall()
        if not rows:
            raise ToolError(f"No inventory found for sku={sku!r}, size={size!r}.")
        pricing = _row(conn.execute("SELECT * FROM pricing WHERE sku = ?", (sku,)).fetchone())
    return {"sku": sku, "stock": [dict(r) for r in rows], "pricing": pricing}


@mcp.tool
def list_inventory() -> dict:
    """Return every inventory row with its pricing, plus the vendor list.

    Use this to see the whole catalogue, which items are out of stock, and
    which vendor specialty could restock each item.
    """
    with closing(_connect_readonly()) as conn:
        rows = conn.execute(
            "SELECT i.sku, i.name, i.size, i.qty, i.location, p.unit_cost, p.list_price "
            "FROM inventory i LEFT JOIN pricing p ON p.sku = i.sku ORDER BY i.sku, i.size"
        ).fetchall()
        vendors = [dict(v) for v in conn.execute("SELECT * FROM vendors ORDER BY id")]
    items = [dict(r) for r in rows]
    return {
        "items": items,
        "out_of_stock": [f"{r['sku']} {r['size']}" for r in items if r["qty"] == 0],
        "vendors": vendors,
    }


@mcp.tool
def get_vendor_status(vendor_id: int) -> dict:
    """Return a vendor's lead time and its open invoices.

    A vendor will not ship a new order while it has an open, unpaid invoice,
    so `can_ship_new_order` is false whenever `open_invoices` is non-empty.
    Each invoice is flagged `overdue` if its due_date is before desk.date_today.
    `arrival_if_ordered_today` is desk.date_today + lead_days.

    Args:
        vendor_id: vendors.id (1 = Bulldog Print Co, 2 = Elm City Gifts, 3 = QuickShip CT).
    """
    with closing(_connect_readonly()) as conn:
        today = _today(conn)
        vendor = _row(conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone())
        if vendor is None:
            raise ToolError(f"No vendor with id={vendor_id}.")
        requested = set()
        if _has_table(conn, "payment_requests"):
            requested = {r["ref_id"] for r in conn.execute(
                "SELECT ref_id FROM payment_requests WHERE kind = 'invoice' AND status = 'pending'")}
        open_invoices = [
            {**dict(r), "overdue": r["due_date"] < today, "payment_already_requested": r["id"] in requested}
            for r in conn.execute(
                "SELECT * FROM invoices WHERE vendor_id = ? AND status = 'open' ORDER BY due_date",
                (vendor_id,),
            )
        ]
    return {
        "date_today": today,
        "vendor": vendor,
        "open_invoices": open_invoices,
        "can_ship_new_order": not open_invoices,
        "arrival_if_ordered_today": _add_days(today, vendor["lead_days"]),
    }


@mcp.tool
def get_lease(lease_id: int) -> dict:
    """Return a lease, its rent, and how many days until rent is due.

    `days_until_due` is next_due minus desk.date_today (negative = late).

    Args:
        lease_id: leases.id (1 = Chapel Street shop).
    """
    with closing(_connect_readonly()) as conn:
        today = _today(conn)
        lease = _row(conn.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone())
        if lease is None:
            raise ToolError(f"No lease with id={lease_id}.")
        paid = [dict(r) for r in conn.execute(
            "SELECT * FROM payments WHERE kind = 'rent' AND ref_id = ? ORDER BY id", (lease_id,)
        )]
    days = (date.fromisoformat(lease["next_due"]) - date.fromisoformat(today)).days
    return {"date_today": today, "lease": lease, "days_until_due": days, "rent_payments": paid}


@mcp.tool
def get_cash_position() -> dict:
    """Return cash on hand and every bill competing for it, with the math done for you.

    `obligations` lists each bill ONCE: open invoices, rent due within 7 days, and pending
    restock purchases (each marked `requested` if it's already waiting for the owner).
    `summary` states the result in one sentence; `everything_fits` says if cash covers all
    of it. Don't add pending requests on top: they are already inside `obligations`.
    Rent further out (next month) is in `upcoming_rent` and is NOT owed yet. No revenue is
    modeled: cash only goes out.
    """
    with closing(_connect_readonly()) as conn:
        today = _today(conn)
        accounts = [dict(r) for r in conn.execute("SELECT * FROM cash_accounts ORDER BY name")]
        invoices = [
            {**dict(r), "overdue": r["due_date"] < today}
            for r in conn.execute(
                "SELECT i.*, v.name AS vendor_name FROM invoices i "
                "JOIN vendors v ON v.id = i.vendor_id WHERE i.status = 'open' ORDER BY i.due_date"
            )
        ]
        leases = [
            {**dict(r), "days_until_due": (date.fromisoformat(r["next_due"]) - date.fromisoformat(today)).days}
            for r in conn.execute("SELECT * FROM leases ORDER BY next_due")
        ]
        pending = []
        if _has_table(conn, "payment_requests"):
            pending = [dict(r) for r in conn.execute(
                "SELECT * FROM payment_requests WHERE status = 'pending' ORDER BY id"
            )]
    cash = sum(a["balance"] for a in accounts)
    rent_due = [l for l in leases if l["days_until_due"] <= RENT_WINDOW_DAYS]
    upcoming = [{**l, "note": f"Not yet due; current period is paid. Due in {l['days_until_due']} days."}
                for l in leases if l["days_until_due"] > RENT_WINDOW_DAYS]
    asked = {(p["kind"], p["ref_id"]) for p in pending}
    obligations = (
        [{"what": f"Invoice {i['id']} ({i['vendor_name']})", "amount": i["amount"], "due": i["due_date"],
          "requested": ("invoice", i["id"]) in asked} for i in invoices]
        + [{"what": f"Rent ({l['space_name']})", "amount": l["monthly_rent"], "due": l["next_due"],
            "requested": ("rent", l["id"]) in asked} for l in rent_due]
        + [{"what": f"Restock purchase request {p['id']}", "amount": p["amount"], "due": p["created_at"],
            "requested": True} for p in pending if p["kind"] == "purchase"]
    )
    total = round(sum(o["amount"] for o in obligations), 2)
    pending_total = round(sum(p["amount"] for p in pending), 2)
    left = round(cash - total, 2)
    items = " + ".join(f"{o['what']} ${o['amount']:,.2f}" for o in obligations) or "nothing"
    summary = (f"Checking ${cash:,.2f}. Bills: {items} = ${total:,.2f}. "
               + (f"Paying all of them leaves ${left:,.2f}." if left >= 0
                  else f"That is ${-left:,.2f} MORE than checking: not everything can be paid."))
    return {
        "date_today": today,
        "cash_accounts": accounts,
        "cash_total": cash,
        "summary": summary,
        "everything_fits": left >= 0,
        "obligations": obligations,
        "obligations_total": total,
        "cash_left_if_all_paid": left,
        "pending_requests_total": pending_total,
        "cash_left_if_pending_approved": round(cash - pending_total, 2),
        "pending_payment_requests": pending,
        "upcoming_rent": upcoming,
    }


@mcp.tool
def quote_price(sku: str, qty: int, discount_pct: float = 0.0) -> dict:
    """Price an order from the pricing table, with an optional discount.

    The discounted unit price must stay above unit_cost (the cost floor);
    `allowed` is false if it does not. Also reports how much is in stock
    across all sizes. Does not change any data.

    Args:
        sku: Product SKU.
        qty: Units requested (must be > 0).
        discount_pct: Discount off list price, in percent (0-100).
    """
    if qty <= 0:
        raise ToolError("qty must be greater than 0.")
    if not 0 <= discount_pct < 100:
        raise ToolError("discount_pct must be between 0 and 100.")
    with closing(_connect_readonly()) as conn:
        p = _row(conn.execute("SELECT * FROM pricing WHERE sku = ?", (sku,)).fetchone())
        if p is None:
            raise ToolError(f"No pricing for sku={sku!r}.")
    unit_price = round(p["list_price"] * (1 - discount_pct / 100), 2)
    max_pct = round((1 - p["unit_cost"] / p["list_price"]) * 100, 2)
    return {
        "sku": sku,
        "qty": qty,
        "list_price": p["list_price"],
        "unit_cost": p["unit_cost"],
        "discount_pct": discount_pct,
        "unit_price": unit_price,
        "total_price": round(unit_price * qty, 2),
        "margin_per_unit": round(unit_price - p["unit_cost"], 2),
        "total_margin": round((unit_price - p["unit_cost"]) * qty, 2),
        "allowed": unit_price > p["unit_cost"],
        "break_even_discount_pct": max_pct,
    }


@mcp.tool
def list_payment_requests(status: Literal["pending", "approved", "rejected"] | None = None) -> dict:
    """List payment requests and their human decisions.

    Each request includes `payee` and `for` (vendor + invoice description, landlord +
    space, or the purchase lines), `is_purchase` (true for restock purchases), and for
    purchases `pay_first`: unpaid invoices of that vendor the owner must pay first.

    Args:
        status: Optional filter. Omit to list all.
    """
    with closing(_connect_readonly()) as conn:
        if not _has_table(conn, "payment_requests"):
            return {"requests": []}
        sql, args = "SELECT * FROM payment_requests", ()
        if status:
            sql, args = sql + " WHERE status = ?", (status,)
        rows = []
        for r in conn.execute(sql + " ORDER BY id", args):
            row = dict(r)
            if r["kind"] == "purchase":
                vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (r["ref_id"],)).fetchone()
                d = json.loads(r["details"] or "{}")
                items = "; ".join(f"{l['qty']} x {l['name']} {l['size']}" for l in d.get("lines", []))
                tickets = ", ".join(f"#{t}" for t in d.get("ticket_ids", []))
                pay_first = [x["id"] for x in conn.execute(
                    "SELECT id FROM invoices WHERE vendor_id = ? AND status = 'open'", (r["ref_id"],))]
                row.update(payee=vendor["name"], **{"for": f"Purchase order: {items} ({tickets})"},
                           due_date=r["created_at"], is_purchase=True, pay_first=pay_first)
            elif r["kind"] == "invoice":
                inv = conn.execute(
                    "SELECT i.description, i.due_date, v.name FROM invoices i "
                    "JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?", (r["ref_id"],)
                ).fetchone()
                row.update(payee=inv["name"], **{"for": inv["description"]}, due_date=inv["due_date"],
                           is_purchase=False)
            else:
                lease = conn.execute("SELECT * FROM leases WHERE id = ?", (r["ref_id"],)).fetchone()
                row.update(payee=lease["landlord"], **{"for": f"Rent: {lease['space_name']}"},
                           due_date=lease["next_due"], is_purchase=False)
            rows.append(row)
    return {"requests": rows}


@mcp.tool
def list_payments() -> dict:
    """List every payment actually made (payments table), with who approved it, and the total paid."""
    with closing(_connect_readonly()) as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM payments ORDER BY id")]
    return {"payments": rows, "total_paid": sum(r["amount"] for r in rows)}


@mcp.tool
def list_outbox(ticket_id: int | None = None) -> dict:
    """List simulated messages and vendor orders already written to the outbox.

    Args:
        ticket_id: Optional filter by ticket.
    """
    with closing(_connect_readonly()) as conn:
        if not _has_table(conn, "outbox"):
            return {"messages": []}
        sql, args = "SELECT * FROM outbox", ()
        if ticket_id is not None:
            sql, args = sql + " WHERE ticket_id = ?", (ticket_id,)
        rows = [dict(r) for r in conn.execute(sql + " ORDER BY id", args)]
    return {"messages": rows}


# --------------------------------------------------------------------------
# Write tools (agents)
# --------------------------------------------------------------------------

@mcp.tool
def request_payment(
    kind: Literal["invoice", "rent"], ref_id: int, reason: str, requested_by: str
) -> dict:
    """Ask a human to approve a payment. Does NOT move any money.

    The amount is read from the database (invoices.amount or
    leases.monthly_rent), so it can't be mistyped. Creates a 'pending' row in
    payment_requests. Refuses duplicates and anything already paid; rent is
    refused unless it is due within 7 days (so next month can't be paid early).

    Args:
        kind: 'invoice' (ref_id = invoices.id) or 'rent' (ref_id = leases.id).
        ref_id: The invoice or lease id.
        reason: One or two sentences the human will read before approving.
        requested_by: Name of the agent asking.
    """
    reason = _require_text(reason, "reason")
    requested_by = _require_text(requested_by, "requested_by")
    owner = {"invoice": "accounting", "rent": "facilities"}[kind]
    if requested_by != owner:
        raise ToolError(f"Only {owner} requests {kind} payments. Report it to the Boss instead.")
    with closing(_connect_rw()) as conn, conn:
        today = _today(conn)
        if kind == "invoice":
            inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (ref_id,)).fetchone()
            if inv is None:
                raise ToolError(f"No invoice with id={ref_id}.")
            if inv["status"] != "open":
                raise ToolError(f"Invoice {ref_id} is '{inv['status']}', not open.")
            amount = inv["amount"]
        else:
            lease = conn.execute("SELECT * FROM leases WHERE id = ?", (ref_id,)).fetchone()
            if lease is None:
                raise ToolError(f"No lease with id={ref_id}.")
            days = (date.fromisoformat(lease["next_due"]) - date.fromisoformat(today)).days
            if days > RENT_WINDOW_DAYS:
                paid_through = _add_days(lease["next_due"], -1)
                raise ToolError(
                    f"Rent for lease {ref_id} is already paid through {paid_through}. The next rent "
                    f"(${lease['monthly_rent']:,.0f}) is due {lease['next_due']}, {days} days away. Rent can "
                    f"only be requested within {RENT_WINDOW_DAYS} days of its due date. Do not pay it early."
                )
            amount = lease["monthly_rent"]
        dup = conn.execute(
            "SELECT id FROM payment_requests WHERE kind = ? AND ref_id = ? AND status = 'pending'",
            (kind, ref_id),
        ).fetchone()
        if dup:
            raise ToolError(f"Request {dup['id']} for this {kind} is already pending human approval.")
        cur = conn.execute(
            "INSERT INTO payment_requests (kind, ref_id, amount, reason, requested_by, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (kind, ref_id, amount, reason, requested_by, today),
        )
        request_id = cur.lastrowid
    return {
        "request_id": request_id,
        "kind": kind,
        "ref_id": ref_id,
        "amount": amount,
        "status": "pending",
        "note": "No money has moved. A human must approve this request.",
    }


class OrderLine(BaseModel):
    sku: str
    size: str
    qty: int = Field(gt=0)


@mcp.tool
def propose_vendor_order(
    vendor_id: int, lines: list[OrderLine], ticket_ids: list[int], reason: str, requested_by: str
) -> dict:
    """PROPOSE a restock purchase for the owner to approve. Nothing is ordered yet.

    Creates a pending purchase request (kind 'purchase') priced at qty x pricing.unit_cost
    per line. Only when the owner approves it is the (simulated) order placed and paid in one
    step; arrival = approval date + vendor lead_days. If rejected, nothing is ordered.
    Each ticket gets its OWN proposal, so the owner decides each one separately. A pending
    request is never changed by an agent. If the vendor has an unpaid invoice,
    the owner must pay that first (the approval is refused until then). No vendor is contacted.

    Args:
        vendor_id: vendors.id.
        lines: Items, e.g. [{"sku": "CC-TEE-WHITE", "size": "S", "qty": 1}].
        ticket_ids: Tickets this purchase serves.
        reason: One sentence the owner reads before approving.
        requested_by: Must be "inventory".
    """
    requested_by = _require_text(requested_by, "requested_by")
    reason = _require_text(reason, "reason")
    if requested_by != "inventory":
        raise ToolError("Only inventory proposes purchases. Report it to the Boss instead.")
    if not lines:
        raise ToolError("A purchase needs at least one line.")
    with closing(_connect_rw()) as conn, conn:
        today = _today(conn)
        vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if vendor is None:
            raise ToolError(f"No vendor with id={vendor_id}.")
        for r in conn.execute(
            "SELECT id, details FROM payment_requests WHERE kind = 'purchase' AND ref_id = ? AND status = 'pending'",
            (vendor_id,),
        ):
            overlap = set(json.loads(r["details"] or "{}").get("ticket_ids", [])) & set(ticket_ids)
            if overlap:
                raise ToolError(f"Purchase request {r['id']} for ticket(s) {sorted(overlap)} is already "
                                "waiting for the owner. Don't propose it again.")
        priced = []
        for line in lines:
            item = conn.execute(
                "SELECT i.name, p.unit_cost FROM inventory i JOIN pricing p ON p.sku = i.sku "
                "WHERE i.sku = ? AND i.size = ?", (line.sku, line.size)
            ).fetchone()
            if item is None:
                raise ToolError(f"No inventory item sku={line.sku!r}, size={line.size!r}.")
            priced.append({**line.model_dump(), "name": item["name"], "unit_cost": item["unit_cost"],
                           "line_total": round(line.qty * item["unit_cost"], 2)})
        amount = round(sum(l["line_total"] for l in priced), 2)
        details = json.dumps({"lines": priced, "ticket_ids": ticket_ids})
        request_id = conn.execute(
            "INSERT INTO payment_requests (kind, ref_id, amount, reason, requested_by, status, created_at, details) "
            "VALUES ('purchase', ?, ?, ?, ?, 'pending', ?, ?)",
            (vendor_id, amount, reason, requested_by, today, details),
        ).lastrowid
        blocking = [r["id"] for r in conn.execute(
            "SELECT id FROM invoices WHERE vendor_id = ? AND status = 'open'", (vendor_id,)
        )]
    return {
        "request_id": request_id,
        "vendor": vendor["name"],
        "lines": priced,
        "ticket_ids": ticket_ids,
        "amount": amount,
        "status": "pending",
        "pay_first": blocking,
        "arrival_if_approved_today": _add_days(today, vendor["lead_days"]),
        "note": "Nothing is ordered until the owner approves." +
                (f" Invoice(s) {blocking} must be paid first." if blocking else ""),
    }


@mcp.tool
def send_message(
    kind: Literal["customer_message", "landlord_message"],
    recipient: str,
    subject: str,
    body: str,
    ticket_id: int | None,
    sent_by: str,
) -> dict:
    """Write a SIMULATED message to the outbox. Nothing is emailed.

    Args:
        kind: 'customer_message' or 'landlord_message'.
        recipient: Name exactly as it appears in tickets.requester or leases.landlord.
        subject: Short subject line.
        body: Full message text.
        ticket_id: Ticket this message answers, if any.
        sent_by: Name of the agent writing it.
    """
    for value, field in ((recipient, "recipient"), (subject, "subject"), (body, "body"), (sent_by, "sent_by")):
        _require_text(value, field)
    if re.search(r"[\u0400-\u04ff\u0590-\u06ff\u0e00-\u0e7f\u3000-\u9fff\uac00-\ud7af\uff00-\uffef]", f"{subject} {body}"):
        raise ToolError("Message contains garbled non-English text. Rewrite it in plain English.")
    if kind == "customer_message":
        leaked = [t for t in INTERNAL_TERMS if t in f"{subject} {body}".lower()]
        if leaked:
            raise ToolError(f"Customer messages can't mention internal details {leaked}. "
                            "Rewrite it in 1-2 casual sentences: just availability, price, and timing.")
    with closing(_connect_rw()) as conn, conn:
        today = _today(conn)
        cur = conn.execute(
            "INSERT INTO outbox (kind, recipient, ticket_id, subject, body, sent_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, recipient.strip(), ticket_id, subject.strip(), body.strip(), sent_by.strip(), today),
        )
        outbox_id = cur.lastrowid
    return {"outbox_id": outbox_id, "simulated": True, "note": "Saved to outbox; nothing was sent."}


@mcp.tool
def update_ticket(
    ticket_id: int,
    status: Literal["open", "in_progress", "waiting_approval", "closed"],
    note: str,
    updated_by: str,
) -> dict:
    """Change a ticket's status and append a dated note to tickets.notes.

    Args:
        ticket_id: tickets.id.
        status: New status.
        note: What was done or what the ticket is waiting on.
        updated_by: Name of the agent.
    """
    note = _require_text(note, "note")
    updated_by = _require_text(updated_by, "updated_by")
    with closing(_connect_rw()) as conn, conn:
        today = _today(conn)
        t = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            raise ToolError(f"No ticket with id={ticket_id}.")
        notes = (t["notes"] or "") + f"\n[{today} {updated_by}] {status}: {note}"
        conn.execute("UPDATE tickets SET status = ?, notes = ? WHERE id = ?", (status, notes, ticket_id))
    return {"ticket_id": ticket_id, "old_status": t["status"], "new_status": status}


# --------------------------------------------------------------------------
# Human-only tools. The backend never gives these to an agent.
# --------------------------------------------------------------------------

@mcp.tool
def approve_payment(request_id: int, approved_by: str) -> dict:
    """HUMAN ONLY. Approve a pending payment request and pay it.

    In one transaction: inserts a `payments` row, lowers the checking balance, and
    marks the invoice 'paid', moves the lease's next_due ahead one month, or, for a
    purchase, places the (simulated) order with a paid invoice and starts the lead time.
    Refused if cash would go below zero, or if a purchase's vendor has an unpaid invoice.

    Args:
        request_id: payment_requests.id.
        approved_by: Full name of the human approving.
    """
    approved_by = _require_text(approved_by, "approved_by")
    with closing(_connect_rw()) as conn, conn:
        today = _today(conn)
        req = conn.execute("SELECT * FROM payment_requests WHERE id = ?", (request_id,)).fetchone()
        if req is None:
            raise ToolError(f"No payment request with id={request_id}.")
        if req["status"] != "pending":
            raise ToolError(f"Request {request_id} is already '{req['status']}'.")
        acct = conn.execute("SELECT * FROM cash_accounts WHERE name = 'checking'").fetchone()
        if acct["balance"] < req["amount"]:
            raise ToolError(f"Not enough cash: checking has {acct['balance']}, payment is {req['amount']}.")

        result = {}
        pay_ref = req["ref_id"]
        if req["kind"] == "purchase":
            vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (req["ref_id"],)).fetchone()
            unpaid = [r["id"] for r in conn.execute(
                "SELECT id FROM invoices WHERE vendor_id = ? AND status = 'open'", (vendor["id"],))]
            if unpaid:
                raise ToolError(f"{vendor['name']} won't take a new order until invoice(s) {unpaid} are paid. "
                                "Approve those first.")
            d = json.loads(req["details"] or "{}")
            items = "; ".join(f"{l['qty']} x {l['sku']} {l['size']}" for l in d.get("lines", []))
            tickets = ", ".join(f"#{t}" for t in d.get("ticket_ids", [])) or "none"
            eta = _add_days(today, vendor["lead_days"])
            pay_ref = conn.execute(
                "INSERT INTO invoices (vendor_id, amount, due_date, status, description) VALUES (?, ?, ?, 'paid', ?)",
                (vendor["id"], req["amount"], today, f"Purchase order: {items} (tickets {tickets})"),
            ).lastrowid
            outbox_id = conn.execute(
                "INSERT INTO outbox (kind, recipient, ticket_id, subject, body, sent_by, created_at) "
                "VALUES ('vendor_order', ?, ?, ?, ?, ?, ?)",
                (vendor["name"], (d.get("ticket_ids") or [None])[0], f"Purchase order (tickets {tickets})",
                 f"Order: {items}. Prepaid (invoice {pay_ref}, ${req['amount']:,.2f}). Expected arrival {eta}.",
                 f"human:{approved_by}", today),
            ).lastrowid
            result.update(order_placed=True, invoice_id=pay_ref, outbox_id=outbox_id, expected_arrival=eta)
        elif req["kind"] == "invoice":
            inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (req["ref_id"],)).fetchone()
            if inv["status"] != "open":
                raise ToolError(f"Invoice {inv['id']} is already '{inv['status']}'.")
            conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (inv["id"],))
            result["invoice_status"] = "paid"
        else:
            lease = conn.execute("SELECT * FROM leases WHERE id = ?", (req["ref_id"],)).fetchone()
            next_due = _add_month(lease["next_due"])
            conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (next_due, lease["id"]))
            result["lease_next_due"] = next_due

        new_balance = acct["balance"] - req["amount"]
        cur = conn.execute(
            "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) "
            "VALUES (?, ?, ?, 'checking', ?, ?)",
            (req["kind"], pay_ref, req["amount"], today, approved_by),
        )
        conn.execute("UPDATE cash_accounts SET balance = ?, date = ? WHERE name = 'checking'",
                     (new_balance, today))
        conn.execute(
            "UPDATE payment_requests SET status = 'approved', decided_by = ?, decided_at = ? WHERE id = ?",
            (approved_by, today, request_id),
        )
    return {"request_id": request_id, "payment_id": cur.lastrowid, "amount": req["amount"],
            "checking_balance": new_balance, "approved_by": approved_by, **result}


@mcp.tool
def reject_payment(request_id: int, rejected_by: str, reason: str) -> dict:
    """HUMAN ONLY. Reject a pending payment request. No money moves.

    Args:
        request_id: payment_requests.id.
        rejected_by: Full name of the human rejecting.
        reason: Why it was rejected.
    """
    rejected_by = _require_text(rejected_by, "rejected_by")
    with closing(_connect_rw()) as conn, conn:
        today = _today(conn)
        req = conn.execute("SELECT * FROM payment_requests WHERE id = ?", (request_id,)).fetchone()
        if req is None:
            raise ToolError(f"No payment request with id={request_id}.")
        if req["status"] != "pending":
            raise ToolError(f"Request {request_id} is already '{req['status']}'.")
        conn.execute(
            "UPDATE payment_requests SET status = 'rejected', decided_by = ?, decided_at = ?, "
            "decision_note = ? WHERE id = ?",
            (rejected_by, today, reason, request_id),
        )
    return {"request_id": request_id, "status": "rejected", "rejected_by": rejected_by}


if __name__ == "__main__":
    mcp.run(show_banner=False)
