"""Shared settings: the one allowed model, Portkey wiring, cost limits, MCP connection."""

import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

import httpx
from dotenv import load_dotenv
from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport
from openai import AsyncOpenAI
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

HW_ROOT = Path(__file__).resolve().parent.parent
COURSE_ROOT = HW_ROOT.parent.parent
PROMPTS_DIR = HW_ROOT / "backend" / "prompts"
MCP_SERVER = HW_ROOT / "mcp_server" / "server.py"
ORIGINAL_DB = HW_ROOT / "data" / "campus_customs.db"
WORKING_DB = HW_ROOT / "data" / "campus_customs_new.db"
OUTPUT_DIR = HW_ROOT / "output"

load_dotenv(HW_ROOT / ".env")  # PORTKEY_API_KEY (see .env.example); real env vars win
load_dotenv(COURSE_ROOT / ".env")

# The ONLY model allowed in this homework. Deliberately not configurable.
MODEL_NAME = "gpt-6-luna"

# Cost guards for one whole team run (Boss + every delegated agent share these).
USAGE_LIMITS = UsageLimits(request_limit=30, total_tokens_limit=80_000)
# Delegated agents stop earlier, leaving the Boss a reserve to write its report instead of crashing.
SUB_AGENT_LIMITS = UsageLimits(request_limit=26, total_tokens_limit=70_000)
# reasoning_effort='none': Azure's gpt-6-luna rejects function tools on /v1/chat/completions
# while reasoning is on (its default), and every agent here uses tools.
MODEL_SETTINGS = OpenAIChatModelSettings(max_tokens=800, openai_reasoning_effort="none")
MAX_DELEGATION_DEPTH = 3  # boss -> specialist -> specialist -> specialist


def luna_model() -> OpenAIChatModel:
    """gpt-6-luna, routed through the course Portkey gateway."""
    key = os.getenv("PORTKEY_API_KEY")
    if not key:
        raise RuntimeError("PORTKEY_API_KEY not found: copy .env.example to .env and paste your key")
    client = AsyncOpenAI(
        api_key=key,
        base_url="https://api.portkey.ai/v1",
        default_headers={"x-portkey-api-key": key},
        max_retries=0,  # a failed call is not silently retried (and paid for) again
        timeout=httpx.Timeout(90, connect=15),
    )
    model = OpenAIChatModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))
    assert model.model_name == "gpt-6-luna"
    return model


def reset_working_db() -> None:
    """Fresh clone of the untouched original; all writes go to the clone."""
    shutil.copyfile(ORIGINAL_DB, WORKING_DB)


def mcp_transport() -> PythonStdioTransport:
    return PythonStdioTransport(MCP_SERVER, python_cmd=sys.executable, cwd=str(HW_ROOT))


async def call_tool(tool: str, **args) -> dict:
    """One MCP tool call outside an agent (human actions, API reads)."""
    async with Client(mcp_transport()) as client:
        result = await client.call_tool(tool, args)
    return result.structured_content or {}


def mcp_toolset() -> MCPToolset:
    """One stdio connection to the campus-customs MCP server, shared by all agents."""
    return MCPToolset(Client(mcp_transport()))
