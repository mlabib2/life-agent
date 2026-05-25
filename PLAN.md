# Life Agent — Phase-by-Phase Implementation Plan

> This is the working build checklist. Each phase produces a deployable, testable slice of the system.
> Complete every checkbox before moving to the next phase. Tick boxes as you go.

---

## How to Use This Document

- Work top-to-bottom within each phase; items are ordered by dependency.
- `[ ]` = not started · `[x]` = done · `[~]` = in progress / blocked
- If a step fails, note what happened in a comment below the checkbox before skipping.
- Each phase ends with a **Verification Gate** — a concrete test you can run to confirm the phase works end-to-end before proceeding.

---

## Phase 0 — Repo & Environment Setup

**Goal:** Working local dev environment, secrets wired, repo live on GitHub.

### 0.1 — System Prerequisites
- [ ] Python 3.12 installed (`python3 --version`)
- [ ] Docker Desktop installed and running (`docker --version`)
- [ ] Git configured (`git config user.name`, `git config user.email`)
- [ ] GitHub account logged in (`gh auth login` or SSH key added)

### 0.2 — API Keys & Accounts
- [x] Create Telegram bot via @BotFather → save `TELEGRAM_BOT_TOKEN`
- [x] Get your Telegram user ID (message @userinfobot) → save `TELEGRAM_USER_ID`
- [x] Get Anthropic API key from console.anthropic.com → save `ANTHROPIC_API_KEY`
- [x] Get Tavily API key from app.tavily.com → save `TAVILY_API_KEY`
- [ ] Get OpenAI API key from platform.openai.com (for Whisper, Phase 10) → save `OPENAI_API_KEY` _(deferred — not needed until Phase 10)_
- [x] In Supabase: create dedicated `life-agent` project → copy `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
- [ ] Create DigitalOcean droplet ($4/mo, Ubuntu 22.04 LTS, any datacenter) → note the IP

### 0.3 — Local Project Structure
- [x] `cd ~/Desktop/Technical_Projects/Life-Agent`
- [x] Create directory structure (Dockerfile, docker-compose.yml, requirements.txt, .env.example, .github/workflows/deploy.yml all exist)
- [x] Populate `.env` with all real keys (never commit `.env`)
- [x] Confirm `.gitignore` covers: `.env`, `*.db`, `__pycache__/`, `.DS_Store`, `spread_commits.py`

### 0.4 — Supabase Schema
Run the following SQL in the Supabase SQL Editor (Dashboard → SQL Editor → New query):

- [x] Create `users` table:
  ```sql
  CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT UNIQUE NOT NULL,
    name TEXT,
    timezone TEXT DEFAULT 'UTC',
    wake_time TIME DEFAULT '07:00',
    sleep_target_time TIME DEFAULT '23:00',
    tone_preference TEXT DEFAULT 'flexible',
    google_refresh_token TEXT,
    strava_refresh_token TEXT,
    onboarding_complete BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```
- [x] Create `goals` table:
  ```sql
  CREATE TABLE goals (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    timeframe TEXT,
    category TEXT,
    is_non_negotiable BOOLEAN DEFAULT FALSE,
    target_per_week INT,
    current_streak INT DEFAULT 0,
    longest_streak INT DEFAULT 0,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```
- [x] Create `logs` table:
  ```sql
  CREATE TABLE logs (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    date DATE NOT NULL,
    goal_id INT REFERENCES goals(id) ON DELETE SET NULL,
    data JSONB,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
  );
  CREATE INDEX idx_logs_user_date ON logs(user_id, date);
  ```
- [x] Create `records` table:
  ```sql
  CREATE TABLE records (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    date DATE NOT NULL,
    data JSONB,
    source TEXT,
    file_url TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
  );
  CREATE INDEX idx_records_user_type_date ON records(user_id, type, date);
  ```
- [x] Create `events` table:
  ```sql
  CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    date DATE NOT NULL,
    type TEXT,
    source TEXT DEFAULT 'manual',
    notes TEXT
  );
  ```
- [x] Create `domains` table:
  ```sql
  CREATE TABLE domains (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    display_name TEXT,
    active BOOLEAN DEFAULT TRUE,
    evening_prompt TEXT,
    context_decay_days INT DEFAULT 14,
    nudge_after_days INT,
    system_prompt_snippet TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```
- [x] Create `conversations` table:
  ```sql
  CREATE TABLE conversations (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW()
  );
  CREATE INDEX idx_conversations_user_timestamp ON conversations(user_id, timestamp);
  ```
- [x] Verify all 7 tables appear in Supabase Table Editor

### 0.5 — GitHub Remote
- [ ] Create new **public** repo on GitHub named `life-agent`
- [ ] `git remote add origin git@github.com:<your-username>/life-agent.git`
- [ ] `git push -u origin main`
- [ ] Confirm `.env` and `*.db` are not visible in the GitHub repo

### 0.6 — GitHub Actions Secrets
In GitHub repo → Settings → Secrets and variables → Actions:
- [ ] Add secret `DROPLET_IP` (your DigitalOcean IP)
- [ ] Add secret `SSH_PRIVATE_KEY` (contents of `~/.ssh/id_rsa` or your deploy key)

### ✅ Phase 0 Verification Gate
```bash
# All tables present:
# Go to Supabase dashboard → Table Editor → confirm all 7 tables exist

# Repo is live:
git log --oneline | head -5
# Confirm commits are showing on GitHub
```

---

## Phase 1 — Skeleton: Telegram Bot + Health Check

**Goal:** Working Telegram bot that receives messages, validates sender, and replies. No Claude yet.

### 1.1 — Dependencies
- [x] Add to `requirements.txt`:
  ```
  python-telegram-bot==21.6
  fastapi==0.115.0
  uvicorn[standard]==0.32.0
  asyncpg==0.30.0
  sqlalchemy[asyncio]==2.0.36
  pydantic==2.9.2
  pydantic-settings==2.6.0
  apscheduler==3.10.4
  httpx==0.27.2
  python-dotenv==1.0.1
  anthropic==0.39.0
  tavily-python==0.5.0
  supabase==2.9.1
  ```
- [x] `pip install -r requirements.txt` — verify no errors

### 1.2 — config.py ✅
- [x] Implement `Settings` class using `pydantic-settings`:
  - Fields: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_USER_ID` (int), `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`, `OPENAI_API_KEY`, `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
  - Load from `.env` file
  - Export a singleton `settings` instance
- [x] Required fields fail loudly at startup if missing (pydantic handles this automatically)

### 1.3 — db.py (connection only)
- [x] Supabase client singleton via `get_db()`
- [x] `init_db()` verifies connection on startup, logs "Database connected"

### 1.4 — bot.py (skeleton)
- [x] `Application` built using `python-telegram-bot`
- [x] `_is_authorized()` security guard — silently drops any message not from `TELEGRAM_USER_ID`
- [x] `handle_message()` — echoes message back to confirm pipeline works
- [x] Long polling (no webhook)

### 1.5 — FastAPI health endpoint
- [x] `GET /health` returns `{"status": "ok", "timestamp": <iso_datetime>}`

### 1.6 — main.py entry point
- [x] FastAPI lifespan starts DB + bot polling on startup, shuts down cleanly on exit
- [x] uvicorn runs on port 8000

### 1.7 — Docker
- [x] `Dockerfile` and `docker-compose.yml` already written (from Phase 0)
- [ ] `docker-compose up --build` — confirm container starts without errors _(deferred — do after DigitalOcean droplet is set up)_

### 1.8 — GitHub Actions CI/CD
- [x] `.github/workflows/deploy.yml` already written (from Phase 0)
- [ ] Create DigitalOcean droplet → add `DROPLET_IP` + `SSH_PRIVATE_KEY` to GitHub secrets
- [ ] Push to main — confirm GitHub Actions deploys

### ✅ Phase 1 Verification Gate
```
1. Send a message to your bot from your Telegram account
   → You get back "Echo: <your message>" ✓ DONE
2. curl http://localhost:8000/health
   → {"status": "ok", "timestamp": "..."} ✓ DONE
3. docker-compose up --build → deferred until droplet is ready
```

---

## Phase 2 — Database Layer + User Seeding

**Goal:** User row exists in DB, `db.py` has all query functions needed for Phase 3.

### 2.1 — User seeding
- [ ] In `db.py`, implement `get_or_create_user(telegram_user_id: int) -> dict`:
  - `SELECT * FROM users WHERE telegram_user_id = $1`
  - If not found: `INSERT INTO users (telegram_user_id) VALUES ($1) RETURNING *`
  - Return the user row as a dict
- [ ] Call `get_or_create_user(settings.TELEGRAM_USER_ID)` at startup in `main.py`
- [ ] Log `"User seeded: id=<id>"` on first run

### 2.2 — Goal queries
- [ ] `get_active_goals(user_id: int) -> list[dict]`
- [ ] `create_goal(user_id: int, title: str, description: str, timeframe: str, category: str, is_non_negotiable: bool, target_per_week: int | None) -> dict`
- [ ] `update_goal_streak(goal_id: int, current: int, longest: int)` — called after habit completion
- [ ] `deactivate_goal(goal_id: int)` — sets `active = false`

### 2.3 — Log queries
- [ ] `insert_log(user_id: int, type: str, date: str, data: dict, goal_id: int | None, notes: str | None) -> dict`
- [ ] `get_logs_since(user_id: int, days: int) -> list[dict]` — used for tiered context
- [ ] `get_logs_by_type(user_id: int, type: str, days: int) -> list[dict]`
- [ ] `get_yesterday_summary(user_id: int) -> dict` — habit completion, mood, food, finance for yesterday

### 2.4 — Record queries
- [ ] `insert_record(user_id: int, type: str, date: str, data: dict, source: str, notes: str | None, file_url: str | None) -> dict`
- [ ] `get_records_by_type(user_id: int, type: str) -> list[dict]` — pulls all records of a type
- [ ] `get_latest_brain_snapshot(user_id: int) -> dict | None`

### 2.5 — Event queries
- [ ] `get_upcoming_events(user_id: int, days_ahead: int = 7) -> list[dict]`
- [ ] `insert_event(user_id: int, title: str, date: str, type: str, source: str, notes: str | None) -> dict`

### 2.6 — Conversation history queries
- [ ] `save_message(user_id: int, role: str, content: str)` — call after every send/receive
- [ ] `get_recent_messages(user_id: int, limit: int = 20) -> list[dict]` — used in context assembly

### 2.7 — Domain queries
- [ ] `get_active_domains(user_id: int) -> list[dict]`
- [ ] `create_domain(user_id: int, name: str, display_name: str, evening_prompt: str, ...) -> dict`
- [ ] `toggle_domain(domain_id: int, active: bool)`

### ✅ Phase 2 Verification Gate
```python
# Run in a test script or Python REPL:
from db import get_or_create_user, create_goal, insert_log, get_logs_since
import asyncio

async def test():
    user = await get_or_create_user(12345678)
    goal = await create_goal(user['id'], "Go gym", "3x/week", "ongoing", "health", True, 3)
    log = await insert_log(user['id'], "habit", "2026-05-16", {"completed": True}, goal['id'], None)
    logs = await get_logs_since(user['id'], 1)
    print(logs)

asyncio.run(test())
# Should print the log entry you just inserted
# Verify in Supabase Table Editor that rows exist
```

---

## Phase 3 — Claude Integration + Tiered Context

**Goal:** Free-form chat works. Claude has full context about you, reasons over your history, replies intelligently.

### 3.1 — tools.py
- [ ] Define `TOOLS` list with both Claude tool schemas:
  ```python
  TOOLS = [
    {
      "name": "search_web",
      "description": "Search the live web for current information...",
      "input_schema": {
        "type": "object",
        "properties": {
          "query": {"type": "string"},
          "domains": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["query"]
      }
    },
    {
      "name": "log_data",
      "description": "Write a structured log entry to the database...",
      "input_schema": {
        "type": "object",
        "properties": {
          "type": {"type": "string"},
          "date": {"type": "string", "description": "YYYY-MM-DD"},
          "data": {"type": "object"},
          "notes": {"type": "string"}
        },
        "required": ["type", "date", "data"]
      }
    }
  ]
  ```
- [ ] Implement `execute_tool(tool_name: str, tool_input: dict, user_id: int) -> str`:
  - `search_web`: call Tavily client, return formatted results string with source URLs
  - `log_data`: call `insert_log()`, return confirmation string
  - Unknown tool: return error string

### 3.2 — context.py (tiered context assembly)
- [ ] Implement `build_system_prompt(user_id: int) -> str` with 4 tiers:

  **Tier 1 — Static profile (prompt-cached, near-zero decay):**
  - User name, timezone, wake/sleep time, tone preference
  - All active goals (title, description, timeframe, is_non_negotiable, current_streak)
  - Latest body composition record
  - Latest blood test summary
  - Medical notes
  - Dietary profile
  - Active domain configs (system_prompt_snippet)
  - Philosophical frameworks (Huberman, Hamza — hardcoded in prompt)
  - Today's date and day of week

  **Tier 2 — Recent logs (last 14 days):**
  - All `logs` rows from last 14 days, grouped by type
  - Format as compact JSON or bullet list

  **Tier 3 — Weekly summaries (last 4 weeks):**
  - Pull `records` where `type = 'weekly_summary'` and `date >= 28 days ago`
  - Append as "Weekly Summaries" section

  **Tier 4 — Brain snapshot (compressed long-term memory):**
  - Pull latest `brain_snapshot` from `records`
  - Append as "Long-term Memory Snapshot" section

- [ ] Implement `build_messages(user_id: int, new_message: str) -> list[dict]`:
  - Pull last 20 messages from `conversations` table
  - Append `{"role": "user", "content": new_message}`
  - Return as list in Claude message format

### 3.3 — Claude call with tool loop
- [ ] In `bot.py`, implement `call_claude(user_id: int, user_message: str) -> str`:
  ```
  1. system = await build_system_prompt(user_id)
  2. messages = await build_messages(user_id, user_message)
  3. response = anthropic_client.messages.create(
       model="claude-sonnet-4-6",
       system=system,
       messages=messages,
       tools=TOOLS,
       max_tokens=1024
     )
  4. While response.stop_reason == "tool_use":
       a. Find tool_use block in response.content
       b. Execute the tool: result = await execute_tool(name, input, user_id)
       c. Append assistant message with tool_use block
       d. Append user message with tool_result block
       e. Call Claude again with updated messages
  5. Extract final text from response.content
  6. Return text
  ```
- [ ] Wrap entire call in try/except; on `anthropic.APIError`: return "Having trouble reaching my brain right now, try again in a minute."
- [ ] Log every Claude call: timestamp, token usage (input/output), whether tools were used

### 3.4 — Wire up message handler
- [ ] In `bot.py`, update `handle_message`:
  1. Save incoming message: `await save_message(user_id, "user", text)`
  2. Send "typing" action while Claude processes
  3. `reply = await call_claude(user_id, text)`
  4. Save reply: `await save_message(user_id, "assistant", reply)`
  5. Send reply to Telegram

### 3.5 — Prompt caching setup
- [ ] Add `cache_control: {"type": "ephemeral"}` to the last Tier 1 content block in system prompt
- [ ] Verify in logs that `cache_creation_input_tokens` appears on first call and `cache_read_input_tokens` appears on subsequent calls (within 5-minute TTL)

### ✅ Phase 3 Verification Gate
```
1. Send: "What are my current goals?"
   → Claude responds with your actual goals from DB, not generic advice.
2. Send: "What's the best supplement stack for sleep?"
   → Claude calls search_web, returns answer with cited sources.
3. Send: "Log that I did gym today"
   → Claude calls log_data, confirms it wrote the entry.
   → Verify the log row appears in Supabase > logs table.
4. Send two follow-up messages testing memory within the session.
   → Claude references what you said earlier in the conversation.
```

---

## Phase 4 — Scheduled Messages (Morning Check-In + Evening Review)

**Goal:** Agent proactively messages you at the right times without you initiating.

### 4.1 — scheduler.py
- [ ] Initialize `AsyncIOScheduler` from APScheduler
- [ ] Load user timezone and wake_time from DB on startup
- [ ] Register `morning_checkin` job:
  - Cron trigger: `hour=wake_time.hour, minute=wake_time.minute, timezone=user.timezone`
  - Fires daily
- [ ] Register `evening_review` job:
  - Cron trigger: `hour=21, minute=0` (or user's `sleep_target_time - 2h`), `timezone=user.timezone`
  - Fires daily
- [ ] Register `weekly_summary` job:
  - Cron trigger: `day_of_week='sun', hour=20, minute=0`
- [ ] Register `nudge_check` job:
  - Interval trigger: every 6 hours
  - Checks `domains` for `nudge_after_days` logic
- [ ] Start scheduler in `main.py` before bot polling

### 4.2 — morning_checkin job
- [ ] Fetch yesterday's performance summary from DB (habits hit/missed, mood score, study done)
- [ ] Fetch today's upcoming events from `events` table
- [ ] Build prompt: "Good morning, Mahir. Yesterday: [summary]. Today you have: [events]. What are your 3 priorities for today?"
- [ ] Call Claude with this prompt (no conversation history — fresh each morning)
- [ ] Send message via `bot.send_message(chat_id=settings.TELEGRAM_USER_ID, text=response)`
- [ ] Save the agent-initiated message to `conversations` table

### 4.3 — evening_review job
- [ ] Build structured evening prompt covering all active domains:
  - Pull active domains from `domains` table; use `evening_prompt` field for each
  - Standard questions: gym (/habit), food quality, mood 1-10, energy 1-10, spend today, study session
  - End with: "Anything else on your mind before you wind down?"
- [ ] Call Claude to craft the message in the agent's voice (not a dry list)
- [ ] Send, save to conversations

### 4.4 — weekly_summary job
- [ ] Fetch last 7 days of all logs and records
- [ ] Prompt Claude: "Generate the weekly summary. Include: habits hit %, mood average, food quality trend, study hours, spend pattern, standout wins this week, and one honest observation."
- [ ] Save the summary as a `records` row with `type='weekly_summary'`
- [ ] Send summary to Telegram

### 4.5 — brain_snapshot job (runs after weekly_summary)
- [ ] Prompt Claude: "Rewrite the brain snapshot based on this week's data. Include: active goals status, open decisions, key health flags, momentum score 1-10, top patterns noticed. Be compressed and factual."
- [ ] Save as `records` row with `type='brain_snapshot'`

### 4.6 — nudge_check job
- [ ] For each active domain where `nudge_after_days IS NOT NULL`:
  - Check last log entry for that domain type
  - If `(today - last_log_date).days >= nudge_after_days`: send a nudge message via Claude
  - Rate limit: only one nudge per domain per day max

### ✅ Phase 4 Verification Gate
```
1. Temporarily set wake_time to 2 minutes from now in DB
   → Morning check-in fires and you receive a personalised message
2. Check scheduler logs — no duplicate firings, no silent errors
3. Let the weekly_summary job run (or trigger manually)
   → Verify row appears in Supabase > records with type='weekly_summary'
   → Verify row appears for type='brain_snapshot'
4. Check that brain snapshot context appears in your next free-form chat message
```

---

## Phase 5 — Health Records + File Uploads

**Goal:** You can upload blood tests and health data; agent uses them in context.

### 5.1 — Supabase Storage setup
- [ ] In Supabase: Storage → New bucket → name it `health-files` → set to private
- [ ] Note the storage URL pattern: `https://<project>.supabase.co/storage/v1/object/health-files/<filename>`

### 5.2 — File upload handler
- [x] In `bot/__init__.py`, add `MessageHandler(filters.Document.ALL | filters.PHOTO, handle_file)`:
  - Download the file using `context.bot.get_file(file_id)`
  - Upload to Supabase Storage via `supabase.storage.from_("health-files").upload(...)`
  - Store returned URL in a temp variable, pass to Claude with the message
- [x] Handle photo type (food photos, InBody scan photos) separately from documents (PDFs)

### 5.3 — `/record` command
- [x] Register `/record` command handler
- [x] Parse subcommand: `/record bloodtest`, `/record body_comp`, `/record medical`, `/record note`, `/record dietary`, `/record decision`
- [x] Prompt Claude with: "The user is logging a {type} record. Extract the structured data and call store_record..."
- [x] Claude calls `store_record` tool (new tool added to TOOLS) which writes to records table
- [x] Reply confirmation generated by Claude listing key values stored

### 5.4 — Health context in Tier 1
- [x] `build_context` in `agent/context.py` now pulls and formats:
  - Latest `bloodtest` record → key: value pairs
  - Latest `body_comp` record → weight, muscle mass, body fat %, date
  - Up to 3 `medical` records → conditions, allergies, injuries
  - Latest `dietary` record → restrictions and preferences

### 5.5 — `/goals` and `/update` commands
- [x] `/goals` → renders active goals with current streaks, target per week, non-negotiable flag
- [ ] `/update goal <title>` → opens conversation for goal modification _(deferred to later phase)_
- [x] `/done <goal_name>` → fuzzy-matches goal, logs habit entry with goal_id, increments streak, confirms

### ✅ Phase 5 Verification Gate
```
1. Send a text description of blood test results
   → Claude parses and stores; next free-form chat references your lab values
2. Upload a PDF (any file) → bot acknowledges it and stores URL in Supabase Storage
3. Run /goals → your actual goals appear with correct streak counts
4. Run /done gym → streak increments by 1 in DB (check Supabase)
```

---

## Phase 6 — Web Search (Tavily + Claude Tool Use)

**Goal:** Claude searches the web when it determines live information would improve the answer.

> Note: The `search_web` tool definition was already added in Phase 3. This phase wires up the actual Tavily execution and validates behaviour.

### 6.1 — Tavily client setup
- [ ] In `tools.py`, initialize `TavilyClient(api_key=settings.TAVILY_API_KEY)`
- [ ] Implement `run_web_search(query: str, domains: list[str] | None) -> str`:
  - Call `tavily.search(query=query, search_depth="advanced", include_domains=domains)`
  - Format results: title, URL, snippet per result
  - Return as markdown-formatted string with numbered citations

### 6.2 — Tool execution routing
- [ ] In `execute_tool()`, `search_web` path:
  - Call `run_web_search(query, input.get("domains"))`
  - Log: "Tavily search executed: [query] — [n] results returned"
  - Return formatted results string

### 6.3 — Source citation in replies
- [ ] After Claude's final response, if search was used:
  - Append `\n\n_Sources searched via Tavily_` or similar footer
  - Ensure Claude was prompted to include inline citations (add instruction to system prompt)

### ✅ Phase 6 Verification Gate
```
1. Ask: "What's the current research on creatine and sleep quality?"
   → Claude calls search_web, response includes sources/citations
2. Ask: "How is my gym routine going?"
   → Claude does NOT call search_web (uses DB context only)
3. Check Tavily dashboard — confirm search calls are registered
```

---

## Phase 7 — Decision Log + Brain Snapshot Enhancement

**Goal:** Agent tracks major life decisions, references them in context, and maintains coherent long-term memory.

### 7.1 — Decision logging
- [x] Add `/decision` command handler in `bot/handlers.py` + registered in `bot/__init__.py`
- [x] Prompt Claude to extract: title, context, options_considered, choice_made, reasoning
- [x] Claude calls `store_record` with type='decision' → writes to records table
- [x] Reply confirms it's logged with one sentence acknowledgment

### 7.2 — Decision context in prompts
- [x] `build_context` in `agent/context.py` now pulls last 5 `decision` records
- [x] Formatted as: `[date] [title]: [choice_made] — [reasoning]`

### 7.3 — Brain snapshot structure
- [x] Schema defined in `scheduler/jobs.py` (_SNAPSHOT_SCHEMA): goals_momentum, open_decisions, health_flags, momentum_score, patterns_noticed, weekly_note
- [x] `brain_snapshot()` job generates JSON via Claude, parses it with `_extract_json`, saves to records table as type='brain_snapshot'
- [x] Chained at end of `weekly_summary` job (runs every Sunday at 20:00 HKT)
- [x] `build_context` in `agent/context.py` pulls latest brain_snapshot and formats it into "Long-term Memory Snapshot" section

### ✅ Phase 7 Verification Gate
```
1. Log a decision: "I decided to focus only on CFA for the next 3 months, dropping side projects"
2. Two days later, ask about a side project
   → Agent references the prior decision and asks if you're reconsidering
3. After Sunday summary runs, check brain_snapshot in Supabase — verify JSON structure matches schema
4. Check that brain snapshot appears in a free-form chat's context (log the system prompt temporarily)
```

---

## Phase 8 — Google Calendar Integration

**Goal:** Morning check-in automatically includes today's calendar events pulled from Google Calendar.

### 8.1 — OAuth 2.0 setup
- [x] Google Cloud Console: project created, Calendar API enabled, OAuth 2.0 credentials created _(manual — done)_
- [x] Redirect URI set to `http://localhost:8000/auth/google/callback` _(done)_
- [x] `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` in `.env`

### 8.2 — Auth endpoints in FastAPI
- [x] `GET /auth/google` — redirects to Google OAuth consent screen (returns 501 if not configured)
- [x] `GET /auth/google/callback` — exchanges auth code for tokens, saves `refresh_token` to `users.google_refresh_token`
- [x] One-time browser auth completed — refresh token saved to Supabase _(done)_

### 8.3 — Calendar fetch function
- [x] `integrations/google.py` — `get_events_for_user(user, date)`: refreshes access token, calls Calendar API, returns `[{title, time}]`

### 8.4 — Sync job (runs nightly at midnight)
- [x] `sync_google_calendar` job registered at 00:05 HKT daily
- [x] Fetches tomorrow's events, writes to `events` table via `replace_events_for_date` (delete + insert by source)

### 8.5 — Morning check-in update
- [x] `morning_checkin` pulls today's events from `events` table before calling Claude
- [x] Events formatted into prompt so Claude weaves the schedule into the message

### ✅ Phase 8 Verification Gate
```
1. Add an event to Google Calendar for today
2. Wait for midnight sync (or trigger manually)
3. Verify event appears in Supabase > events table with source='google_calendar'
4. Morning check-in message includes today's event
```

---

## Phase 9 — Strava Integration

**Goal:** Gym sessions auto-logged from Strava; no manual gym check-in required.

### 9.1 — Strava OAuth setup
- [x] App created at strava.com/settings/api — Client ID: 247029 _(done)_
- [x] `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET` added to `.env`

### 9.2 — Strava OAuth endpoints
- [x] `GET /auth/strava` → redirect to Strava consent (scope: activity:read_all)
- [x] `GET /auth/strava/callback` → exchange for refresh token, save to `users.strava_refresh_token`
- [x] One-time browser auth completed — refresh token saved to Supabase _(done 2026-05-18)_

### 9.3 — Strava fetch function
- [x] `integrations/strava.py` — `get_activities_for_user(user, since)`:
  - Refreshes access token (expires every 6h)
  - Fetches activities after a given datetime
  - Returns `{id, name, sport_type, date, duration_min, distance_km, avg_hr, calories, is_gym}`
  - `GYM_SPORT_TYPES` set: WeightTraining, Workout, Crossfit, RockClimbing, Yoga, Pilates, Swim

### 9.4 — Strava sync job (runs daily at midnight)
- [x] `sync_strava` job at 00:10 HKT — fetch yesterday's activities, write to logs as `strava_activity`
- [x] Gym detection: if `is_gym=True`, check for duplicate manual habit log and deduplicate

### 9.5 — Streak validation + duplicate detection
- [x] During sync: if manual habit log exists for gym goal on same day, delete it (Strava has richer data)
- [x] `/done gym` checks `has_strava_gym_log` before incrementing streak — no double-counting
- [x] `get_strava_activities` Claude tool — query workout history by days + sport_type filter
- [x] New DB helpers: `delete_strava_logs_for_date`, `delete_habit_logs_for_goal_date`, `has_strava_gym_log`, `get_strava_logs`

### ✅ Phase 9 Verification Gate
```
1. Complete a workout and record it on Strava
2. Wait for midnight sync (or trigger manually)
3. Verify strava_activity row appears in Supabase > logs
4. Ask Claude: "Did I train yesterday?" → Claude knows without you telling it
```

---

## Phase 10 — Voice Message Support (Whisper)

**Goal:** Send voice notes to the bot; they're transcribed and processed as text.

### 10.1 — Whisper transcription
- [x] In `bot/handlers.py`, `handle_voice` handler: downloads Telegram voice file, calls Whisper (`openai.audio.transcriptions.create`), echoes transcript in italics, passes to `_process_message` same as text
- [x] Registered in `bot/__init__.py`: `MessageHandler(filters.VOICE | filters.AUDIO, handle_voice)`
- [x] Edge cases: missing key returns clear error, empty transcript handled, download failure handled
- [x] `openai` package in `requirements.txt`; `openai_api_key` in `config.py` (defaults to "")
- Note: add `OPENAI_API_KEY=<key>` to `.env` to activate

### 10.2 — Voice-aware responses
- [x] System prompt note added: "Mahir sometimes sends voice notes transcribed by Whisper — text may be informal or contain transcription artifacts; interpret charitably"
- [x] Edge cases handled: empty transcription returns user-friendly message; download errors caught with fallback reply

### ✅ Phase 10 Verification Gate
```
1. Record a voice note: "Log that I had a good gym session today, about 60 minutes"
2. Bot transcribes and processes → Claude calls log_data, confirms gym session logged
3. Verify in Supabase > logs that the habit row was created
```

---

## Phase 11 — Apple Health (iPhone Shortcuts)

**Goal:** Sleep duration, resting HR, and steps sync daily without any manual input.

### 11.1 — Parsing endpoint
- [x] `POST /health/apple` in `main.py`: accepts `{sleep_hours, resting_hr, steps, hrv, date}`, Bearer token auth via `APPLE_HEALTH_TOKEN`, writes each non-null metric as a separate `health_metric` log row, returns `{"status": "logged", "metrics": [...], "date": "..."}`
- [x] Returns 501 if `APPLE_HEALTH_TOKEN` is not set or still has placeholder value
- Note: change `APPLE_HEALTH_TOKEN` in `.env` from `your_static_secret_here` to a real random string before using

### 11.2 — iPhone Shortcut setup (manual, one-time)
- [ ] On iPhone: Shortcuts app → New Shortcut → Add steps:
  1. Get "Health Samples" for: Sleep (last night), Resting Heart Rate (latest), Steps (yesterday), HRV (latest if available)
  2. Create Dictionary with those values + today's date
  3. `Get Contents of URL` → POST to `http://<your-droplet-ip>:8000/health/apple` with JSON body and Authorization header
  4. Set automation: run every morning at wake_time
- [ ] Test Shortcut manually → confirm metrics appear in Supabase > logs

### 11.3 — Health metrics in context
- [x] `build_context` in `agent/context.py` now pulls health_metric logs from the last 7 days from the already-fetched logs list, groups by date, formats as compact "Apple Health (Last 7 Days)" section — shown separately from other logs
- [x] Correlation logic added to SYSTEM_PROMPT: "When mood or energy is low, cross-reference sleep_hours from Apple Health logs"

### ✅ Phase 11 Verification Gate
```
1. Trigger the Shortcut manually
2. Verify health_metric rows appear in Supabase with correct values
3. Ask Claude: "How has my sleep been this week?"
   → Claude gives accurate answer from actual Apple Health data
```

---

## Phase 12 — Web Dashboard (Analytics & Data Visualisation)

**Goal:** Read-only web dashboard to visualise all logged data. Build after Phase 4 once real data exists.

> Detailed implementation checklist to be written at build time. This section captures the planned tech stack and scope agreed during initial planning.

### Planned Stack
- **Next.js 14** (App Router + TypeScript)
- **Tailwind CSS**
- **Recharts** — charts and trend visualisations
- **Supabase JS client** — data via server components
- **Vercel** — free hosting

### Planned Views
- [ ] Habit streak heatmap (GitHub contribution graph style)
- [ ] Mood + energy trend lines over time
- [ ] Goal progress cards (current streak, longest streak, weekly target %)
- [ ] Weekly summary viewer (browse past summaries)
- [ ] Body composition history (weight, muscle mass, body fat % over time)
- [ ] Finance spend trend over time
- [ ] Study hours over time
- [ ] Latest brain snapshot viewer

### Open Decisions (to resolve at build time)
- Auth approach: single-password middleware vs Supabase Auth
- Read-only vs allow some data entry from the dashboard
- Same repo (`/dashboard`) vs separate repository

---

## Post-Build Maintenance Tasks

- [x] Rate limiting: 50 messages/day cap in `_process_message` — sends email via Gmail SMTP on first hit (idempotent, one email/day max), replies to user with clear message. Set SMTP_USER, SMTP_PASSWORD, NOTIFICATION_EMAIL in .env to activate email alerts.
- [ ] Monthly review: check Claude API costs in Anthropic console; tune prompt caching if over budget
- [ ] Add Sentry or similar error tracking for production exceptions
- [ ] Review and prune `conversations` table monthly (keep last 60 days; archive older rows)
- [ ] Rotate API keys every 6 months
- [ ] Test the GitHub Actions deploy pipeline after any droplet restart/rebuild
