# Campus Customs — Agent Ops Desk

```
                         ▄▄▄▄████████████▄▄▄
                     ▄▄████████████████████████▄
                   ▄████████████████████████████▄
                  ██████████▀▀▀▀▀▀▀▀▀▀▀██████████▌
                 ▐███████▀                ▀███████
                 ████████    ▄▄▄▄    ▄▄▄▄   ███████
                 ███████▌  ▀▀████▀  ▀████▀▀ ▐██████
                 ▐██████     ▀▀▀      ▀▀▀    ██████
                  █████▌         ▐▌          ▐████
                  ▐████          ▐█▌          ████▌
                   ████         ▄██▄         ▐███
                   ▐███▄      ▀▀▀▀▀▀▀       ▄███▌
                    █████▄   ▀▀██████▀▀   ▄█████
                    ▐███████▄▄       ▄▄▄██████▌
                     ████████████████████████
                      ▀████████████████████▀
                        ▀████████████████▀
                           ▀▀████████▀▀
                    ▄▄▄▄▄▄▄▄▄▄▄████▄▄▄▄▄▄▄▄▄▄▄
               ▄▄████████████████████████████████▄▄
            ▄████████████████████████████████████████▄
          ▄████████████████████████████████████████████▄
```

> **"Average multi-agent system:** burns 500k tokens, emails the customer about overdue vendor invoices, pays rent twice.
> **GIGACHAD Campus Customs:** five agents, $152 left in checking, and the owner signs off on every dollar.
> Yes, he *will* be accepting full marks. No, he does *not* need a discount."
>
> — Boss agent, `gpt-6-luna`, at exactly 800 output tokens

A five-agent team (Boss, Inventory, Accounting, Facilities, Customer Service) that works the shop's tickets through an MCP server, with a FastAPI backend and a React board where the owner approves every payment. All agents use `gpt-6-luna` via Portkey. Customer, landlord and vendor messages are simulated (written to the `outbox` table); nothing is actually sent.

Full details: [`output/harness.md`](output/harness.md).

## Layout

| Path | What |
|---|---|
| `data/campus_customs.db` | Original database. **Never modified.** |
| `data/campus_customs_new.db` | Working copy. All agent writes go here. |
| `mcp_server/` | MCP server (18 tools) over the working DB |
| `backend/` | Agents (`agents/`, `prompts/`), data types (`models.py`), FastAPI app (`main.py`) |
| `frontend/` | React + Vite + TypeScript board |
| `output/` | Harness, evidence, audit trail, results |

## Setup (once)

```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env        # then paste your PORTKEY_API_KEY into .env
```

## 1. Copy the original DB to the working copy (clean run)

Whenever you want a clean run, overwrite the working copy with the original:

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

(Same as the **Reset DB** button on the board, or `POST /reset`.) The original is never written to.

## 2. Start the MCP server

The backend starts the MCP server for you (stdio) and keeps one connection open, so there is nothing separate to run for the board. To run it on its own, or to use it from Claude Code:

```bash
python mcp_server/server.py
```

Claude Code picks it up automatically from `.mcp.json` at the project root (server name `campus-customs`).

## 3. Start the FastAPI backend

```bash
cd backend
uvicorn main:app --port 8000
```

API docs: http://localhost:8000/docs

## 4. Start the React board

In a second terminal:

```bash
cd frontend
npm run dev
```

Open http://localhost:5173.

## 5. Reset the DB before a full three-ticket run

Before running all three tickets (#101, #102, #103) from the start, click **Reset DB** in the board's top bar (or run step 1). Then, for each ticket:

1. Select it in the queue and click **▶ Deploy team**.
2. Decide what's in **Your call** (approve/reject payments and purchases) and **Boss says** (yes/no questions).
3. Click **▶ Run follow-up** until the ticket shows **RESOLVED**.

The audit trail (`output/audit_trail.json`) is append-only and is never reset.

## Results

Final runs: all three tickets closed; checking $3,400 → $152. See `output/desk_tickets.html` (Expected vs Actual, Cash, Reflection), `output/resolved_tickets.json`, and `output/resolved_board.html`.
