# Life Agent — Architecture Diagrams

> Last updated: April 2026. All diagrams reflect the final planned architecture.

---

## 1. System Overview

All components and their connections across the full stack.

```mermaid
graph TD
    classDef user     fill:#fff7ed,stroke:#ea580c,color:#9a3412,font-weight:bold
    classDef backend  fill:#dcfce7,stroke:#16a34a,color:#166534
    classDef llm      fill:#dbeafe,stroke:#3b82f6,color:#1e40af
    classDef data     fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef integr   fill:#f3e8ff,stroke:#9333ea,color:#6b21a8
    classDef cicd     fill:#fce7f3,stroke:#db2777,color:#9d174d

    %% ── User Interface ──────────────────────────────────────────────────────
    Mahir(["👤 Mahir\nTelegram App"]):::user
    iPhone(["📱 iPhone\nShortcuts App"]):::user

    %% ── Telegram Layer ───────────────────────────────────────────────────────
    TG["Telegram Bot API\n─────────────\nLong Polling\n(no domain / SSL needed)"]:::integr

    %% ── Backend — runs inside Docker on a $4/mo DigitalOcean Droplet ────────
    subgraph Droplet["  DigitalOcean Droplet · $4 / mo  "]
        subgraph Docker["  Docker Container · life-agent  "]
            Bot["bot.py\n─────────────\nPolling loop\nMessage handlers"]:::backend
            Security["Security Guard\n─────────────\nUser ID whitelist\nSilently drops all\nother senders"]:::backend
            Router["Message Router\n─────────────\nSlash command ?\nFree-form text ?\nVoice note ?\nPhoto / file ?"]:::backend
            Context["context.py\n─────────────\nTiered context\nassembly\n(4 tiers, see §3)"]:::backend
            Scheduler["scheduler.py\n─────────────\nAPScheduler jobs:\nMorning check-in\nEvening review\nWeekly summary\nBrain snapshot\nNudge check"]:::backend
            Tools["tools.py\n─────────────\nTool executor:\nsearch_web\nlog_data"]:::backend
            DB["db.py\n─────────────\nAsync query layer\n(asyncpg + SQLAlchemy)"]:::backend
            FastAPI["FastAPI\n─────────────\nGET  /health\nGET  /auth/google\nGET  /auth/strava\nPOST /health/apple"]:::backend
        end
    end

    %% ── LLM & AI Services ───────────────────────────────────────────────────
    Claude["Claude API\n─────────────\nclaude-sonnet-4-6\nNative tool use\nPrompt caching"]:::llm
    Tavily["Tavily API\n─────────────\nLive web search\npurpose-built for\nAI agents"]:::llm
    Whisper["OpenAI Whisper\n─────────────\nVoice → text\n(Phase 10)"]:::llm

    %% ── Data Layer ──────────────────────────────────────────────────────────
    Supabase[("Supabase\n─────────────\nManaged PostgreSQL\n7 tables\nAuto-backups\nBuilt-in dashboard")]:::data
    Storage[("Supabase Storage\n─────────────\nhealth-files bucket\nBlood test PDFs\nHealth photos")]:::data

    %% ── Third-Party Integrations ─────────────────────────────────────────────
    GCal["Google Calendar API\n─────────────\nOAuth 2.0\nNightly event sync\n(Phase 8)"]:::integr
    StravaAPI["Strava API\n─────────────\nOAuth 2.0\nDaily workout sync\n(Phase 9)"]:::integr

    %% ── CI/CD ────────────────────────────────────────────────────────────────
    GitHub["GitHub\n─────────────\nPublic repo\n(code + docs only;\nno secrets, no DB)"]:::cicd
    Actions["GitHub Actions\n─────────────\nPush to main →\nSSH into droplet →\ndocker-compose up"]:::cicd

    %% ── Flows ────────────────────────────────────────────────────────────────
    Mahir          -->|"text · voice · photo · file"| TG
    TG             -->|"polled every 1 s"| Bot
    Bot            --> Security
    Security       -->|"✓ ID match"| Router
    Security       -. "✗ silent drop + log" .-> Security

    Router         -->|"voice note"| Whisper
    Whisper        -->|"transcript text"| Context
    Router         -->|"free-form text"| Context
    Router         -->|"slash command\n(/done /goals /record)"| DB
    Router         -->|"file / photo upload"| FastAPI
    FastAPI        -->|"store file"| Storage
    FastAPI        -->|"Apple Health metrics"| DB

    Context        --> DB
    Context        -->|"system prompt +\nmessage history +\ntool definitions"| Claude

    Claude         -->|"tool_use: search_web"| Tools
    Claude         -->|"tool_use: log_data"| Tools
    Tools          -->|"Tavily query"| Tavily
    Tavily         -->|"results + citations"| Tools
    Tools          -->|"insert_log / insert_record"| DB
    Tools          -->|"tool_result"| Claude

    Claude         -->|"final response text"| Bot
    Bot            -->|"send_message"| TG
    TG             -->|"deliver"| Mahir

    Scheduler      -->|"proactive messages\n(no user trigger needed)"| Context

    GCal           -->|"OAuth · nightly sync\nevents → events table"| DB
    StravaAPI      -->|"OAuth · daily sync\nactivities → logs table"| DB
    iPhone         -->|"POST /health/apple\nsleep · HR · steps · HRV"| FastAPI

    DB             <-->|"async SQL\n(asyncpg)"| Supabase

    GitHub         -->|"push to main"| Actions
    Actions        -->|"SSH · git pull ·\ndocker-compose up --build -d"| Docker
```

---

## 2. Free-Form Message Flow

Step-by-step sequence for a typical free-form message that triggers both web search and a data write.

```mermaid
sequenceDiagram
    actor Mahir
    participant TG   as Telegram API
    participant Bot  as bot.py
    participant Ctx  as context.py
    participant DB   as db.py / Supabase
    participant AI   as Claude API
    participant Exec as tools.py
    participant Tav  as Tavily API

    Mahir ->> TG   : "What supplements help with sleep? Also log I went to gym."
    Bot  ->> TG    : poll (every 1 s)
    TG  -->> Bot   : new message received

    Note over Bot  : Security guard: update.effective_user.id == TELEGRAM_USER_ID ?
    Bot  ->> Bot   : ✓ Authorized — proceed

    Bot  ->> TG    : send typing action (...)

    %% ── Context Assembly ───────────────────────────────────────────────────
    Bot  ->> Ctx   : build_system_prompt(user_id)

    Ctx  ->> DB    : get_active_goals()
    DB  -->> Ctx   : goals + streaks

    Ctx  ->> DB    : get_records_by_type("blood_test", "body_comp", "medical", "dietary")
    DB  -->> Ctx   : health profile

    Ctx  ->> DB    : get_logs_since(days=14)
    DB  -->> Ctx   : 14-day habit / mood / food / finance / study logs

    Ctx  ->> DB    : get_records_by_type("weekly_summary", days=28)
    DB  -->> Ctx   : last 4 weekly summaries

    Ctx  ->> DB    : get_latest_brain_snapshot()
    DB  -->> Ctx   : compressed long-term memory

    Ctx  ->> DB    : get_active_domains()
    DB  -->> Ctx   : domain configs + prompt snippets

    Ctx -->> Bot   : assembled system prompt (Tier 1–4, prompt-cached)

    Bot  ->> DB    : get_recent_messages(limit=20)
    DB  -->> Bot   : conversation history

    %% ── First Claude Call ─────────────────────────────────────────────────
    Bot  ->> AI    : messages.create(system, messages, tools=[search_web, log_data])

    Note over AI   : Reasoning...<br/>Decides to call search_web for supplement question<br/>AND log_data for gym session

    AI  -->> Bot   : stop_reason="tool_use"<br/>tool[0]: search_web {query: "magnesium glycinate sleep research"}<br/>tool[1]: log_data {type: "habit", date: "2026-05-16", data: {completed: true}}

    %% ── Tool: search_web ───────────────────────────────────────────────────
    Bot  ->> Exec  : execute_tool("search_web", {query: ...})
    Exec ->> Tav   : tavily.search(query, search_depth="advanced")
    Tav -->> Exec  : results [{title, url, snippet}, ...]
    Exec -->> Bot  : formatted markdown string with citations

    %% ── Tool: log_data ────────────────────────────────────────────────────
    Bot  ->> Exec  : execute_tool("log_data", {type: "habit", ...})
    Exec ->> DB    : insert_log(user_id, "habit", "2026-05-16", {completed: true})
    DB  -->> Exec  : row inserted
    Exec ->> DB    : update_goal_streak(goal_id, current=7, longest=12)
    Exec -->> Bot  : "Gym session logged for 2026-05-16. Streak: 7 days."

    %% ── Second Claude Call (tool results injected) ────────────────────────
    Bot  ->> AI    : messages + tool_result blocks (both results)

    AI  -->> Bot   : stop_reason="end_turn"<br/>Final response text with supplement advice + gym confirmation

    %% ── Persist & Reply ───────────────────────────────────────────────────
    Bot  ->> DB    : save_message("user", original_message)
    Bot  ->> DB    : save_message("assistant", response)

    Bot  ->> TG    : send_message(response)
    TG  ->> Mahir  : reply (supplement advice + "Gym logged · streak: 7 days")
```

---

## 3. Context Tiers

What gets assembled into the Claude system prompt on every call.

```mermaid
graph LR
    classDef tier1 fill:#dcfce7,stroke:#16a34a,color:#166534
    classDef tier2 fill:#dbeafe,stroke:#3b82f6,color:#1e40af
    classDef tier3 fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef tier4 fill:#f3e8ff,stroke:#9333ea,color:#6b21a8
    classDef source fill:#f1f5f9,stroke:#94a3b8,color:#334155

    %% Sources
    U[("users table")]:::source
    G[("goals table")]:::source
    R[("records table")]:::source
    L[("logs table")]:::source
    D[("domains table")]:::source
    C[("conversations table")]:::source
    BS[("brain_snapshot\nrecord")]:::source

    %% Tiers
    T1["TIER 1 · Static Profile\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n• Name, timezone, wake / sleep time\n• Tone preference (Huberman / Hamza / flexible)\n• All active goals + is_non_negotiable + streaks\n• Latest blood test panel values\n• Latest body composition (InBody / DEXA)\n• Medical notes: injuries, conditions, medications\n• Dietary restrictions and current approach\n• Active domain prompt snippets\n• Philosophical frameworks (hardcoded)\n• Today's date + day of week\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n🔵 PROMPT-CACHED (up to 90% cost saving)\nDecay: near-zero — only changes when profile updates"]:::tier1

    T2["TIER 2 · Recent Logs (14-day window)\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n• Habit completions per goal (with dates)\n• Mood scores + energy levels\n• Food quality logs\n• Finance spend logs (amount, category, intentional?)\n• Study sessions (topic, duration, quality)\n• Reflection logs (drained by / energised by)\n• Strava activities (type, duration, HR, calories)\n• Apple Health metrics (sleep, resting HR, steps, HRV)\n━━━━━━━━━━━━━━━━━━━━━━━━━━\nDecay: 14 days — older entries roll out of context"]:::tier2

    T3["TIER 3 · Weekly Summaries (4-week window)\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n• Last 4 agent-generated weekly_summary records\n• Habits hit %, mood averages\n• Study hour totals\n• Spend patterns\n• Standout wins and honest observations\n━━━━━━━━━━━━━━━━━━━━━━━━━━\nDecay: 4 weeks — older summaries drop out"]:::tier3

    T4["TIER 4 · Brain Snapshot (long-term memory)\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n• Goal momentum status per goal\n• Open decisions logged\n• Key health flags (e.g. 'Low iron in last labs')\n• Momentum score 1–10\n• Patterns noticed across multiple weeks\n• Agent's weekly note on overall trajectory\n━━━━━━━━━━━━━━━━━━━━━━━━━━\nDecay: replaced every Sunday night\nCompresses all history older than 4 weeks"]:::tier4

    U & G & D  --> T1
    L          --> T2
    R          --> T3
    BS         --> T4

    T1 --> T2 --> T3 --> T4

    T4 -->|"Complete system prompt\n(all 4 tiers concatenated)"| Claude(["Claude API"])
    C  -->|"Last 20 messages\n(separate messages array)"| Claude
```

---

## 4. Database Schema

Entity-relationship diagram for all 7 tables.

```mermaid
erDiagram
    users {
        int     id                      PK
        bigint  telegram_user_id        UK
        text    name
        text    timezone
        time    wake_time
        time    sleep_target_time
        text    tone_preference
        text    google_refresh_token
        text    strava_refresh_token
        boolean onboarding_complete
        timestamptz created_at
    }

    goals {
        int     id                      PK
        int     user_id                 FK
        text    title
        text    description
        text    timeframe
        text    category
        boolean is_non_negotiable
        int     target_per_week
        int     current_streak
        int     longest_streak
        boolean active
        timestamptz created_at
        timestamptz updated_at
    }

    logs {
        int     id                      PK
        int     user_id                 FK
        text    type
        date    date
        int     goal_id                 FK
        jsonb   data
        text    notes
        timestamptz created_at
    }

    records {
        int     id                      PK
        int     user_id                 FK
        text    type
        date    date
        jsonb   data
        text    source
        text    file_url
        text    notes
        timestamptz created_at
    }

    events {
        int     id                      PK
        int     user_id                 FK
        text    title
        date    date
        text    type
        text    source
        text    notes
    }

    domains {
        int     id                      PK
        int     user_id                 FK
        text    name
        text    display_name
        boolean active
        text    evening_prompt
        int     context_decay_days
        int     nudge_after_days
        text    system_prompt_snippet
        timestamptz created_at
    }

    conversations {
        int     id                      PK
        int     user_id                 FK
        text    role
        text    content
        timestamptz timestamp
    }

    users ||--o{ goals         : "has"
    users ||--o{ logs          : "has"
    users ||--o{ records       : "has"
    users ||--o{ events        : "has"
    users ||--o{ domains       : "has"
    users ||--o{ conversations : "has"
    goals ||--o{ logs          : "linked via goal_id"
```

**`logs.type` values:** `habit` · `mood` · `food` · `finance` · `study` · `social` · `reflection` · `strava_activity` · `health_metric`

**`records.type` values:** `blood_test` · `body_comp` · `medical` · `dietary` · `decision` · `weekly_summary` · `brain_snapshot`

**`events.source` values:** `manual` · `google_calendar`

**`logs.data` JSONB examples:**
```json
habit:      { "goal_id": 3, "completed": true }
mood:       { "score": 7, "energy": 6 }
food:       { "description": "chicken rice veg", "quality": 8 }
finance:    { "amount": 45, "category": "food delivery", "intentional": false }
study:      { "topic": "CFA Fixed Income", "duration_min": 90, "quality": "focused" }
reflection: { "drained_by": "...", "energised_by": "...", "on_mind": "..." }
strava:     { "name": "Morning Run", "type": "Run", "duration_sec": 2700,
              "distance_m": 5000, "average_heartrate": 152, "calories": 380 }
health:     { "sleep_hours": 7.2, "resting_hr": 58, "steps": 9400, "hrv": 42 }
```

---

## 5. Scheduler Jobs

Proactive message cadence — no user action required.

```mermaid
graph LR
    classDef job     fill:#dcfce7,stroke:#16a34a,color:#166534
    classDef trigger fill:#dbeafe,stroke:#3b82f6,color:#1e40af
    classDef output  fill:#fff7ed,stroke:#ea580c,color:#9a3412

    APScheduler["APScheduler\n(in-process,\nstarts with app)"]

    Morning["Morning Check-In\n─────────────\nTrigger: daily @ wake_time\n(user's timezone)\n─────────────\n1. Pull yesterday's performance\n2. Pull today's events\n3. Claude crafts personalised\n   check-in message\n4. Ask for today's priorities"]:::job

    Evening["Evening Review\n─────────────\nTrigger: daily @ sleep_time − 2h\n─────────────\n1. Loop active domains\n2. Use evening_prompt per domain\n3. Standard: gym · food · mood ·\n   energy · spend · study\n4. 'Anything on your mind?'"]:::job

    Weekly["Weekly Summary\n─────────────\nTrigger: Sunday @ 20:00\n─────────────\n1. Fetch 7-day logs + records\n2. Habits hit % · mood avg\n3. Study hours · spend pattern\n4. Standout wins\n5. One honest observation\n6. Saves record (weekly_summary)"]:::job

    Snapshot["Brain Snapshot\n─────────────\nTrigger: Sunday @ 20:30\n(after weekly summary)\n─────────────\n1. Read this week's data\n2. Rewrite compressed memory\n3. Saves record (brain_snapshot)\n4. Used in Tier 4 context"]:::job

    Nudge["Nudge Check\n─────────────\nTrigger: every 6 hours\n─────────────\n1. For each active domain\n   where nudge_after_days set:\n2. Check last log date\n3. If gap ≥ nudge_after_days\n   → send nudge message\n4. Rate limit: 1 nudge/domain/day"]:::job

    GCalSync["Google Calendar Sync\n─────────────\nTrigger: daily @ midnight\n─────────────\n1. Refresh OAuth token\n2. Fetch tomorrow's events\n3. Upsert into events table\n   (source='google_calendar')"]:::job

    StravaSync["Strava Sync\n─────────────\nTrigger: daily @ 01:00\n─────────────\n1. Refresh OAuth token\n2. Fetch yesterday's activities\n3. Insert into logs table\n   (type='strava_activity')\n4. Update goal streak if\n   gym session detected"]:::job

    APScheduler --> Morning
    APScheduler --> Evening
    APScheduler --> Weekly
    APScheduler --> Snapshot
    APScheduler --> Nudge
    APScheduler --> GCalSync
    APScheduler --> StravaSync

    Morning  -->|"Telegram message"| Mahir(["👤 Mahir"]):::output
    Evening  -->|"Telegram message"| Mahir
    Weekly   -->|"Telegram message\n+ DB record"| Mahir
    Snapshot -->|"DB record only\n(no message)"| Mahir
    Nudge    -->|"Telegram message\n(conditional)"| Mahir
    GCalSync -->|"events table rows"| DB[("Supabase")]:::output
    StravaSync -->|"logs table rows"| DB
```

---

## 6. CI/CD Pipeline

```mermaid
graph LR
    classDef dev  fill:#dbeafe,stroke:#3b82f6,color:#1e40af
    classDef ci   fill:#fce7f3,stroke:#db2777,color:#9d174d
    classDef prod fill:#dcfce7,stroke:#16a34a,color:#166534

    Dev["Local Dev Machine\n─────────────\npython main.py\n(or docker-compose up)\n.env has real secrets\nnever committed"]:::dev

    Push["git push origin main\n─────────────\nOnly code + docs\nNo .env, no *.db\nNo secrets of any kind"]:::dev

    GitHub["GitHub\n─────────────\nPublic repository\nlife-agent"]:::ci

    Actions["GitHub Actions\n─────────────\ndeploy.yml triggers\non push to main\nuses appleboy/ssh-action"]:::ci

    Secrets["GitHub Secrets\n─────────────\nDROPLET_IP\nSSH_PRIVATE_KEY\n(never in repo)"]:::ci

    SSH["SSH into Droplet\n─────────────\nuser: lifeagent\n/home/lifeagent/app"]:::prod

    Commands["Deploy Commands\n─────────────\ngit pull origin main\ndocker-compose up\n  --build -d"]:::prod

    Droplet["DigitalOcean Droplet\n─────────────\nDocker container\nrunning life-agent\n.env stored on server\n(never in git)"]:::prod

    Health["Health Check\n─────────────\nGET /health\nDocker restarts\ncontainer on failure"]:::prod

    Dev    --> Push --> GitHub
    GitHub --> Actions
    Secrets -.->|"injected at runtime"| Actions
    Actions --> SSH --> Commands --> Droplet
    Droplet --> Health
    Health  -.->|"failure → auto-restart"| Droplet
```
