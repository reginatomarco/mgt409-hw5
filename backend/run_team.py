"""Run the agent team once and save the report.

    python backend/run_team.py              # reset the working DB, then run
    python backend/run_team.py --continue   # keep the DB (after human approvals), follow-up run

Uses gpt-6-luna through Portkey: every run costs money.
"""

import argparse
import asyncio
import json
from dataclasses import asdict

from config import MODEL_NAME, ORIGINAL_DB, OUTPUT_DIR, WORKING_DB, reset_working_db
from team import FOLLOW_UP, KICKOFF, build_team


def reset_db() -> None:
    reset_working_db()
    print(f"Reset {WORKING_DB.name} from {ORIGINAL_DB.name}")


async def main(follow_up: bool) -> None:
    if not follow_up:
        reset_db()
    team = build_team()
    report, usage = await team.run(FOLLOW_UP if follow_up else KICKOFF)
    out = OUTPUT_DIR / ("run_followup.json" if follow_up else "run_report.json")
    out.write_text(json.dumps({
        "run_id": team.run_id,
        "model": MODEL_NAME,
        "report": report.model_dump(),
        "delegations": [asdict(d) for d in team.log],
        "usage": {"requests": usage.requests, "input_tokens": usage.input_tokens,
                  "output_tokens": usage.output_tokens},
    }, indent=2), encoding="utf-8")
    print(report.model_dump_json(indent=2))
    print(f"\nSaved {out}. Pending payments: python backend/approvals.py list")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--continue", dest="follow_up", action="store_true",
                        help="don't reset the DB; finish work unblocked by approvals")
    asyncio.run(main(parser.parse_args().follow_up))
