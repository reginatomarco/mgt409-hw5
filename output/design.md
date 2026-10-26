# Campus Customs Desk: dashboard design

The board in `frontend/` (React + Vite + TypeScript) is built to feel like a **trading desk for a small shop**. One screen shows the work queue, the agents working live, the cash, and the decisions only a human can make.

Run it with `npm run dev` (http://localhost:5173). It talks to the FastAPI backend at http://localhost:8000.

---

## 1. Layout: three columns, read left to right like a workflow

| Column | What's there | Why |
|---|---|---|
| **Left: Queue** | The 3 tickets as cards with status chips. The selected card shows **▶ Deploy team** / **▶ Run follow-up** and **✔ Mark resolved**. | Work starts here: pick a ticket and send the team. |
| **Center: The Floor + Transcript** | The Boss on a wide "station" with the 4 specialists below, each showing what it's doing right now. Under them, a live transcript of the run. | The center of the screen goes to the most interesting thing: the agents working. |
| **Right: Checking · Approvals · Debrief** | Cash as a large hero number, the approval inbox, and each agent's summary for the selected ticket. | Money and decisions sit together, so the owner always sees the balance next to what they're about to approve. |

The page fills the screen with no page scroll. Each panel scrolls on its own, like a real terminal. Below 1200px wide, the right column moves under the others.

## 2. Look: dark "operations desk"

- **Dark theme only.** People sit at a desk like this for hours, and a dark board makes the colored agents and status chips stand out. Panels are `#14171d` on a near-black page `#0b0d11`.
- **Yale blue as the brand.** The CC logo tile uses Yale blue `#00356b`. The interactive accent (buttons, selection, the Boss) is the brighter dark-mode step `#3987e5`, so it stays readable on dark.
- **Graph-paper background.** A faint 32px grid with a navy glow in the corner gives the page a "control room" feel without competing with the content.
- **One sans font everywhere** (system UI). Numbers and the cash figure use it too. Monospace is only for machine text: tool calls, run ids, ticket ids, the model name.

## 3. Color rules (followed, not eyeballed)

- **Each agent has a fixed identity color.** Boss blue `#3987e5`, Inventory orange `#d95926`, Accounting aqua `#199e70`, Facilities amber `#c98500`, Customer Service magenta `#d55181`. These are slots 1–5 of a validated categorical palette, dark-mode steps. All five pass the lightness, chroma, and 3:1 contrast checks against the panel color.
- **Color is never the only cue.** I ran the palette validator: with all five on screen together, some pairs are too close for colorblind viewers (and amber vs. orange is close for everyone). So every agent always appears with its **name and a letter badge** (B, I, A, F, C). The color only reinforces that.
- **Status colors are reserved** and always come with an icon and a label: ● Open, ◐ In progress, ⏸ Needs approval, ✔ Resolved, plus ⚠ for warnings and ✕ for errors. Green / amber / orange / red are never reused for anything else.
- **Text stays in ink colors.** Labels and numbers are off-white, gray, or muted. The agent color sits on the badge or the card's left edge, never on body text.

## 4. Live behavior

- The board polls the backend every **1.5 s while a run is live** and every **4 s when idle**. Agent events are fetched incrementally (`/events?after=<last id>`), so each refresh only pulls new lines.
- Each agent's station reads the latest events of the current run and shows one of these states: *Picked up a task → Thinking… → Checking stock / Requesting your approval / Waiting on Accounting → Filing the report → ✔ Done*. Busy agents get a spinner, a pulsing ring around their badge, and a glow in their color.
- The transcript indents each delegation level, so you can see the Boss → Inventory → Accounting chain at a glance. Tool calls appear as code chips with their arguments. Tool results are collapsed and open on click.
- **Run tabs** (Run 1, Run 2…) keep the first run and the follow-up run after approvals separate.

## 5. Money and safety by design

- **Approvals inbox.** Each request shows a type tag (**Rent**, **Invoice**, or **Purchase bill**), the payee and what it's for, the agent's reason, who requested it, the due date, and **"Leaves $X in checking"** before you click.
- **Two-step approval.** **✔ Approve** becomes a glowing **"Confirm: pay $840.00"**. One stray click never moves money.
- **Signed by name.** Approving, rejecting, or resolving needs your full name in "Signed in as". It's saved in the browser and sent as `approved_by`, so the `payments` row and the audit trail record who signed. If the name is empty, the field shakes and the board tells you to sign in.
- **Can't overdraw.** If a request is bigger than the balance, the card turns red and the button reads **⚠ Not enough cash**. The server would refuse it anyway.
- **Cash meter.** Under the balance, a bar shows how much of checking the pending requests would use. It goes blue → amber → orange → red as the share grows, and it shows the balance left if you approve everything.
- **Paid runs are labeled.** The deploy button says "uses gpt-6-luna (paid)". Only one run can be live at a time, and **Reset DB** is also two-step and locked during a run.

## 6. The GIGACHAD choices 🗿

- **LIVE pill with a blinking red dot and a running timer** in the top bar ("LIVE · Ticket #101 · 0:42"), like a broadcast desk.
- **Spinning border on the live ticket card**, so you can always see which ticket the team is working on.
- **The cash drop.** After you approve, the balance counts down instead of jumping, and a red **▼ −$840** badge appears next to it and fades out.
- **RESOLVED rubber stamp.** Closing a ticket thumps a tilted green "RESOLVED" stamp onto the card.
- **Glowing confirm button.** The confirm step pulses green to signal that the next click pays.
- **Typing dots** at the bottom of the transcript while agents are working.
- **Keyboard keys 1 · 2 · 3** jump between tickets (each card shows its key). Desk operators don't need a mouse.
- **The Boss gets the corner office.** It has the wide station at the top of the Floor; the four specialists share the row below.
- **Toasts** for the important moments: "Team deployed on #103", "Team finished ticket #101. Check the debrief and approvals.", "Paid $840.00 to Bulldog Print Co. Signed by Marco Reginato."
- **Calm when it should be.** All motion turns off for users with reduced-motion settings. When idle, the board is quiet: "Desk idle", agents "At desk", and empty states that explain what will show up there.

## 7. How it maps to the requirements

| Requirement | Where |
|---|---|
| List all 3 tickets | Left Queue (`GET /tickets`) |
| Pick 1 ticket and start the team | Select a card, then **▶ Deploy team** (`POST /tickets/{id}/run`) |
| Show each agent and what it's saying or doing | The Floor + Transcript (`GET /events`, `GET /runs`) |
| Mark a ticket resolved when done | Status chip + RESOLVED stamp from the agents' `update_ticket`, or **✔ Mark resolved** (`POST /tickets/{id}/resolve`) |
| Short summary of what each agent did | Right column **Debrief**: the Boss's note to you, plan, next step, and risks, plus each specialist's summary, actions, and blockers |
| Human approves a payment or purchase | **Approvals** inbox, two-step approve (`POST /payments/{id}/approve`) or reject |
| Checking balance drops after an approved payment | **Checking** hero number (`GET /cash`), with a count-down animation and a −$ badge |
