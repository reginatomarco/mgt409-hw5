"""Campus Customs backend API for the React board.

    cd backend
    uvicorn main:app --reload --port 8000      # docs at http://localhost:8000/docs

Every shop fact comes from the MCP server over one long-lived stdio connection
(opened at startup); the API never opens the database itself. Agent runs use gpt-6-luna via Portkey and cost money,
so only one run can be active at a time. Money moves only through the approve
route, which needs the name of the human who clicked Approve.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import Client
from fastmcp.exceptions import ToolError

import audit
from config import mcp_transport, reset_working_db
from models import (
    AgentEvent,
    ApproveBody,
    CashBalance,
    DecisionBody,
    RejectBody,
    ResolveBody,
    RunInfo,
    TicketSummary,
)
from team import build_team, ticket_prompt

_client: Client | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start the MCP server once and reuse it (a new process per call takes seconds)."""
    global _client
    async with Client(mcp_transport()) as client:
        _client = client
        yield
    _client = None


app = FastAPI(title="Campus Customs desk API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                   "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

RUNS: dict[str, RunInfo] = {}
_tasks: set[asyncio.Task] = set()  # keep references so background runs aren't garbage-collected


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _active_run() -> RunInfo | None:
    return next((r for r in RUNS.values() if r.status == "running"), None)


async def _mcp(tool: str, **args) -> dict:
    """Call an MCP tool; a tool refusal becomes HTTP 400 with the server's message."""
    assert _client is not None, "MCP client not started"
    try:
        result = await _client.call_tool(tool, args)
        return result.structured_content or {}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --------------------------------------------------------------------------
# Tickets and agent runs
# --------------------------------------------------------------------------

@app.get("/tickets", response_model=list[TicketSummary])
async def list_tickets():
    """All tickets, each marked open or resolved."""
    data = await _mcp("list_tickets")
    return [
        TicketSummary(id=t["id"], type=t["type"], requester=t["requester"], subject=t["subject"],
                      status=t["status"], state="resolved" if t["resolved"] else "open")
        for t in data["tickets"]
    ]


async def _run_team(info: RunInfo) -> None:
    try:
        team = build_team()
        report, usage = await team.run(ticket_prompt(info.ticket_id), run_id=info.run_id, ticket_id=info.ticket_id)
        info.report = report
        info.usage = {"requests": usage.requests, "input_tokens": usage.input_tokens,
                      "output_tokens": usage.output_tokens}
        info.status = "done"
    except Exception as e:  # already written to the audit trail as run_error where it happened
        info.status, info.error = "error", f"{type(e).__name__}: {e}"
    finally:
        info.finished_utc = _now()


@app.post("/tickets/{ticket_id}/run", response_model=RunInfo, status_code=202)
async def run_ticket(ticket_id: int):
    """Start the agent team on one ticket (background). Poll /runs/{run_id} and /events."""
    if (busy := _active_run()) is not None:
        raise HTTPException(409, f"Run {busy.run_id} (ticket #{busy.ticket_id}) is still running.")
    ids = {t["id"] for t in (await _mcp("list_tickets"))["tickets"]}
    if ticket_id not in ids:
        raise HTTPException(404, f"No ticket #{ticket_id}.")
    info = RunInfo(run_id=audit.new_run_id(), ticket_id=ticket_id, status="running", started_utc=_now())
    RUNS[info.run_id] = info
    task = asyncio.create_task(_run_team(info))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return info


@app.post("/tickets/{ticket_id}/resolve")
async def resolve_ticket(ticket_id: int, body: ResolveBody):
    """Human marks a ticket resolved (status closed) from the board.

    Customer tickets can't be closed until the customer has been messaged (outbox).
    """
    who = body.resolved_by.strip()
    t = (await _mcp("get_ticket", ticket_id=ticket_id))["ticket"]
    if t["type"] in ("customer_order", "price_override") and not any(
        m["kind"] == "customer_message" for m in t.get("outbox", [])
    ):
        raise HTTPException(409, f"{t['requester']} hasn't been told the outcome yet. "
                                 "Run a follow-up so Customer Service replies first.")
    result = await _mcp("update_ticket", ticket_id=ticket_id, status="closed",
                        note=body.note, updated_by=f"human:{who}")
    audit.append({"agent": "human", "event": "ticket_resolved", "actor": who, "via": "api",
                  "ticket_id": ticket_id, "result": result})
    return result


@app.post("/tickets/{ticket_id}/decision")
async def decide(ticket_id: int, body: DecisionBody):
    """Owner answers a Boss yes/no question that isn't a payment. Saved as a ticket note via MCP,
    so the next run sees it; the ticket's status doesn't change."""
    who = body.decided_by.strip()
    ticket = next((t for t in (await _mcp("list_tickets"))["tickets"] if t["id"] == ticket_id), None)
    if ticket is None:
        raise HTTPException(404, f"No ticket #{ticket_id}.")
    note = f"OWNER DECISION: {body.answer.upper()} to \"{body.ask}\""
    result = await _mcp("update_ticket", ticket_id=ticket_id, status=ticket["status"],
                        note=note, updated_by=f"human:{who}")
    audit.append({"agent": "human", "event": "owner_decision", "actor": who, "via": "api",
                  "ticket_id": ticket_id, "ask": body.ask, "answer": body.answer, "note": note})
    return result


@app.get("/runs", response_model=list[RunInfo])
async def list_runs():
    """Runs started in this server session, newest first (the board uses it to find an active run)."""
    return sorted(RUNS.values(), key=lambda r: r.started_utc, reverse=True)


@app.get("/runs/{run_id}", response_model=RunInfo)
async def get_run(run_id: str):
    """Status of one run; includes the Boss's TeamReport when done."""
    if run_id not in RUNS:
        raise HTTPException(404, f"No run {run_id} in this server session.")
    return RUNS[run_id]


# --------------------------------------------------------------------------
# Agent events (from output/audit_trail.json)
# --------------------------------------------------------------------------

def _preview(value, n: int = 280) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= n else text[:n] + "…"


def _flatten(i: int, e: dict) -> AgentEvent:
    said, tools, output = None, [], None
    kind = e.get("event", "")
    if kind == "run_start":
        said = e.get("task")
    elif kind == "model_response":
        # Raw model text is scratch work (kept in the audit trail, not shown on the board).
        tools = [{"tool": p["tool"], "args": p["args"]} for p in e.get("parts", []) if p["type"] == "tool_call"]
    elif kind == "model_request":
        tools = [{"tool": p.get("tool"),
                  "result": _preview(p.get("content")) if p["type"] == "tool_result" else None,
                  "error": _preview(p.get("error")) if p.get("error") else None}
                 for p in e.get("parts", []) if p["type"] in ("tool_result", "retry")]
    elif kind == "run_end":
        output = e.get("output") or {}
        said = output.get("headline") or output.get("summary")
    elif kind in ("run_error", "delegation_refused"):
        said = e.get("error") or e.get("reason")
    elif kind in ("payment_approved", "payment_rejected", "db_reset", "ticket_resolved", "owner_decision"):
        said = e.get("note") or f"{e.get('actor', 'human')}: {kind.replace('_', ' ')}"
    return AgentEvent(id=i, ts_utc=e.get("ts_utc", ""), run_id=e.get("run_id"), ticket_id=e.get("ticket_id"),
                      depth=e.get("depth"), agent=e.get("agent", "?"), event=kind, said=said,
                      tools=tools, output=output)


@app.get("/events", response_model=list[AgentEvent])
async def recent_events(
    limit: int = Query(50, ge=1, le=500),
    after: int = Query(-1, description="Only events with id > after (for incremental refresh)"),
    run_id: str | None = None,
    ticket_id: int | None = None,
):
    """Most recent agent events: what each agent said and which tools it used."""
    if not audit.AUDIT_PATH.exists():
        return []
    events = None
    for _ in range(10):  # the file may be mid-append for a few ms
        try:
            events = json.loads(audit.AUDIT_PATH.read_text(encoding="utf-8"))
            break
        except (json.JSONDecodeError, PermissionError):
            await asyncio.sleep(0.05)
    if events is None:
        raise HTTPException(503, "Audit trail is busy; try again.")
    rows = [(i, e) for i, e in enumerate(events)
            if i > after
            and (run_id is None or e.get("run_id") == run_id)
            and (ticket_id is None or e.get("ticket_id") == ticket_id)]
    return [_flatten(i, e) for i, e in rows[-limit:]]


# --------------------------------------------------------------------------
# Payments (human approval) and cash
# --------------------------------------------------------------------------

@app.get("/payments")
async def payment_requests(status: str | None = Query("pending", pattern="^(pending|approved|rejected)$")):
    """Payment and purchase-bill requests waiting for (or decided by) a human."""
    return await _mcp("list_payment_requests", status=status)


@app.post("/payments/{request_id}/approve")
async def approve(request_id: int, body: ApproveBody):
    """Human clicked Approve: pay the rent, invoice, or purchase bill. Money moves here only."""
    pending = (await _mcp("list_payment_requests", status="pending"))["requests"]
    req = next((r for r in pending if r["id"] == request_id), None)
    if req is None:
        raise HTTPException(404, f"No pending payment request {request_id}.")
    result = await _mcp("approve_payment", request_id=request_id, approved_by=body.approved_by.strip())
    audit.append({"agent": "human", "event": "payment_approved", "actor": body.approved_by.strip(),
                  "via": "api", "request": req, "result": result})
    return result


@app.post("/payments/{request_id}/reject")
async def reject(request_id: int, body: RejectBody):
    """Human clicked Reject. No money moves."""
    result = await _mcp("reject_payment", request_id=request_id,
                        rejected_by=body.rejected_by.strip(), reason=body.reason)
    audit.append({"agent": "human", "event": "payment_rejected", "actor": body.rejected_by.strip(),
                  "via": "api", "request_id": request_id, "reason": body.reason, "result": result})
    return result


@app.get("/cash", response_model=CashBalance)
async def cash():
    """Current checking balance from cash_accounts."""
    data = await _mcp("get_cash_position")
    acct = next(a for a in data["cash_accounts"] if a["name"] == "checking")
    return CashBalance(account=acct["name"], balance=acct["balance"], as_of=acct["date"],
                       shop_date=data["date_today"])


# --------------------------------------------------------------------------
# Reset
# --------------------------------------------------------------------------

@app.post("/reset")
async def reset():
    """Re-copy data/campus_customs.db over the working copy. The audit trail is kept (append-only)."""
    if (busy := _active_run()) is not None:
        raise HTTPException(409, f"Can't reset while run {busy.run_id} is in progress.")
    reset_working_db()
    audit.append({"agent": "human", "event": "db_reset", "via": "api",
                  "note": "Working DB reset from data/campus_customs.db"})
    return {"reset": True, "working_db": "data/campus_customs_new.db", "source": "data/campus_customs.db"}
