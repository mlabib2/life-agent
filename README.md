# The Life Agent

A personal AI accountability system delivered via Telegram. Acts as a life coach, data-driven advisor, and habit tracker — available 24/7, proactively initiating check-ins, logging your data, and reasoning over your history.

---

## Overview

Most habit tools fail because they are passive — you have to remember to open them. The Life Agent is active. It messages you at the right times, notices patterns in your data, and holds you accountable to your own stated goals. After months of logs, it knows patterns you cannot see yourself.

**What it covers:** Fitness · Nutrition · Finance · Study (CFA) · Sleep · Mood · Health records · Life decisions · Goals

---

## Architecture

```
Mahir (Telegram — text, voice, photo)
    |
    v
Telegram Bot API  <----> APScheduler (proactive jobs)
    |
    v
FastAPI Backend (Python)
    |
    |-- Step 1: Haiku (forced extraction) --> Supabase (write logs)
    |-- Step 2: Sonnet (conversation)     --> Supabase (read context)
    |                                     --> Tavily (web search)
    |                                     --> Google Calendar API
    |                                     --> Strava DB
    v
Supabase (PostgreSQL)
```

**Message flow:**
1. Bot polls Telegram every second for new messages
2. Security guard: only responds to your `TELEGRAM_USER_ID` — all others silently dropped
3. Slash command (`/done`, `/goals`, `/record`, `/decision`) → direct handler, no LLM
4. Voice note → Whisper transcription → treated as text
5. Free-form text → **Step 1**: Haiku with `tool_choice="any"` extracts and logs all data items; **Step 2**: Sonnet assembles full context from DB and generates conversational reply
6. Claude can call tools during Step 2: `search_web`, `get_calendar_events`, `create_calendar_event`, `delete_calendar_event`, `get_strava_activities`, `delete_log`, `store_record`
7. Reply sent to Telegram; conversation saved to DB

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Interface | Telegram Bot (long polling) | Always accessible, text/voice/photo. No domain or SSL required. |
| Backend | Python + FastAPI | Best ecosystem for this use case |
| Extraction LLM | Claude Haiku (`claude-haiku-4-5`) | Fast, cheap, forced tool use for reliable data capture |
| Conversation LLM | Claude Sonnet (`claude-sonnet-4-6`) | Best reasoning for advice, context, and pattern recognition |
| Web Search | Tavily API | Purpose-built for AI agents; clean structured JSON |
| Database | Supabase (PostgreSQL) | Managed hosted Postgres; JSONB columns; auto-backups |
| Scheduler | APScheduler | In-process cron inside the FastAPI app |
| Voice | OpenAI Whisper (`whisper-1`) | Voice-to-text for eyes-free logging |
| Containers | Docker + docker-compose | Single container; dev/prod parity |
| Hosting | DigitalOcean Droplet | Always-on; Supabase handles DB separately |
| Integrations | Google Calendar, Strava | Auto-pull schedule and workouts nightly |

---

## Two-Step Extraction Pipeline

The core reliability mechanism for data capture:

**Step 1 — Forced extraction (Haiku)**
- Model: `claude-haiku-4-5-20251001` with `tool_choice={"type": "any"}`
- Tools: `log_data` only + `nothing_to_log` escape hatch
- Cannot return text — must call a tool. Loops up to 3 rounds to capture all items.
- Runs before any conversation. Supabase connection is reset after this step.

**Step 2 — Conversation (Sonnet)**
- Model: `claude-sonnet-4-6` with `tool_choice="auto"`
- Tools: everything except `log_data` (already handled in Step 1)
- Builds fresh context from DB, generates natural reply, confirms what was logged

This prevents the classic LLM failure mode of saying "I'll log that" without actually calling the tool.

---

## Claude Tools

| Tool | Available in | What it does |
|---|---|---|
| `log_data` | Step 1 only | Write structured log to Supabase (habit, food, finance, sleep, mood, study, social, health_metric) |
| `nothing_to_log` | Step 1 only | Escape hatch — signals no data in this message |
| `delete_log` | Step 2 | Delete the most recent log entry of a given type/date |
| `store_record` | Step 2 | Write a one-time record (blood test, body comp, dietary profile, decision) |
| `get_calendar_events` | Step 2 | Fetch Google Calendar events for a date range |
| `create_calendar_event` | Step 2 | Add an event to Google Calendar |
| `delete_calendar_event` | Step 2 | Delete a Google Calendar event by ID |
| `get_strava_activities` | Step 2 | Query logged Strava activities from DB |
| `search_web` | Step 2 | Tavily web search for current information |

---

## Slash Commands

| Command | What it does |
|---|---|
| `/done <goal>` | Mark a goal completed today, increment streak. Blocks duplicate if Strava already logged it. |
| `/goals` | List all active goals with current streaks |
| `/record <type> <data>` | Store a health record (bloodtest, body\_comp, medical, dietary, decision, note) |
| `/decision <text>` | Log a major life decision with structured fields extracted by Claude |

---

## Proactive Scheduler Jobs

| Job | Trigger | What it does |
|---|---|---|
| Google Calendar sync | Daily 00:05 HKT | Refreshes OAuth token, fetches next 7 days of events, upserts into `events` table |
| Strava sync | Daily 00:10 HKT | Fetches yesterday's activities, writes to `logs` (type=strava_activity), deduplicates against manual gym logs |
| Morning check-in | Weekdays 06:40 HKT | Yesterday's performance + today's calendar + ask for priorities |
| Evening review | Daily 21:00 HKT | Review gym, food, mood, spend, study — anything outstanding |
| Weekly summary + brain snapshot | Sunday 20:00 HKT | Full week recap saved to DB; brain snapshot (compressed long-term memory) rewritten |

---

## Context Injection

Every Claude call assembles context fresh from the DB:

| Section | Content |
|---|---|
| Current date/time | Injected every call — prevents year drift bugs |
| User profile | Name, timezone, wake time, sleep target, tone preference |
| Active goals | Title, description, non-negotiable flag, weekly target, current streak |
| Last 14 days of logs | All log types with date and structured data |
| Health records | Latest body comp, blood test, dietary profile, recent medical notes |
| Recent decisions | Last 5 decision records |
| Brain snapshot | Agent-generated compressed long-term memory, rewritten weekly |

---

## Data Model

```
users         — identity, preferences, OAuth tokens (Google, Strava)
goals         — goals + non-negotiables, streak tracking
logs          — daily captures: habit, mood, food, finance, study, social, strava_activity, health_metric
records       — one-time data: blood_test, body_comp, medical, dietary, decision, brain_snapshot
events        — calendar events (manual + Google Calendar sync)
conversations — full message history for context continuity
```

`logs.data` is JSONB — structure varies by type:
```json
habit:          { "name": "gym", "muscle_groups": "chest, triceps", "duration_min": 75 }
food:           { "description": "chicken rice", "calories": 650 }
finance:        { "amount": 45, "currency": "HKD", "category": "food", "description": "lunch" }
sleep:          { "bedtime": "00:30", "wake_time": "07:00", "hours": 6.5 }
strava_activity:{ "name": "Morning Run", "sport_type": "Run", "duration_min": 42, "distance_km": 7.2 }
```

---

## Repository Structure

```
life-agent/
├── main.py                  # FastAPI app entry point + OAuth routes + uvicorn
├── config.py                # Pydantic-settings — loads all .env vars
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example
├── schema.sql               # Supabase table definitions
│
├── agent/
│   ├── context.py           # build_context() + SYSTEM_PROMPT + build_messages()
│   └── tools.py             # TOOLS list + handle_tool_call() dispatcher
│
├── bot/
│   ├── __init__.py          # build_app() — registers handlers + error handler
│   └── handlers.py          # All Telegram handlers + two-step pipeline + Whisper
│
├── db/
│   └── __init__.py          # All Supabase query functions (sync, lazy singleton)
│
├── integrations/
│   ├── google.py            # Google Calendar OAuth + event CRUD
│   └── strava.py            # Strava OAuth + activity fetch
│
└── scheduler/
    └── jobs.py              # APScheduler setup + all 5 job functions
```

---

## Setup

### Prerequisites
- Python 3.12+
- Supabase account (free tier)
- API keys: Telegram, Anthropic, Tavily, OpenAI (Whisper)
- Optional: Google Calendar OAuth app, Strava OAuth app

### Local Development

```bash
git clone git@github.com:mlabib2/life-agent.git
cd life-agent

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Fill in real API keys in .env

python main.py
```

### Docker (Production)

```bash
docker compose up -d --build

# Watch logs
docker compose logs -f

# Health check
curl http://localhost:8000/health
```

### Optional Integrations

**Google Calendar:**
```
GET http://localhost:8000/auth/google
```
Redirects through OAuth → stores refresh token in DB. Nightly sync starts automatically.

**Strava:**
```
GET http://localhost:8000/auth/strava
```
Same flow. Requires `activity:read_all` scope.

---

## Environment Variables

```bash
# Required
TELEGRAM_BOT_TOKEN=        # From @BotFather
TELEGRAM_USER_ID=          # Your Telegram user ID (from @userinfobot)
ANTHROPIC_API_KEY=         # From console.anthropic.com
TAVILY_API_KEY=            # From app.tavily.com
SUPABASE_URL=              # https://<project>.supabase.co
SUPABASE_SERVICE_KEY=      # Service role key from Supabase dashboard

# Optional
OPENAI_API_KEY=            # Voice transcription via Whisper
GOOGLE_CLIENT_ID=          # Google Calendar integration
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=       # http://localhost:8000/auth/google/callback
STRAVA_CLIENT_ID=          # Strava integration
STRAVA_CLIENT_SECRET=
CLAUDE_MODEL=              # Defaults to claude-sonnet-4-6
```

---

## Security

- Bot only responds to `TELEGRAM_USER_ID`. All other senders are silently ignored and logged.
- `.env` is gitignored — never committed.
- Supabase service key has full DB access — keep it secret.
- OAuth refresh tokens stored in `users` table (encrypted at rest by Supabase).

---

## Build Status

| Phase | Feature | Status |
|---|---|---|
| 0 | Repo, Supabase schema, Docker setup | Complete |
| 1 | Telegram bot skeleton, security guard, health endpoint | Complete |
| 2 | Full DB layer | Complete |
| 3 | Claude integration, tiered context, tool use | Complete |
| 4 | Scheduled messages (morning, evening, weekly, brain snapshot) | Complete |
| 5 | Health records, file uploads, `/record`, `/goals` commands | Complete |
| 6 | Tavily web search | Complete |
| 7 | Decision log, brain snapshot, long-term memory | Complete |
| 8 | Google Calendar OAuth + nightly sync | Complete |
| 9 | Strava OAuth + daily workout sync + dedup | Complete |
| 10 | Voice messages via Whisper | Complete |
| 11 | DigitalOcean deployment | Pending |
| 12 | Apple Health via iPhone Shortcuts | Planned |
| 13 | Web dashboard (analytics + visualisation) | Planned |

---

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — System diagrams (Mermaid): message flow, context tiers, DB schema, scheduler jobs
- **[PLAN.md](PLAN.md)** — Phase-by-phase implementation checklist
