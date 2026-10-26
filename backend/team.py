"""Assembles the five agents and runs the team loop.

Loop: the Boss reads the open tickets, delegates to specialists (who may
delegate to each other), and returns a TeamReport. Payments are only
*requested*; a human approves them afterwards with backend/approvals.py, and a
follow-up run (--continue) lets the team finish the work those payments unblock.
"""

from dataclasses import dataclass, field

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage

import audit
from agents import accounting, boss, customer_service, facilities, inventory
from agents.base import Role, build_agent
from config import luna_model, mcp_toolset
from models import AgentName, Delegation, TeamDeps, TeamReport

ROLES: dict[AgentName, Role] = {
    r.name: r for r in (boss.ROLE, inventory.ROLE, accounting.ROLE, facilities.ROLE, customer_service.ROLE)
}

KICKOFF = (
    "Work every open ticket for Campus Customs. Start with get_open_tickets and get_cash_position, "
    "delegate each ticket to its owner, make sure every needed payment is requested for human "
    "approval, and return your TeamReport."
)
FOLLOW_UP = (
    "Follow-up run. A human has reviewed payment requests since the last run. Check "
    "list_payment_requests and get_open_tickets, then have the owners finish whatever the approved "
    "(or rejected) payments unblock: restock orders, customer updates, landlord confirmation, ticket "
    "status. Return your TeamReport."
)



def ticket_prompt(ticket_id: int) -> str:
    """Kickoff for one ticket. Also serves as the follow-up after human approvals."""
    return (
        f"Work ticket #{ticket_id} only. Call get_ticket({ticket_id}) first and follow its next_step "
        "exactly (if owner_waiting is true, call no agents). Don't start work on other tickets. "
        "Make sure every payment this ticket needs is requested for human approval, then return your "
        f"TeamReport (include only ticket #{ticket_id} in `tickets`)."
    )


@dataclass
class Team:
    agents: dict[AgentName, Agent]
    mcp: MCPToolset
    log: list[Delegation] = field(default_factory=list)

    run_id: str = ""

    async def run(
        self, prompt: str = KICKOFF, run_id: str | None = None, ticket_id: int | None = None
    ) -> tuple[TeamReport, RunUsage]:
        self.run_id = run_id or audit.new_run_id()
        async with self.mcp:  # one MCP server process for the whole run
            result = await audit.run_logged(
                self.agents["boss"],
                prompt,
                deps=TeamDeps(agent="boss", run_id=self.run_id, ticket_id=ticket_id, log=self.log),
            )
        return result.output, result.usage


def build_team(model: Model | None = None, mcp: MCPToolset | None = None) -> Team:
    """All agents use gpt-6-luna unless a test passes an offline model."""
    model = model or luna_model()
    mcp = mcp or mcp_toolset()
    agents: dict[AgentName, Agent] = {}
    for role in ROLES.values():
        agents[role.name] = build_agent(role, ROLES, agents, mcp, model)
    return Team(agents=agents, mcp=mcp)
