"""Builds one agent: its prompt file, its slice of the MCP tools, and the delegate tool.

Every agent can delegate to every other agent (full connectivity). Loops are
blocked by `TeamDeps.chain`: an agent can't hand work to itself or to anyone
already working on the same request, and the chain can't grow past
MAX_DELEGATION_DEPTH. All delegated runs share one usage counter, so the whole
team run stays under USAGE_LIMITS.
"""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext, Tool
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models import Model

import audit
from config import MAX_DELEGATION_DEPTH, MODEL_SETTINGS, PROMPTS_DIR, SUB_AGENT_LIMITS
from models import AGENT_NAMES, AgentName, Delegation, TeamDeps

# Scripts that never belong in this shop's English output (CJK, Hangul, Cyrillic, Arabic, Hebrew, Thai).
# The model occasionally emits garbage tokens; a report containing them is sent back for a rewrite.
GARBLE = re.compile(r"[\u0400-\u04ff\u0590-\u06ff\u0e00-\u0e7f\u3000-\u9fff\uac00-\ud7af\uff00-\uffef]")

# MCP tools only a human may call (via backend/approvals.py). Never given to an agent.
HUMAN_ONLY_TOOLS = frozenset({"approve_payment", "reject_payment"})


@dataclass(frozen=True)
class Role:
    """Static description of one team member."""

    name: AgentName
    title: str
    job: str  # one line, shown to colleagues in their delegate tool
    mcp_tools: frozenset[str]
    output_type: type[BaseModel]


def _delegate_tool(role: Role, roles: dict[AgentName, Role], team: dict[AgentName, Agent]) -> Tool:
    others = tuple(n for n in AGENT_NAMES if n != role.name)

    async def delegate(ctx: RunContext[TeamDeps], to: str, task: str) -> str:
        chain = [*ctx.deps.chain, role.name]
        refusal = None
        if to == role.name or to in chain:
            refusal = f"Refused: {to} is already working on this request (chain: {' -> '.join(chain)})."
        elif len(chain) > MAX_DELEGATION_DEPTH:
            refusal = f"Refused: delegation depth limit ({MAX_DELEGATION_DEPTH}) reached. Do the work yourself or report it as blocked."
        elif role.name == "boss" and to in ctx.deps.delegated_to:
            refusal = f"Refused: you already delegated to {to} in this run. Use their report; don't re-check."
        elif role.name != "boss" and ctx.deps.delegated_to:
            refusal = ("Refused: specialists may hand off at most once per task. Put what's needed in "
                       "`blocked_on` and the Boss will route it.")
        if refusal:
            audit.append({"run_id": ctx.deps.run_id, "ticket_id": ctx.deps.ticket_id,
                          "agent": role.name, "chain": ctx.deps.chain,
                          "event": "delegation_refused", "to": to, "task": task, "reason": refusal})
            return refusal
        entry = Delegation(from_agent=role.name, to_agent=to, task=task, depth=len(chain))
        ctx.deps.log.append(entry)
        ctx.deps.delegated_to.append(to)
        try:
            result = await audit.run_logged(
                team[to],
                task,
                deps=TeamDeps(agent=to, run_id=ctx.deps.run_id, ticket_id=ctx.deps.ticket_id,
                              chain=chain, log=ctx.deps.log),
                usage=ctx.usage,  # shared counter: one budget for the whole team run
                limits=SUB_AGENT_LIMITS,  # stops before the team cap, so the caller can still report
            )
        except UsageLimitExceeded:
            entry.result = (f"{to} stopped: this run's budget is nearly used up. Don't delegate again. "
                            "Write your report now with what you have, and list unfinished work as next steps.")
            return entry.result
        entry.result = result.output.model_dump_json()
        return entry.result

    delegate.__annotations__["to"] = Literal[others]
    roster = "\n".join(f"- {n}: {roles[n].title}. {roles[n].job}" for n in others)
    return Tool(
        delegate,
        name="delegate",
        description=(
            "Hand a task to a colleague and wait for their report. Give a self-contained task: "
            "ticket ids, SKUs, sizes, quantities, amounts, and exactly what you need back.\n"
            f"Colleagues:\n{roster}"
        ),
    )


def build_agent(
    role: Role,
    roles: dict[AgentName, Role],
    team: dict[AgentName, Agent],
    mcp: MCPToolset,
    model: Model,
) -> Agent[TeamDeps, BaseModel]:
    leaked = role.mcp_tools & HUMAN_ONLY_TOOLS
    if leaked:
        raise ValueError(f"{role.name} must not get human-only tools: {sorted(leaked)}")
    prompt = (PROMPTS_DIR / f"{role.name}.md").read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(f"Empty prompt file for {role.name}")
    allowed = role.mcp_tools
    agent = Agent(
        model,
        name=role.name,
        instructions=prompt,
        deps_type=TeamDeps,
        output_type=role.output_type,
        toolsets=[mcp.filtered(lambda ctx, td: td.name in allowed)],
        tools=[_delegate_tool(role, roles, team)],
        model_settings=MODEL_SETTINGS,
        retries=2,
    )

    @agent.output_validator
    def plain_english(output: BaseModel) -> BaseModel:
        if GARBLE.search(output.model_dump_json()):
            raise ModelRetry("Your report contains garbled non-English text. Rewrite it in plain English only.")
        return output

    return agent
