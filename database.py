import os
import sqlite3
from datetime import datetime

DB_FILE = os.getenv("DATABASE_PATH", "questions.db")


def _conn():
    c = sqlite3.connect(DB_FILE)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    conn = _conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL,
            username       TEXT,
            full_name      TEXT,
            question       TEXT NOT NULL,
            status         TEXT DEFAULT 'pending',
            tag            TEXT DEFAULT '',
            created_at     TEXT,
            answered_at    TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id       INTEGER NOT NULL,
            user_id           INTEGER NOT NULL,
            username          TEXT,
            full_name         TEXT,
            comment           TEXT NOT NULL,
            created_at        TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS comment_votes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            comment_id  INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            vote_type   TEXT NOT NULL,
            created_at  TEXT,
            UNIQUE(comment_id, user_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id    INTEGER PRIMARY KEY,
            full_name  TEXT,
            username   TEXT,
            visible    INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS follows (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            follower_id  INTEGER NOT NULL,
            following_id INTEGER NOT NULL,
            created_at   TEXT,
            UNIQUE(follower_id, following_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS admin_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            text          TEXT,
            photo_file_id TEXT,
            buttons_json  TEXT DEFAULT '[]',
            pin           INTEGER DEFAULT 0,
            scheduled_at  TEXT,
            published     INTEGER DEFAULT 0,
            created_at    TEXT
        )
    """)

    # Migrations for existing databases
    for migration in [
        "ALTER TABLE questions ADD COLUMN channel_msg_id INTEGER",
        "ALTER TABLE questions ADD COLUMN photo_file_id  TEXT",
        "ALTER TABLE questions ADD COLUMN post_number    INTEGER",
        "ALTER TABLE questions ADD COLUMN voice_file_id  TEXT",
        "ALTER TABLE comments  ADD COLUMN photo_file_id  TEXT",
        "ALTER TABLE comments  ADD COLUMN voice_file_id  TEXT",
    ]:
        try:
            c.execute(migration)
        except sqlite3.OperationalError:
            pass  # column already exists

    conn.commit()
    conn.close()


# ── Questions ─────────────────────────────────────────────────────────────────

def save_question(user_id: int, username: str, full_name: str, question: str,
                  photo_file_id: str = None, voice_file_id: str = None) -> int:
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO questions (user_id, username, full_name, question, photo_file_id, voice_file_id, status, created_at) VALUES (?,?,?,?,?,?,'pending',?)",
        (user_id, username, full_name, question, photo_file_id, voice_file_id, datetime.now().isoformat()),
    )
    qid = c.lastrowid
    conn.commit()
    conn.close()
    return qid


def get_question(question_id: int):
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
    row = c.fetchone()
    conn.close()
    return row


def next_post_number() -> int:
    """Return the next sequential channel post number (max approved post_number + 1)."""
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT COALESCE(MAX(post_number), 0) FROM questions WHERE status='approved'")
    n = c.fetchone()[0] + 1
    conn.close()
    return n


def assign_post_number(question_id: int, number: int):
    conn = _conn()
    c = conn.cursor()
    c.execute("UPDATE questions SET post_number=? WHERE id=?", (number, question_id))
    conn.commit()
    conn.close()


def reset_questions():
    """Wipe all questions, comments, and votes. Post counter resets to 0."""
    conn = _conn()
    c = conn.cursor()
    for table in ("comment_votes", "comments", "questions"):
        c.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()


def update_status(question_id: int, status: str, tag: str = ""):
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "UPDATE questions SET status=?, tag=?, answered_at=? WHERE id=?",
        (status, tag, datetime.now().isoformat(), question_id),
    )
    conn.commit()
    conn.close()


def set_channel_msg_id(question_id: int, msg_id: int):
    conn = _conn()
    c = conn.cursor()
    c.execute("UPDATE questions SET channel_msg_id=? WHERE id=?", (msg_id, question_id))
    conn.commit()
    conn.close()


def get_all_questions_export() -> list:
    """Return all questions with comment counts for PDF export."""
    conn = _conn()
    c = conn.cursor()
    c.execute("""
        SELECT q.id, q.post_number, q.full_name, q.username, q.question,
               q.status, q.tag, q.created_at,
               (SELECT COUNT(*) FROM comments WHERE question_id=q.id) AS comment_count
        FROM questions q
        ORDER BY q.id ASC
    """)
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT status, COUNT(*) FROM questions GROUP BY status")
    rows = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}


# ── Comments ──────────────────────────────────────────────────────────────────

def save_comment(question_id: int, user_id: int, username: str, full_name: str,
                 comment: str = "", photo_file_id: str = None, voice_file_id: str = None) -> int:
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO comments (question_id, user_id, username, full_name, comment, photo_file_id, voice_file_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (question_id, user_id, username, full_name, comment, photo_file_id, voice_file_id, datetime.now().isoformat()),
    )
    cid = c.lastrowid
    conn.commit()
    conn.close()
    return cid


def get_comment_count(question_id: int) -> int:
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM comments WHERE question_id=?", (question_id,))
    count = c.fetchone()[0]
    conn.close()
    return count


def get_comments_page(question_id: int, page: int = 1, per_page: int = 3):
    """Return (list_of_dicts, total_count)."""
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM comments WHERE question_id=?", (question_id,))
    total = c.fetchone()[0]
    offset = (page - 1) * per_page
    c.execute("""
        SELECT
            cm.id, cm.user_id, cm.username, cm.full_name, cm.comment,
            cm.photo_file_id, cm.voice_file_id, cm.created_at,
            (SELECT COUNT(*) FROM comment_votes WHERE comment_id=cm.id AND vote_type='up')   AS likes,
            (SELECT COUNT(*) FROM comment_votes WHERE comment_id=cm.id AND vote_type='down') AS dislikes
        FROM comments cm
        WHERE cm.question_id=?
        ORDER BY cm.created_at ASC
        LIMIT ? OFFSET ?
    """, (question_id, per_page, offset))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows], total


# ── Votes ─────────────────────────────────────────────────────────────────────

def vote_comment(comment_id: int, user_id: int, vote_type: str):
    """Toggle vote. Returns (likes, dislikes) after the operation."""
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "SELECT vote_type FROM comment_votes WHERE comment_id=? AND user_id=?",
        (comment_id, user_id),
    )
    existing = c.fetchone()
    if existing:
        if existing["vote_type"] == vote_type:
            c.execute(
                "DELETE FROM comment_votes WHERE comment_id=? AND user_id=?",
                (comment_id, user_id),
            )
        else:
            c.execute(
                "UPDATE comment_votes SET vote_type=?, created_at=? WHERE comment_id=? AND user_id=?",
                (vote_type, datetime.now().isoformat(), comment_id, user_id),
            )
    else:
        c.execute(
            "INSERT INTO comment_votes (comment_id, user_id, vote_type, created_at) VALUES (?,?,?,?)",
            (comment_id, user_id, vote_type, datetime.now().isoformat()),
        )
    conn.commit()
    c.execute("SELECT COUNT(*) FROM comment_votes WHERE comment_id=? AND vote_type='up'",   (comment_id,))
    likes = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM comment_votes WHERE comment_id=? AND vote_type='down'", (comment_id,))
    dislikes = c.fetchone()[0]
    conn.close()
    return likes, dislikes


# ── User profiles ─────────────────────────────────────────────────────────────

def ensure_user_profile(user_id: int, full_name: str, username: str):
    conn = _conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO user_profiles (user_id, full_name, username, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET full_name=excluded.full_name, username=excluded.username
    """, (user_id, full_name, username, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_user_profile(user_id: int):
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT * FROM user_profiles WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row


def set_user_visibility(user_id: int, visible: bool):
    conn = _conn()
    c = conn.cursor()
    c.execute("UPDATE user_profiles SET visible=? WHERE user_id=?", (int(visible), user_id))
    conn.commit()
    conn.close()


def get_discoverable_users(exclude_id: int, page: int = 1, per_page: int = 5):
    """Return (list_of_dicts, total) of visible users excluding the requesting user."""
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM user_profiles WHERE visible=1 AND user_id!=?", (exclude_id,))
    total = c.fetchone()[0]
    offset = (page - 1) * per_page
    c.execute("""
        SELECT user_id, full_name, username FROM user_profiles
        WHERE visible=1 AND user_id!=?
        ORDER BY created_at ASC
        LIMIT ? OFFSET ?
    """, (exclude_id, per_page, offset))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows], total


# ── Follows ───────────────────────────────────────────────────────────────────

def follow_user(follower_id: int, following_id: int):
    conn = _conn()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO follows (follower_id, following_id, created_at) VALUES (?,?,?)",
            (follower_id, following_id, datetime.now().isoformat()),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()


def unfollow_user(follower_id: int, following_id: int):
    conn = _conn()
    c = conn.cursor()
    c.execute("DELETE FROM follows WHERE follower_id=? AND following_id=?", (follower_id, following_id))
    conn.commit()
    conn.close()


def is_following(follower_id: int, following_id: int) -> bool:
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM follows WHERE follower_id=? AND following_id=?", (follower_id, following_id))
    result = c.fetchone() is not None
    conn.close()
    return result


def get_follower_count(user_id: int) -> int:
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM follows WHERE following_id=?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count


def get_following_count(user_id: int) -> int:
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM follows WHERE follower_id=?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count


def get_followers_list(user_id: int):
    conn = _conn()
    c = conn.cursor()
    c.execute("""
        SELECT up.user_id, up.full_name, up.username
        FROM follows f
        JOIN user_profiles up ON up.user_id = f.follower_id
        WHERE f.following_id=?
        ORDER BY f.created_at DESC
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_following_list(user_id: int):
    conn = _conn()
    c = conn.cursor()
    c.execute("""
        SELECT up.user_id, up.full_name, up.username
        FROM follows f
        JOIN user_profiles up ON up.user_id = f.following_id
        WHERE f.follower_id=?
        ORDER BY f.created_at DESC
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── User stats ────────────────────────────────────────────────────────────────

def get_user_aura(user_id: int) -> int:
    """Aura = total upvotes received on the user's comments."""
    conn = _conn()
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*) FROM comment_votes cv
        JOIN comments cm ON cv.comment_id = cm.id
        WHERE cm.user_id=? AND cv.vote_type='up'
    """, (user_id,))
    aura = c.fetchone()[0]
    conn.close()
    return aura


def get_user_stats(user_id: int) -> dict:
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM questions WHERE user_id=? AND status='approved'", (user_id,))
    questions = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM comments WHERE user_id=?", (user_id,))
    comments = c.fetchone()[0]
    conn.close()
    aura = get_user_aura(user_id)
    return {"questions": questions, "comments": comments, "aura": aura}


# ── Admin settings ────────────────────────────────────────────────────────────

def get_admin_setting(key: str, default: str = "") -> str:
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT value FROM admin_settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row["value"] if row else default


def set_admin_setting(key: str, value: str):
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO admin_settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


# ── Scheduled posts ───────────────────────────────────────────────────────────

def save_scheduled_post(text: str, photo_file_id, buttons_json: str, pin: bool, scheduled_at: str) -> int:
    conn = _conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO scheduled_posts (text, photo_file_id, buttons_json, pin, scheduled_at, published, created_at)
        VALUES (?,?,?,?,?,0,?)
    """, (text, photo_file_id, buttons_json, int(pin), scheduled_at, datetime.now().isoformat()))
    pid = c.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_pending_scheduled_posts():
    conn = _conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        SELECT * FROM scheduled_posts
        WHERE published=0 AND scheduled_at <= ?
        ORDER BY scheduled_at ASC
    """, (now,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_scheduled_post_published(post_id: int):
    conn = _conn()
    c = conn.cursor()
    c.execute("UPDATE scheduled_posts SET published=1 WHERE id=?", (post_id,))
    conn.commit()
    conn.close()


# ── Daily limit / spam / duplicate ────────────────────────────────────────────

def get_user_question_count_today(user_id: int) -> int:
    """Count questions submitted by this user today (UTC date)."""
    from datetime import date
    today = date.today().isoformat()
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "SELECT COUNT(*) FROM questions WHERE user_id=? AND created_at>=?",
        (user_id, today),
    )
    count = c.fetchone()[0]
    conn.close()
    return count


def has_submitted_exact(user_id: int, text: str) -> bool:
    """True if this user already submitted the exact same question text."""
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM questions WHERE user_id=? AND LOWER(question)=LOWER(?) LIMIT 1",
        (user_id, text),
    )
    found = c.fetchone() is not None
    conn.close()
    return found


def find_duplicate_question(text: str):
    """Return an existing approved question that is very similar, or None."""
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT id, question, post_number FROM questions WHERE status='approved'")
    rows = c.fetchall()
    conn.close()

    words_new = {w.lower() for w in text.split() if len(w) > 3}
    if not words_new:
        return None

    best_score, best_row = 0.0, None
    for row in rows:
        words_ex = {w.lower() for w in row["question"].split() if len(w) > 3}
        if not words_ex:
            continue
        common = words_new & words_ex
        score  = len(common) / len(words_new)
        if len(common) >= 3 and score > best_score:
            best_score, best_row = score, row

    return dict(best_row) if best_score >= 0.5 else None


# ── User question history ──────────────────────────────────────────────────────

def get_user_questions(user_id: int) -> list:
    """Return all questions submitted by the user (newest first)."""
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "SELECT id, question, status, post_number, created_at FROM questions "
        "WHERE user_id=? ORDER BY created_at DESC",
        (user_id,),
    )
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Search ────────────────────────────────────────────────────────────────────

def search_questions(keyword: str) -> list:
    """Full-text search across approved questions (up to 10 results)."""
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "SELECT id, question, post_number, tag FROM questions "
        "WHERE status='approved' AND LOWER(question) LIKE LOWER(?) ORDER BY id DESC LIMIT 10",
        (f"%{keyword}%",),
    )
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Broadcast helpers ─────────────────────────────────────────────────────────

def get_all_user_ids() -> list:
    """Return all user IDs who have ever started the bot."""
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM user_profiles ORDER BY created_at ASC")
    rows = c.fetchall()
    conn.close()
    return [row["user_id"] for row in rows]


# ── Weekly digest ─────────────────────────────────────────────────────────────

def get_top_questions_week(limit: int = 5) -> list:
    """Top questions approved in the last 7 days, ranked by comment count."""
    from datetime import datetime, timedelta
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    conn = _conn()
    c = conn.cursor()
    c.execute("""
        SELECT q.id, q.question, q.post_number, q.tag,
               (SELECT COUNT(*) FROM comments WHERE question_id=q.id) AS comment_count
        FROM questions q
        WHERE q.status='approved' AND q.answered_at >= ?
        ORDER BY comment_count DESC
        LIMIT ?
    """, (week_ago, limit))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Legacy compat ─────────────────────────────────────────────────────────────

def get_comments(question_id: int) -> list:
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "SELECT full_name, username, comment, created_at FROM comments WHERE question_id=? ORDER BY created_at ASC",
        (question_id,),
    )
    rows = c.fetchall()
    conn.close()
    return [tuple(r) for r in rows]
