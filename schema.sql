-- Life Agent -- Database Schema
-- Run in Supabase SQL Editor (Dashboard -> SQL Editor -> New query)

CREATE TABLE users (
    id                   SERIAL PRIMARY KEY,
    telegram_user_id     BIGINT UNIQUE NOT NULL,
    name                 TEXT,
    timezone             TEXT DEFAULT 'UTC',
    wake_time            TIME DEFAULT '07:00',
    sleep_target_time    TIME DEFAULT '23:00',
    tone_preference      TEXT DEFAULT 'flexible',
    google_refresh_token TEXT,
    strava_refresh_token TEXT,
    onboarding_complete  BOOLEAN DEFAULT FALSE,
    created_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE goals (
    id                 SERIAL PRIMARY KEY,
    user_id            INT REFERENCES users(id) ON DELETE CASCADE,
    title              TEXT NOT NULL,
    description        TEXT,
    timeframe          TEXT,
    category           TEXT,
    is_non_negotiable  BOOLEAN DEFAULT FALSE,
    target_per_week    INT,
    current_streak     INT DEFAULT 0,
    longest_streak     INT DEFAULT 0,
    active             BOOLEAN DEFAULT TRUE,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE logs (
    id         SERIAL PRIMARY KEY,
    user_id    INT REFERENCES users(id) ON DELETE CASCADE,
    type       TEXT NOT NULL,
    date       DATE NOT NULL,
    goal_id    INT REFERENCES goals(id) ON DELETE SET NULL,
    data       JSONB,
    notes      TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_logs_user_date ON logs(user_id, date);

CREATE TABLE records (
    id         SERIAL PRIMARY KEY,
    user_id    INT REFERENCES users(id) ON DELETE CASCADE,
    type       TEXT NOT NULL,
    date       DATE NOT NULL,
    data       JSONB,
    source     TEXT,
    file_url   TEXT,
    notes      TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_records_user_type_date ON records(user_id, type, date);

CREATE TABLE events (
    id      SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    title   TEXT NOT NULL,
    date    DATE NOT NULL,
    type    TEXT,
    source  TEXT DEFAULT 'manual',
    notes   TEXT
);

CREATE TABLE domains (
    id                    SERIAL PRIMARY KEY,
    user_id               INT REFERENCES users(id) ON DELETE CASCADE,
    name                  TEXT NOT NULL,
    display_name          TEXT,
    active                BOOLEAN DEFAULT TRUE,
    evening_prompt        TEXT,
    context_decay_days    INT DEFAULT 14,
    nudge_after_days      INT,
    system_prompt_snippet TEXT,
    created_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE conversations (
    id        SERIAL PRIMARY KEY,
    user_id   INT REFERENCES users(id) ON DELETE CASCADE,
    role      TEXT NOT NULL,
    content   TEXT NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_conversations_user_timestamp ON conversations(user_id, timestamp);
