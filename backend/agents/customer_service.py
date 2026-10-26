"""Customer Service: customer orders, quotes and discounts, and (simulated) replies."""

from agents.base import Role
from models import AgentReport

ROLE = Role(
    name="customer_service",
    title="Customer service lead",
    job="Owns customer and student-org tickets: quotes prices and discounts above cost, writes simulated customer replies, updates tickets.",
    mcp_tools=frozenset({
        "get_ticket",
        "check_inventory",
        "quote_price",
        "send_message",
        "update_ticket",
        "list_outbox",
    }),
    output_type=AgentReport,
)
