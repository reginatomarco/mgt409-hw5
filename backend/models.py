"""Data types shared by the Campus Customs agent team."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
AGENT_NAMES: tuple[AgentName, ...] = ("boss", "inventory", "accounting", "facilities", "customer_service")

TicketStatus = Literal["open", "in_progress", "waiting_approval", "closed"]


# --------------------------------------------------------------------------
# Run-time dependencies passed to every agent (not sent to the model)
# --------------------------------------------------------------------------

@dataclass
class Delegation:
    """One hand-off between agents, kept for the run log."""

    from_agent: AgentName
    to_agent: AgentName
    task: str
    depth: int
    result: str = ""


@dataclass
class TeamDeps:
    """Who is running, how deep in the delegation chain, and the shared log.

    `chain` lists the agents already working on this request, so an agent can't
    hand work back to someone up the chain (no loops).
    """

    agent: AgentName
    run_id: str = ""  # one id per team run, shared by every delegated agent (audit trail)
    ticket_id: int | None = None  # set when the run targets one ticket (API runs)
    chain: list[AgentName] = field(default_factory=list)
    log: list[Delegation] = field(default_factory=list)
    delegated_to: list[AgentName] = field(default_factory=list)  # hand-offs made by THIS agent run

    @property
    def depth(self) -> int:
        return len(self.chain)


# --------------------------------------------------------------------------
# Agent outputs
# --------------------------------------------------------------------------

class PaymentRequestRef(BaseModel):
    """A payment an agent asked a human to approve (via request_payment)."""

    request_id: int
    kind: Literal["invoice", "rent", "purchase"]
    ref_id: int = Field(description="invoices.id, leases.id, or vendors.id for a purchase")
    amount: float = Field(description="Amount returned by the request_payment tool")


class AgentReport(BaseModel):
    """What a specialist agent returns to whoever delegated to it."""

    agent: AgentName
    ticket_ids: list[int] = Field(default_factory=list, description="Tickets this work was for")
    summary: str = Field(description="2-4 sentences: what was found and done, with the numbers from the tools")
    facts: list[str] = Field(default_factory=list, description="Key values read from tools, e.g. 'CC-HOOD-NAVY M qty 8'")
    actions_taken: list[str] = Field(default_factory=list, description="Writes made: payment requests, outbox ids, ticket updates")
    payment_requests: list[PaymentRequestRef] = Field(default_factory=list)
    blocked_on: list[str] = Field(default_factory=list, description="What must happen before this can finish (e.g. human approval)")


class TicketOutcome(BaseModel):
    """The Boss's verdict on one ticket."""

    ticket_id: int
    owner: AgentName = Field(description="Agent responsible for the ticket")
    status: TicketStatus
    resolution: str = Field(description="Max 20 words: what was found and done, with key numbers")
    next_step: str = Field(description="Max 10 words: who does what next ('none' if closed)")


class Decision(BaseModel):
    """One yes/no call the owner has to make."""

    ask: str = Field(description="Yes/no question, max 10 words, e.g. 'Pay $8 tee bill to Bulldog Print?'")
    request_id: int | None = Field(None, description="payment_requests.id when this is a payment")
    amount: float | None = Field(None, description="Dollar amount, from the tools")
    recommend: Literal["yes", "no"]
    why: str = Field(description="Max 12 words")


class TeamReport(BaseModel):
    """The Boss's final report for one run of the team. Short: the owner reads it at a glance."""

    date_today: str = Field(description="desk.date_today")
    headline: str = Field(description="Max 15 words: where things stand")
    decisions: list[Decision] = Field(default_factory=list, description="At most 3; empty if nothing needs the owner")
    tickets: list[TicketOutcome]
    cash_before: float = Field(description="Checking balance at start of the run, from the tools")
    cash_if_all_approved: float = Field(description="cash_before minus every payment in decisions")


# --------------------------------------------------------------------------
# FastAPI request / response bodies (backend/main.py)
# --------------------------------------------------------------------------

class TicketSummary(BaseModel):
    id: int
    type: str
    requester: str
    subject: str
    status: str = Field(description="Raw tickets.status: open, in_progress, waiting_approval, closed")
    state: Literal["open", "resolved"] = Field(description="resolved when status is closed")


class RunInfo(BaseModel):
    run_id: str
    ticket_id: int
    status: Literal["running", "done", "error"]
    started_utc: str
    finished_utc: str | None = None
    report: TeamReport | None = None
    usage: dict | None = None
    error: str | None = None


class AgentEvent(BaseModel):
    """One audit-trail entry, flattened for the board."""

    id: int = Field(description="Position in audit_trail.json; pass as ?after= to get only newer events")
    ts_utc: str
    run_id: str | None = None
    ticket_id: int | None = None
    depth: int | None = None
    agent: str
    event: str
    said: str | None = Field(None, description="What the agent said, was asked, or concluded")
    tools: list[dict] = Field(default_factory=list, description="Tools called (name + args) or tool results")
    output: dict | None = Field(None, description="run_end only: the agent's full structured report")


class ApproveBody(BaseModel):
    approved_by: str = Field(min_length=1, description="Full name of the human who clicked Approve")


class RejectBody(BaseModel):
    rejected_by: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class DecisionBody(BaseModel):
    """The owner's answer to a non-payment decision the Boss asked (e.g. a discount sign-off)."""

    ask: str = Field(min_length=1, description="The Boss's question, as shown on the board")
    answer: Literal["yes", "no"]
    decided_by: str = Field(min_length=1)


class ResolveBody(BaseModel):
    resolved_by: str = Field(min_length=1, description="Full name of the human closing the ticket")
    note: str = Field("Marked resolved on the desk board.", min_length=1)


class CashBalance(BaseModel):
    account: str
    balance: float
    as_of: str
    shop_date: str = Field(description="desk.date_today")
