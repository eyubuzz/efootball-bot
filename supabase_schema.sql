-- eFootball Q&A Bot — Supabase Schema
-- Safe to run multiple times (uses IF NOT EXISTS / IF NOT EXISTS for columns)

CREATE TABLE IF NOT EXISTS questions (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         BIGINT NOT NULL,
    username        TEXT,
    full_name       TEXT,
    question        TEXT NOT NULL,
    status          TEXT DEFAULT 'pending',
    tag             TEXT DEFAULT '',
    created_at      TEXT,
    answered_at     TEXT,
    channel_msg_id  BIGINT,
    photo_file_id   TEXT,
    post_number     INTEGER,
    voice_file_id   TEXT
);
-- Add columns that may be missing if the table already existed
ALTER TABLE questions ADD COLUMN IF NOT EXISTS full_name       TEXT;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS answered_at     TEXT;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS channel_msg_id  BIGINT;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS photo_file_id   TEXT;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS post_number     INTEGER;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS voice_file_id   TEXT;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS tag             TEXT DEFAULT '';

CREATE TABLE IF NOT EXISTS comments (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    question_id     BIGINT NOT NULL,
    user_id         BIGINT NOT NULL,
    username        TEXT,
    full_name       TEXT,
    comment         TEXT NOT NULL DEFAULT '',
    photo_file_id   TEXT,
    voice_file_id   TEXT,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS comment_votes (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    comment_id  BIGINT NOT NULL,
    user_id     BIGINT NOT NULL,
    vote_type   TEXT NOT NULL,
    created_at  TEXT,
    UNIQUE(comment_id, user_id)
);

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id     BIGINT PRIMARY KEY,
    full_name   TEXT,
    username    TEXT,
    visible     INTEGER DEFAULT 0,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS follows (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    follower_id  BIGINT NOT NULL,
    following_id BIGINT NOT NULL,
    created_at   TEXT,
    UNIQUE(follower_id, following_id)
);

CREATE TABLE IF NOT EXISTS admin_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS scheduled_posts (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    text          TEXT,
    photo_file_id TEXT,
    buttons_json  TEXT DEFAULT '[]',
    pin           INTEGER DEFAULT 0,
    scheduled_at  TEXT,
    published     INTEGER DEFAULT 0,
    created_at    TEXT
);

-- IMPORTANT: Disable Row Level Security on all tables.
-- The bot uses the service_role key which bypasses RLS anyway,
-- but disabling it here ensures the anon key also works.
ALTER TABLE questions       DISABLE ROW LEVEL SECURITY;
ALTER TABLE comments        DISABLE ROW LEVEL SECURITY;
ALTER TABLE comment_votes   DISABLE ROW LEVEL SECURITY;
ALTER TABLE user_profiles   DISABLE ROW LEVEL SECURITY;
ALTER TABLE follows         DISABLE ROW LEVEL SECURITY;
ALTER TABLE admin_settings  DISABLE ROW LEVEL SECURITY;
ALTER TABLE scheduled_posts DISABLE ROW LEVEL SECURITY;
