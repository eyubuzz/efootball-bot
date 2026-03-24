import sqlite3
from datetime import datetime

DB_FILE = "questions.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            username    TEXT,
            full_name   TEXT,
            question    TEXT NOT NULL,
            status      TEXT DEFAULT 'pending',
            tag         TEXT DEFAULT '',
            created_at  TEXT,
            answered_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            username    TEXT,
            full_name   TEXT,
            comment     TEXT NOT NULL,
            created_at  TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_question(user_id: int, username: str, full_name: str, question: str) -> int:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """INSERT INTO questions (user_id, username, full_name, question, status, created_at)
           VALUES (?, ?, ?, ?, 'pending', ?)""",
        (user_id, username, full_name, question, datetime.now().isoformat()),
    )
    question_id = c.lastrowid
    conn.commit()
    conn.close()
    return question_id


def get_question(question_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
    row = c.fetchone()
    conn.close()
    return row


def update_status(question_id: int, status: str, tag: str = ""):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "UPDATE questions SET status = ?, tag = ?, answered_at = ? WHERE id = ?",
        (status, tag, datetime.now().isoformat(), question_id),
    )
    conn.commit()
    conn.close()


def save_comment(question_id: int, user_id: int, username: str, full_name: str, comment: str) -> int:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """INSERT INTO comments (question_id, user_id, username, full_name, comment, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (question_id, user_id, username, full_name, comment, datetime.now().isoformat()),
    )
    comment_id = c.lastrowid
    conn.commit()
    conn.close()
    return comment_id


def get_comments(question_id: int) -> list:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT full_name, username, comment, created_at FROM comments WHERE question_id = ? ORDER BY created_at ASC",
        (question_id,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def get_stats() -> dict:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT status, COUNT(*) FROM questions GROUP BY status")
    rows = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}
