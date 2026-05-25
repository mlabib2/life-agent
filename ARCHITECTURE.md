# Life Agent — Architecture Diagrams

> Last updated: May 2026. Diagrams reflect the current implemented architecture (Phases 0–10 complete).

---

## 1. System Overview

```mermaid
graph TD
    classDef user     fill:#fff7ed,stroke:#ea580c,color:#9a3412,font-weight:bold
    classDef backend  fill:#dcfce7,stroke:#16a34a,color:#166534
    classDef llm      fill:#dbeafe,stroke:#3b82f6,color:#1e40af
    classDef data     fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef integr   fill:#f3e8ff,stroke:#9333ea,color:#6b21a8

    Mahir(["👤 Mahir\nTelegram App"]):::user

    TG["Telegram Bot API\n─────────────\nLong Polling\n(no domain / SSL needed)"]:::integr

    subgraph Droplet["  Docker Container · life-agent  "]
        Bot["bot/handlers.py\n─────────────\nMessage handlers\nTwo-step pipeline\nVoice transcription"]:::backend
        Security["Security Guard\n─────────────\nTELEGRAM_USER_ID\nwhitelist only"]:::backend
        Scheduler["scheduler/jobs.py\n─────────────\nAPScheduler:\n5 proactive jobs"]:::backend
        Context["agent/context.py\n─────────────\nTiered context\nassembly"]:::backend
        Tools["agent/tools.py\n─────────────\n9 tools:\nlog_data, delete_log\nstore_record\ncalendar CRUD\nstrava, search_web"]:::backend
        DB["db/__init__.py\n─────────────\nSupabase sync\nquery layer"]:::backend
        FastAPI["main.py / FastAPI\n─────────────\nGET  /health\nGET  /auth/google\nGET  /auth/strava"]:::backend
    end

    Claude_Haiku["Claude Haiku\n─────────────\nclaude-haiku-4-5\ntool_choice=any\nStep 1: extraction"]:::llm
    Claude_Sonnet["Claude Sonnet\n─────────────\nclaude-sonnet-4-6\ntool_choice=auto\nStep 2: conversation"]:::llm
    Tavily["Tavily API\n─────────────\nLive web search"]:::llm
    Whisper["OpenAI Whisper\n─────────────\nVoice → text"]:::llm

    Supabase[("Supabase\n─────────────\nManaged PostgreSQL\n6 tables\nAuto-backups")]:::data
    Storage[("Supabase Storage\n─────────────\nhealth-files bucket")]:::data

    GCal["Google Calendar API\n─────────────\nOAuth 2.0\nNightly event sync"]:::integr
    StravaAPI["Strava API\n─────────────\nOAuth 2.0\nDaily workout sync"]:::integr

    Mahir          -->|"text · voice · photo"| TG
    TG             -->|"polled every 1 s"| Bot
    Bot            --> Security
    Security       -->|"✓ ID match"| Bot

    Bot            -->|"voice note"| Whisper
    Whisper        -->|"transcript"| Bot

    Bot            -->|"Step 1"| Claude_Haiku
    Claude_Haiku   -->|"log_data calls"| Tools
    Tools          -->|"write_log"| DB

    Bot            -->|"Step 2"| Context
    Context        --> DB
    Context        -->|"system + history + tools"| Claude_Sonnet

    Claude_Sonnet  -->|"search_web"| Tavily
    Claude_Sonnet  -->|"calendar / strava / delete"| Tools
    Tools          -->|"tool_result"| Claude_Sonnet
    Claude_Sonnet  -->|"final reply"| Bot
    Bot            -->|"send_message"| TG
    TG             -->|"deliver"| Mahir

    Scheduler      -->|"proactive messages"| Context

    GCal           -->|"nightly sync 00:05 HKT"| DB
    StravaAPI      -->|"nightly sync 00:10 HKT"| DB

    DB             <-->|"sync HTTP"| Supabase
    FastAPI        -->|"file upload"| Storage
```

---

## 2. Two-Step Message Flow

Detailed sequence for a free-form message through the extraction + conversation pipeline.

```mermaid
sequenceDiagram
    actor Mahir
    participant TG      as Telegram API
    participant Bot     as bot/handlers.py
    participant Haiku   as Claude Haiku (Step 1)
    participant DB      as db/__init__.py / Supabase
    participant Sonnet  as Claude Sonnet (Step 2)
    participant Tools   as agent/tools.py
    participant Tavily  as Tavily API

    Mahir  ->> TG    : "Did gym, chest day 75min. Had rice for lunch. Spent 80 HKD on food."
    Bot    ->> TG    : poll (every 1 s)
    TG    -->> Bot   : new message

    Note over Bot    : Security guard: user_id == TELEGRAM_USER_ID?
    Bot    ->> TG    : send typing action

    %% ── Step 1: Forced Extraction ────────────────────────────────────────────
    Note over Bot,Haiku : Step 1 — Haiku with tool_choice=any

    Bot    ->> Haiku : messages.create(system=extraction_prompt, tool_choice=any,<br/>tools=[log_data, nothing_to_log])

    Haiku -->> Bot   : stop_reason=tool_use<br/>log_data {type:habit, data:{name:gym, duration_min:75}}<br/>log_data {type:food, data:{description:rice for lunch}}<br/>log_data {type:finance, data:{amount:80, currency:HKD}}

    Bot    ->> Tools : handle_tool_call("log_data", habit)
    Tools  ->> DB    : write_log(type=habit, goal_id=<linked>, data=...)
    DB    -->> Tools : row inserted

    Bot    ->> Tools : handle_tool_call("log_data", food)
    Tools  ->> DB    : write_log(type=food ...)

    Bot    ->> Tools : handle_tool_call("log_data", finance)
    Tools  ->> DB    : write_log(type=finance ...)

    Note over Bot    : 3 items logged. reset_db() — fresh Supabase connection.

    %% ── Step 2: Conversation ─────────────────────────────────────────────────
    Note over Bot,Sonnet : Step 2 — Sonnet with tools except log_data

    Bot    ->> DB    : build_context() — goals, 14-day logs, records, brain snapshot
    DB    -->> Bot   : context assembled

    Bot    ->> Sonnet: messages.create(system=context + "3 items logged",<br/>tools=[delete_log, store_record, calendar, strava, search_web])

    Note over Sonnet : No tool call needed — confirms logged items in reply

    Sonnet -->> Bot  : "Logged: gym (75min chest day), lunch, 80 HKD food spend."

    Bot    ->> DB    : save_message(user, original_text)
    Bot    ->> DB    : save_message(assistant, reply)
    Bot    ->> TG    : send_message(reply)
    TG     ->> Mahir : "Logged: gym (75min chest day), lunch, 80 HKD food spend."
```

---

## 3. Context Assembly

What gets injected into the Sonnet system prompt on every Step 2 call.

```mermaid
graph LR
    classDef source fill:#f1f5f9,stroke:#94a3b8,color:#334155
    classDef section fill:#dcfce7,stroke:#16a34a,color:#166534

    U[("users")]:::source
    G[("goals")]:::source
    L[("logs")]:::source
    R[("records")]:::source
    C[("conversations")]:::source

    S1["## Current Date & Time\n────────────────────\nDate + weekday (HKT)\nInjected every call\n(prevents year drift)"]:::section

    S2["## User Profile\n────────────────────\nName, timezone\nWake time, sleep target\nTone preference"]:::section

    S3["## Active Goals\n────────────────────\nTitle + description\nNon-negotiable flag\nWeekly target + streak"]:::section

    S4["## Last 14 Days of Logs\n────────────────────\nAll log types:\nhabit, food, finance\nsleep, mood, study\nsocial, health_metric\nstrava_activity"]:::section

    S5["## Health Records\n────────────────────\nLatest body comp\nLatest blood test\nDietary profile\nRecent medical notes"]:::section

    S6["## Recent Decisions\n────────────────────\nLast 5 decision records\nwith choice + reasoning"]:::section

    S7["## Long-term Memory Snapshot\n────────────────────\nMomentum score\nGoal status + streaks\nHealth flags\nPatterns noticed\nOpen decisions\nWeekly note"]:::section

    U --> S2
    G --> S3
    L --> S4
    R --> S5
    R --> S6
    R --> S7

    S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7

    S7 -->|"Complete system prompt"| Sonnet(["Claude Sonnet"])
    C  -->|"Last 20 messages\n(messages array)"| Sonnet
```

---

## 4. Database Schema

```mermaid
erDiagram
    users {
        int         id                  PK
        bigint      telegram_user_id    UK
        text        name
        text        timezone
        time        wake_time
        time        sleep_target_time
        text        tone_preference
        text        google_refresh_token
        text        strava_refresh_token
        timestamptz created_at
    }

    goals {
        int         id                  PK
        int         user_id             FK
        text        title
        text        description
        boolean     is_non_negotiable
        int         target_per_week
        int         current_streak
        int         longest_streak
        boolean     active
        timestamptz created_at
        timestamptz updated_at
    }

    logs {
        int         id                  PK
        int         user_id             FK
        text        type
        date        date
        int         goal_id             FK
        jsonb       data
        text        notes
        timestamptz created_at
    }

    records {
        int         id                  PK
        int         user_id             FK
        text        type
        date        date
        jsonb       data
        text        source
        text        notes
        timestamptz created_at
    }

    events {
        int         id                  PK
        int         user_id             FK
        text        title
        date        date
        text        type
        text        source
        text        notes
    }

    conversations {
        int         id                  PK
        int         user_id             FK
        text        role
        text        content
        timestamptz timestamp
    }

    users ||--o{ goals         : "has"
    users ||--o{ logs          : "has"
    users ||--o{ records       : "has"
    users ||--o{ events        : "has"
    users ||--o{ conversations : "has"
    goals ||--o{ logs          : "goal_id"
```

**`logs.type`:** `habit` · `mood` · `food` · `finance` · `study` · `social` · `strava_activity` · `health_metric`

**`records.type`:** `blood_test` · `body_comp` · `medical` · `dietary` · `decision` · `brain_snapshot`

**`events.source`:** `manual` · `google_calendar`

---

## 5. Scheduler Jobs

Five APScheduler jobs running inside the FastAPI process (same event loop).

```mermaid
graph LR
    classDef job     fill:#dcfce7,stroke:#16a34a,color:#166534
    classDef output  fill:#fff7ed,stroke:#ea580c,color:#9a3412

    APScheduler["AsyncIOScheduler\n(shares FastAPI\nevent loop)"]

    GCalSync["Google Calendar Sync\n─────────────\nTrigger: daily 00:05 HKT\n─────────────\n1. Refresh OAuth token\n2. Fetch next 7 days\n3. Delete-then-insert\n   per (user, date, source)\n4. events table updated"]:::job

    StravaSync["Strava Sync\n─────────────\nTrigger: daily 00:10 HKT\n─────────────\n1. Refresh access token\n2. Fetch 2 days back (UTC)\n3. Filter by yesterday HKT\n4. Delete-then-insert\n5. Dedup: Strava gym wins\n   over manual habit log"]:::job

    Morning["Morning Check-In\n─────────────\nTrigger: Mon–Fri 06:40 HKT\n─────────────\n1. Yesterday's performance\n2. Today's calendar events\n3. Claude crafts check-in\n4. Ask for priorities"]:::job

    Evening["Evening Review\n─────────────\nTrigger: daily 21:00 HKT\n─────────────\n1. Gym · food · mood\n2. Spend · study\n3. Anything on your mind?"]:::job

    Weekly["Weekly Summary\n+ Brain Snapshot\n─────────────\nTrigger: Sunday 20:00 HKT\n─────────────\n1. 7-day habit hit %\n2. Mood + study + spend\n3. Saves brain_snapshot record\n4. Sends Telegram summary"]:::job

    APScheduler --> GCalSync
    APScheduler --> StravaSync
    APScheduler --> Morning
    APScheduler --> Evening
    APScheduler --> Weekly

    GCalSync   -->|"events table"| DB[("Supabase")]:::output
    StravaSync -->|"logs table"| DB
    Morning    -->|"Telegram message"| Mahir(["👤 Mahir"]):::output
    Evening    -->|"Telegram message"| Mahir
    Weekly     -->|"Telegram message\n+ brain_snapshot record"| Mahir
```

---

## 6. Goal ID Auto-Linking

When Haiku logs a `habit`, `handle_tool_call` automatically links it to the matching goal.

```
log_data called with type=habit, data={name: "gym"}
    |
    v
get_goal_by_name(user_id, "gym")
    — fuzzy match: name_lower in goal.title.lower()
    |
    +--> match found  → write_log(..., goal_id=goal["id"])
    |                   Strava dedup and streak logic can now find this log
    |
    +--> no match     → write_log(..., goal_id=None)
                        stored but not linked to streak tracking
```

This means dense voice notes ("did gym, took creatine, went for a run") are correctly linked to their goals without any manual input.
