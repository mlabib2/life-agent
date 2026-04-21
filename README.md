# The Life Agent

A personal AI accountability system delivered via Telegram. Acts as a life coach, data-driven advisor, and habit tracker — available 24/7, proactively initiating check-ins, logging your data, and reasoning over your history.

---

## Overview

Most habit tools fail because they are passive — you have to remember to open them. The Life Agent is active. It messages you at the right times, notices patterns in your data, and holds you accountable to your own stated goals. After months of logs, it knows patterns you cannot see yourself.

**What it covers:** Fitness · Nutrition · Finance · Study (CFA) · Sleep · Mood · Health records · Life decisions · Goals

---

## Architecture

```
Mahir (Telegram)
    |
    v
Telegram Bot API  <----> Scheduler (APScheduler)
    |                         |
    v                         v
Backend App (Python + FastAPI)
    |           |           |
    v           v           v
Claude API    Supabase     Tavily API
(Anthropic)   (PostgreSQL,  (live web search,
+ Tool Use)    managed DB)   on Claude request)
```

**Message flow:**
1. Backend polls Telegram every second for new messages
2. Incoming message → security check (only responds to your Telegram user ID)
3. Slash command (e.g. `/done gym`) → direct DB write, no LLM needed
4. Free-form message → tiered context assembled from DB → Claude API call
5. If Claude calls `search_web` → Tavily executes, results returned to Claude
6. If Claude calls `log_data` → structured JSON written directly to Supabase
7. Reply sent to Telegram; conversation saved to DB

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Interface | Telegram Bot (long polling) | Always accessible, text/voice/buttons/photos. No domain or SSL required. |
| Backend | Python + FastAPI | Best ecosystem for this use case |
| LLM | Claude API (claude-sonnet-4-6) | Best-in-class reasoning, native tool use, prompt caching |
| Web Search | Tavily API | Purpose-built for AI agents; clean structured JSON with citations |
| Database | Supabase (PostgreSQL) | Managed hosted Postgres; JSONB columns; auto-backups; built-in dashboard |
| Scheduler | APScheduler | In-process cron inside the app container |
| Voice | OpenAI Whisper API | Voice-to-text for eyes-free logging |
| Containers | Docker + docker-compose | Single container app; dev/prod parity |
| Hosting | DigitalOcean Droplet ($4/mo) | Always-on; Supabase handles DB separately |
| CI/CD | GitHub Actions | Push to main → auto-deploy via SSH |
| Integrations | Google Calendar, Strava, Apple Health | Auto-pull schedule, workouts, sleep/HR data |

**Estimated monthly cost:** $8–12/month (droplet + API usage with prompt caching)

---

## Data Model

Seven tables, KISS/DRY principle — all variation handled via `type` field + JSONB.

```
users         — identity, preferences, OAuth tokens, onboarding state
goals         — goals + non-negotiables, streak tracking
logs          — all daily captures (habit, mood, food, finance, study, social, reflection, strava_activity, health_metric)
records       — semi-permanent data (blood_test, body_comp, medical, dietary, decision, weekly_summary, brain_snapshot)
events        — calendar events (manual + Google Calendar imports)
domains       — extensible life tracking area configs (data-driven, zero code changes to add new areas)
conversations — full message history for context continuity
```

---

## Context Injection (What Claude Knows)

Every Claude API call receives a 4-tier context assembled from the database:

| Tier | Content | Decay |
|---|---|---|
| 1 | Goals, health profile, medical notes, dietary profile, tone preference — **prompt-cached** | Near-zero |
| 2 | All logs from the last 14 days | 14 days |
| 3 | Weekly summaries from the last 4 weeks | 4 weeks |
| 4 | Brain snapshot — agent-generated compressed long-term memory | Replaced weekly |

Prompt caching (Tier 1) reduces Claude API costs by up to 90% on repeated calls.

---

## Claude Tools

Claude has two tools it can call autonomously during conversation:

- **`search_web`** — calls Tavily API for live web search; Claude decides when to use it
- **`log_data`** — writes structured JSON directly to Supabase; no fragile text parsing

---

## Proactive Messages (Scheduler)

| Job | Time | What it does |
|---|---|---|
| Morning check-in | At your wake time | Summarises yesterday, lists today's events, asks for priorities |
| Evening review | ~2h before sleep | Covers all active domains: gym, food, mood, spend, study |
| Weekly summary | Sunday 8pm | Habits hit %, mood trend, study pace, spend pattern, standout wins, honest observation |
| Brain snapshot | Sunday after summary | Agent rewrites compressed long-term memory; saved to `records` |
| Nudge check | Every 6h | Fires a nudge if any domain hasn't been logged in `nudge_after_days` days |

---

## Planned Phases

| Phase | Feature | Status |
|---|---|---|
| 0 | Repo, environment, Supabase schema, CI/CD | Planning |
| 1 | Telegram bot skeleton, security guard, health endpoint, Docker | Planning |
| 2 | Full DB layer (all query functions) | Planning |
| 3 | Claude integration, tiered context, tool use (search + log) | Planning |
| 4 | Scheduled messages (morning, evening, weekly summary, brain snapshot) | Planning |
| 5 | Health records, file uploads, `/record` command, `/goals` command | Planning |
| 6 | Tavily web search validation and citation formatting | Planning |
| 7 | Decision log, brain snapshot schema, long-term memory coherence | Planning |
| 8 | Google Calendar OAuth + nightly sync | Planning |
| 9 | Strava OAuth + daily workout sync | Planning |
| 10 | Voice message support (Whisper transcription) | Planning |
| 11 | Apple Health via iPhone Shortcuts | Planning |
| 12 | Web dashboard (analytics + data visualisation) | Planned — detail TBD after Phase 4 |

See [PLAN.md](PLAN.md) for the detailed step-by-step implementation checklist.

### Dashboard (Phase 12 — after core is built)

A read-only analytics dashboard to visualise all logged data. To be built after Phase 4 once real data exists to display.

**Planned stack:**
- **Next.js 14** (App Router + TypeScript) — front-end framework
- **Tailwind CSS** — styling
- **Recharts** — charts and trend visualisations
- **Supabase JS client** — pulls data via server components
- **Vercel** — free hosting, one-click deploy

**Planned views:** habit streak heatmap · mood/energy trend lines · goal progress cards · weekly summary viewer · body composition history · finance spend over time · study hours · brain snapshot viewer

Auth approach and read-only vs interactive scope to be decided at build time.

---

## Repository Structure

```
life-agent/
|-- main.py              # Entry point — starts FastAPI + bot polling
|-- bot.py               # Telegram polling loop + message handlers
|-- scheduler.py         # APScheduler jobs (morning, evening, weekly)
|-- context.py           # Tiered context assembly for Claude calls
|-- db.py                # Supabase / PostgreSQL async query functions
|-- tools.py             # Claude tool definitions (search_web, log_data)
|-- config.py            # Loads .env vars via pydantic-settings
|-- Dockerfile
|-- docker-compose.yml
|-- requirements.txt
|-- .env.example         # Template (committed — no real values)
|-- .env                 # Real secrets (never committed — in .gitignore)
|-- .gitignore
|-- .github/
|   |-- workflows/
|       |-- deploy.yml   # GitHub Actions CI/CD
|-- LifeAgent_Requirements.tex  # Full requirements and architecture doc
|-- PLAN.md              # Phase-by-phase implementation checklist
|-- README.md            # This file
```

---

## Setup

### Prerequisites
- Python 3.12+
- Docker Desktop
- Supabase account (free tier)
- DigitalOcean droplet ($4/mo)
- API keys: Telegram, Anthropic, Tavily, OpenAI (Whisper)

### Local Development

```bash
# Clone and enter project
git clone git@github.com:<username>/life-agent.git
cd life-agent

# Install dependencies
pip install -r requirements.txt

# Copy and fill in secrets
cp .env.example .env
# Edit .env with your real API keys

# Run directly (no Docker needed for local dev)
python main.py
```

### Docker (Production)

```bash
docker-compose up --build -d

# View logs
docker-compose logs -f

# Check health
curl http://localhost:8000/health
```

### Deployment

Push to `main` → GitHub Actions automatically SSHs into your DigitalOcean droplet and runs:

```bash
cd /home/lifeagent/app
git pull origin main
docker-compose up --build -d
```

Requires `DROPLET_IP` and `SSH_PRIVATE_KEY` set as GitHub Actions secrets.

---

## Environment Variables

```bash
TELEGRAM_BOT_TOKEN=       # From @BotFather
TELEGRAM_USER_ID=         # Your Telegram user ID (from @userinfobot)
ANTHROPIC_API_KEY=        # From console.anthropic.com
TAVILY_API_KEY=           # From app.tavily.com
OPENAI_API_KEY=           # From platform.openai.com (Whisper)
DATABASE_URL=             # postgresql://postgres:password@db.<project>.supabase.co:5432/postgres
SUPABASE_URL=             # https://<project>.supabase.co
SUPABASE_SERVICE_KEY=     # Service role key from Supabase settings
GOOGLE_CLIENT_ID=         # Phase 8 — Google Calendar OAuth
GOOGLE_CLIENT_SECRET=     # Phase 8
GOOGLE_REDIRECT_URI=      # Phase 8
STRAVA_CLIENT_ID=         # Phase 9 — Strava OAuth
STRAVA_CLIENT_SECRET=     # Phase 9
APPLE_HEALTH_TOKEN=       # Phase 11 — static secret for iPhone Shortcut auth
```

---

## Security

- Bot only responds to the single Telegram user ID set in `TELEGRAM_USER_ID`. All other senders are silently ignored and logged.
- `.env` is in `.gitignore` and never committed.
- Database files (`*.db`, `*.sqlite`) are in `.gitignore`.
- Supabase handles all database backups automatically.
- OAuth refresh tokens stored in `users` table (encrypted at rest by Supabase).

---

## Documentation

- **[LifeAgent_Requirements.tex](LifeAgent_Requirements.tex)** — Full requirements, architecture, data model, agent logic, and build plan (LaTeX source)
- **[PLAN.md](PLAN.md)** — Phase-by-phase implementation checklist with detailed action items
