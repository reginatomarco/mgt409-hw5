"""Facilities: the shop lease, rent schedule, and landlord communication."""

from agents.base import Role
from models import AgentReport

ROLE = Role(
    name="facilities",
    title="Facilities manager",
    job="Owns the Chapel Street lease: rent amount and due date, rent payment requests, simulated landlord messages.",
    mcp_tools=frozenset({
        "get_ticket",
        "get_lease",
        "get_cash_position",
        "request_payment",
        "list_payment_requests",
        "send_message",
        "update_ticket",
    }),
    output_type=AgentReport,
)
