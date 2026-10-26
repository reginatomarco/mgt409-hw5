"""Human payment approval. The only path by which money leaves the account.

    python backend/approvals.py list
    python backend/approvals.py approve 1 --by "Marco Reginato"
    python backend/approvals.py reject 2 --by "Marco Reginato" --reason "Wait until Monday"

Calls the MCP server's human-only tools; no agent or LLM is involved.
"""

import argparse
import asyncio
import json
import sys

import audit
from config import call_tool as call


async def main(a: argparse.Namespace) -> None:
    if a.cmd == "list":
        out = await call("list_payment_requests", status="pending")
    elif a.cmd == "approve":
        req = next((r for r in (await call("list_payment_requests", status="pending"))["requests"]
                    if r["id"] == a.request_id), None)
        if req is None:
            sys.exit(f"No pending request {a.request_id}.")
        print(f"Pay {req['kind']} {req['ref_id']}: ${req['amount']:,.2f}\n  Reason: {req['reason']}")
        if input("Type YES to approve: ").strip() != "YES":
            sys.exit("Not approved.")
        out = await call("approve_payment", request_id=a.request_id, approved_by=a.by)
        audit.append({"agent": "human", "event": "payment_approved", "actor": a.by,
                      "request": req, "result": out})
    else:
        out = await call("reject_payment", request_id=a.request_id, rejected_by=a.by, reason=a.reason)
        audit.append({"agent": "human", "event": "payment_rejected", "actor": a.by,
                      "request_id": a.request_id, "reason": a.reason, "result": out})
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for cmd in ("approve", "reject"):
        s = sub.add_parser(cmd)
        s.add_argument("request_id", type=int)
        s.add_argument("--by", required=True, help="full name of the human deciding")
        if cmd == "reject":
            s.add_argument("--reason", required=True)
    asyncio.run(main(p.parse_args()))
