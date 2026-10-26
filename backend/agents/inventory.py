"""Inventory: stock levels, vendor readiness, lead times, and simulated restock orders."""

from agents.base import Role
from models import AgentReport

ROLE = Role(
    name="inventory",
    title="Inventory manager",
    job="Checks stock by SKU and size, picks the vendor, checks if it can ship, gives arrival dates, proposes restock purchases for the owner to approve.",
    mcp_tools=frozenset({
        "get_ticket",
        "check_inventory",
        "list_inventory",
        "get_vendor_status",
        "propose_vendor_order",
        "list_outbox",
    }),
    output_type=AgentReport,
)
