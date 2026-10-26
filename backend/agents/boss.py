"""Boss: triages every open ticket, routes work, and reports to the human owner."""

from agents.base import Role
from models import TeamReport

ROLE = Role(
    name="boss",
    title="Store manager",
    job="Triages tickets, assigns owners, checks the cash plan, writes the final report for the human.",
    mcp_tools=frozenset({
        "get_ticket",
        "list_payments",
        "get_open_tickets",
        "get_cash_position",
        "list_payment_requests",
        "list_outbox",
    }),
    output_type=TeamReport,
)
