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
- [ ] Create Telegram bot via @BotFather → save `TELEGRAM_BOT_TOKEN`
- [ ] Get your Telegram user ID (message @userinfobot) → save `TELEGRAM_USER_ID`
- [ ] Get Anthropic API key from console.anthropic.com → save `ANTHROPIC_API_KEY`
- [ ] Get Tavily API key from app.tavily.com → save `TAVILY_API_KEY`
- [ ] Get OpenAI API key from platform.openai.com (for Whisper, Phase 6) → save `OPENAI_API_KEY`
- [ ] In Supabase: create project → copy `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
- [ ] Create DigitalOcean droplet ($4/mo, Ubuntu 22.04 LTS, any datacenter) → note the IP

### 0.3 — Local Project Structure
- [ ] `cd ~/Desktop/Technical_Projects/Life-Agent`
- [ ] Create directory structure:
  ```
  mkdir -p .github/workflows
  touch main.py bot.py scheduler.py context.py db.py tools.py config.py
  touch Dockerfile docker-compose.yml requirements.txt .env.example
  ```
- [ ] Populate `.env` from `.env.example` with all real keys (never commit `.env`)
- [ ] Confirm `.gitignore` covers: `.env`, `*.db`, `__pycache__/`, `.DS_Store`, `spread_commits.py`

### 0.4 — Supabase Schema
Run the following SQL in the Supabase SQL Editor (Dashboard → SQL Editor → New query):

- [ ] Create `users` table:
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
- [ ] Create `goals` table:
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
- [ ] Create `logs` table:
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
- [ ] Create `records` table:
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
- [ ] Create `events` table:
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
- [ ] Create `domains` table:
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
- [ ] Create `conversations` table:
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
- [ ] Verify all 7 tables appear in Supabase Table Editor

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
- [ ] Add to `requirements.txt`:
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
- [ ] `pip install -r requirements.txt` — verify no errors

### 1.2 — config.py
- [ ] Implement `Settings` class using `pydantic-settings`:
  - Fields: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_USER_ID` (int), `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`, `OPENAI_API_KEY`, `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
  - Load from `.env` file
  - Export a singleton `settings` instance
- [ ] Add a startup check: if any required key is missing or empty, raise `ValueError` with the field name

### 1.3 — db.py (connection only)
- [ ] Set up async SQLAlchemy engine using `asyncpg` driver and `DATABASE_URL` from settings
- [ ] Implement `get_db()` async context manager that yields a session
- [ ] Implement `init_db()` that runs a `SELECT 1` to verify connection on startup
- [ ] Log `"Database connected"` on success, raise on failure

### 1.4 — bot.py (skeleton)
- [ ] Create `Application` using `python-telegram-bot`
- [ ] Implement `security_guard` middleware:
  - On every incoming message, check `update.effective_user.id == settings.TELEGRAM_USER_ID`
  - If not matching: log the unauthorized attempt (include user ID and username), do NOT reply, return immediately
  - This must run before ANY handler
- [ ] Implement `handle_message(update, context)`:
  - For now: just reply "Echo: {message_text}" to confirm the pipeline works
- [ ] Register `MessageHandler(filters.ALL, handle_message)` 
- [ ] Implement `start_bot()` that runs long polling (no webhook)

### 1.5 — FastAPI health endpoint
- [ ] In `main.py`: create FastAPI `app` instance
- [ ] Add `GET /health` route returning `{"status": "ok", "timestamp": <iso_datetime>}`
- [ ] This is used by Docker healthcheck

### 1.6 — main.py entry point
- [ ] `async def main()`:
  1. Load settings (fail fast if env vars missing)
  2. Call `init_db()` (fail fast if DB unreachable)
  3. Start FastAPI via uvicorn on port 8000 (background task)
  4. Start Telegram bot polling
- [ ] `if __name__ == "__main__": asyncio.run(main())`

### 1.7 — Docker
- [ ] Write `Dockerfile`:
  ```dockerfile
  FROM python:3.12-slim
  WORKDIR /app
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  COPY . .
  CMD ["python", "main.py"]
  ```
- [ ] Write `docker-compose.yml`:
  ```yaml
  services:
    app:
      build: .
      env_file: .env
      restart: always
      ports:
        - "8000:8000"
      healthcheck:
        test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
        interval: 30s
        timeout: 10s
        retries: 3
  ```
- [ ] `docker-compose up --build` — confirm container starts without errors
- [ ] Confirm `/health` responds at `http://localhost:8000/health`

### 1.8 — GitHub Actions CI/CD
- [ ] Write `.github/workflows/deploy.yml`:
  ```yaml
  name: Deploy
  on:
    push:
      branches: [main]
  jobs:
    deploy:
      runs-on: ubuntu-latest
      steps:
        - name: Deploy to droplet
          uses: appleboy/ssh-action@v1
          with:
            host: ${{ secrets.DROPLET_IP }}
            username: lifeagent
            key: ${{ secrets.SSH_PRIVATE_KEY }}
            script: |
              cd /home/lifeagent/app
              git pull origin main
              docker-compose up --build -d
  ```
- [ ] On DigitalOcean droplet: create user `lifeagent`, clone repo to `/home/lifeagent/app`, place `.env`
- [ ] Push to main — confirm GitHub Actions runs and deploys

### ✅ Phase 1 Verification Gate
```
1. Send a message to your bot from your Telegram account
   → You get back "Echo: <your message>"
2. Send a message from a different Telegram account
   → Bot does NOT reply; unauthorized attempt appears in logs
3. curl http://localhost:8000/health
   → {"status": "ok", "timestamp": "..."}
4. Push a commit to main
   → GitHub Actions deploys within ~90 seconds
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
- [ ] In `bot.py`, add `MessageHandler(filters.Document.ALL | filters.PHOTO, handle_file)`:
  - Download the file using `context.bot.get_file(file_id)`
  - Upload to Supabase Storage via `supabase.storage.from_("health-files").upload(...)`
  - Store returned URL in a temp variable, pass to Claude with the message
- [ ] Handle photo type (food photos, InBody scan photos) separately from documents (PDFs)

### 5.3 — `/record` command
- [ ] Register `/record` command handler
- [ ] Parse subcommand: `/record bloodtest`, `/record inbody`, `/record medical`, `/record note`
- [ ] Prompt Claude with: "The user is uploading a {type}. Parse the following data and store it. [data]"
- [ ] Claude calls `log_data` internally OR backend calls `insert_record` directly based on type
- [ ] Reply confirmation: "Got it. I've stored your [type] from [date]. Here's what I noted: ..."

### 5.4 — Health context in Tier 1
- [ ] Ensure `build_system_prompt` pulls and formats:
  - Latest `blood_test` record → format as key: value pairs
  - Latest `body_comp` record → weight, muscle mass, body fat %, date
  - All `medical` records → conditions, allergies, injuries
  - Latest `dietary` record → restrictions and preferences

### 5.5 — `/goals` and `/update` commands
- [ ] `/goals` → Claude renders active goals with current streaks in a formatted list
- [ ] `/update goal <title>` → opens conversation for goal modification
- [ ] `/done <goal_name>` → marks habit complete, updates streak, confirms

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
- [ ] Add `/decision` command handler
- [ ] Prompt Claude to extract: decision title, context/background, options considered, choice made, reasoning, date
- [ ] Store as `records` row with `type='decision'`
- [ ] Reply: "Decision logged. I'll reference this if it comes up again."

### 7.2 — Decision context in prompts
- [ ] In `build_system_prompt`, add a "Recent Decisions" section:
  - Pull last 5 `decision` records
  - Format as: `[date] [title]: [choice made] — [one-line reasoning]`

### 7.3 — Brain snapshot structure
- [ ] Define exact schema for brain snapshot JSON:
  ```json
  {
    "goals_momentum": [{"goal": "...", "streak": 3, "status": "on_track|behind|ahead"}],
    "open_decisions": ["..."],
    "health_flags": ["Low iron noted in last blood test"],
    "momentum_score": 7,
    "patterns_noticed": ["Mood dips on Wednesdays", "Gym skips correlate with poor sleep"],
    "weekly_note": "Strong week on study, gym slipped"
  }
  ```
- [ ] Update `weekly_summary` job prompt to generate snapshot in this exact schema
- [ ] Update `build_system_prompt` Tier 4 to parse and format this schema

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
- [ ] In Google Cloud Console: create project, enable Google Calendar API, create OAuth 2.0 credentials (Web application type)
- [ ] Set redirect URI to `http://localhost:8000/auth/google/callback` for local dev
- [ ] Add to `.env`: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`

### 8.2 — Auth endpoints in FastAPI
- [ ] `GET /auth/google` — redirect to Google OAuth consent screen
- [ ] `GET /auth/google/callback` — receive auth code, exchange for tokens, save `refresh_token` to `users.google_refresh_token`
- [ ] One-time setup: Mahir visits the URL once, authorises, tokens stored

### 8.3 — Calendar fetch function
- [ ] `get_todays_events_from_google(user_id: int) -> list[dict]`:
  - Load refresh token from DB
  - Exchange for access token via Google token endpoint
  - Call `https://www.googleapis.com/calendar/v3/calendars/primary/events` with `timeMin/timeMax` for today
  - Return list of `{title, start_time, end_time}` dicts

### 8.4 — Sync job (runs nightly at midnight)
- [ ] Register `sync_google_calendar` job in scheduler
- [ ] Fetches tomorrow's events from Google Calendar
- [ ] Upserts into `events` table with `source='google_calendar'`

### 8.5 — Morning check-in update
- [ ] Update `morning_checkin` job to pull today's events from `events` table (now populated from Google)
- [ ] Include formatted schedule in the check-in message context

### ✅ Phase 8 Verification Gate
```
1. Add an event to Google Calendar for today
2. Wait for midnight sync (or trigger manually)
3. Verify event appears in Supabase > events table with source='google_calendar'
4. Morning check-in message includes today's event
```

---

## Phase 9 — Strava Integration
