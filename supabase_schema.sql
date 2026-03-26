-- eFootball Q&A Bot — Supabase Schema
-- Run this ONCE in Supabase → SQL Editor → New Query

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
