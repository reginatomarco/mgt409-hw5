"""Accounting: cash position, vendor invoices, and payment requests for human approval."""

from agents.base import Role
from models import AgentReport

ROLE = Role(
    name="accounting",
    title="Accountant",
    job="Owns cash and vendor invoices: checks the balance, flags overdue bills, requests human approval to pay invoices.",
    mcp_tools=frozenset({
        "list_payments",
        "get_cash_position",
        "get_vendor_status",
        "request_payment",
        "list_payment_requests",
    }),
    output_type=AgentReport,
)
