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
            created_at  TEXT,
            answered_at TEXT
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


def update_status(question_id: int, status: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "UPDATE questions SET status = ?, answered_at = ? WHERE id = ?",
        (status, datetime.now().isoformat(), question_id),
    )
    conn.commit()
    conn.close()


def get_stats() -> dict:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT status, COUNT(*) FROM questions GROUP BY status")
    rows = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}
