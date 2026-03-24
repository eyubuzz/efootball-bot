import sqlite3
from datetime import datetime

DB_FILE = "questions.db"


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

    # Migrations for existing databases
    for migration in [
        "ALTER TABLE questions ADD COLUMN channel_msg_id INTEGER",
        "ALTER TABLE questions ADD COLUMN photo_file_id  TEXT",
    ]:
        try:
            c.execute(migration)
        except sqlite3.OperationalError:
            pass  # column already exists

    conn.commit()
    conn.close()


# ── Questions ─────────────────────────────────────────────────────────────────

def save_question(user_id: int, username: str, full_name: str, question: str, photo_file_id: str = None) -> int:
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO questions (user_id, username, full_name, question, photo_file_id, status, created_at) VALUES (?,?,?,?,?,'pending',?)",
        (user_id, username, full_name, question, photo_file_id, datetime.now().isoformat()),
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


def get_stats() -> dict:
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT status, COUNT(*) FROM questions GROUP BY status")
    rows = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}


# ── Comments ──────────────────────────────────────────────────────────────────

def save_comment(question_id: int, user_id: int, username: str, full_name: str, comment: str) -> int:
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO comments (question_id, user_id, username, full_name, comment, created_at) VALUES (?,?,?,?,?,?)",
        (question_id, user_id, username, full_name, comment, datetime.now().isoformat()),
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
            cm.id, cm.user_id, cm.username, cm.full_name, cm.comment, cm.created_at,
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


# ── User ──────────────────────────────────────────────────────────────────────

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


# ── Legacy compat (used by old comment command) ───────────────────────────────

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
