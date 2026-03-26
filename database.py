"""
database.py — PostgreSQL via psycopg2 (Supabase).

Add ONE env var in Railway:
  DATABASE_URL = postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
  (Supabase Dashboard → Project Settings → Database → Connection string → URI)

Run supabase_schema.sql once in the Supabase SQL Editor to create the tables.
"""
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, date

import psycopg2
import psycopg2.extras

DATABASE_URL = os.getenv("DATABASE_URL", "")


@contextmanager
def _cur():
    """Yield a RealDictCursor, commit on success, rollback on error, always close."""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Verify connection on startup."""
    try:
        with _cur() as cur:
            cur.execute("SELECT 1")
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("PostgreSQL connection failed: %s", e)


# ── Questions ──────────────────────────────────────────────────────────────────

def save_question(user_id: int, username: str, full_name: str, question: str,
                  photo_file_id: str = None, voice_file_id: str = None) -> int:
    with _cur() as cur:
        cur.execute("""
            INSERT INTO questions
                (user_id, username, full_name, question, photo_file_id, voice_file_id, status, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,'pending',%s)
            RETURNING id
        """, (user_id, username, full_name, question,
              photo_file_id, voice_file_id, datetime.now().isoformat()))
        return cur.fetchone()["id"]


def get_question(question_id: int):
    with _cur() as cur:
        cur.execute("SELECT * FROM questions WHERE id=%s", (question_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def next_post_number() -> int:
    with _cur() as cur:
        cur.execute("SELECT COALESCE(MAX(post_number),0) AS n FROM questions WHERE status='approved'")
        return cur.fetchone()["n"] + 1


def assign_post_number(question_id: int, number: int):
    with _cur() as cur:
        cur.execute("UPDATE questions SET post_number=%s WHERE id=%s", (number, question_id))


def reset_questions():
    with _cur() as cur:
        cur.execute("DELETE FROM comment_votes")
        cur.execute("DELETE FROM comments")
        cur.execute("DELETE FROM questions")


def update_status(question_id: int, status: str, tag: str = ""):
    with _cur() as cur:
        cur.execute(
            "UPDATE questions SET status=%s, tag=%s, answered_at=%s WHERE id=%s",
            (status, tag, datetime.now().isoformat(), question_id))


def set_channel_msg_id(question_id: int, msg_id: int):
    with _cur() as cur:
        cur.execute("UPDATE questions SET channel_msg_id=%s WHERE id=%s", (msg_id, question_id))


def get_all_questions_export() -> list:
    with _cur() as cur:
        cur.execute("""
            SELECT q.id, q.post_number, q.full_name, q.username, q.question,
                   q.status, q.tag, q.created_at,
                   (SELECT COUNT(*) FROM comments WHERE question_id=q.id) AS comment_count
            FROM questions q ORDER BY q.id ASC
        """)
        return [dict(r) for r in cur.fetchall()]


def get_stats() -> dict:
    with _cur() as cur:
        cur.execute("SELECT status, COUNT(*) AS n FROM questions GROUP BY status")
        return {r["status"]: r["n"] for r in cur.fetchall()}


# ── Comments ──────────────────────────────────────────────────────────────────

def save_comment(question_id: int, user_id: int, username: str, full_name: str,
                 comment: str = "", photo_file_id: str = None, voice_file_id: str = None) -> int:
    with _cur() as cur:
        cur.execute("""
            INSERT INTO comments
                (question_id, user_id, username, full_name, comment,
                 photo_file_id, voice_file_id, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (question_id, user_id, username, full_name, comment,
              photo_file_id, voice_file_id, datetime.now().isoformat()))
        return cur.fetchone()["id"]


def get_comment_count(question_id: int) -> int:
    with _cur() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM comments WHERE question_id=%s", (question_id,))
        return cur.fetchone()["n"]


def get_comments_page(question_id: int, page: int = 1, per_page: int = 3):
    """Return (list_of_dicts, total_count)."""
    with _cur() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM comments WHERE question_id=%s", (question_id,))
        total  = cur.fetchone()["n"]
        offset = (page - 1) * per_page
        cur.execute("""
            SELECT cm.id, cm.user_id, cm.username, cm.full_name, cm.comment,
                   cm.photo_file_id, cm.voice_file_id, cm.created_at,
                   (SELECT COUNT(*) FROM comment_votes WHERE comment_id=cm.id AND vote_type='up')   AS likes,
                   (SELECT COUNT(*) FROM comment_votes WHERE comment_id=cm.id AND vote_type='down') AS dislikes
            FROM comments cm
            WHERE cm.question_id=%s
            ORDER BY cm.created_at ASC
            LIMIT %s OFFSET %s
        """, (question_id, per_page, offset))
        return [dict(r) for r in cur.fetchall()], total


# ── Votes ─────────────────────────────────────────────────────────────────────

def vote_comment(comment_id: int, user_id: int, vote_type: str):
    """Toggle vote. Returns (likes, dislikes)."""
    with _cur() as cur:
        cur.execute(
            "SELECT vote_type FROM comment_votes WHERE comment_id=%s AND user_id=%s",
            (comment_id, user_id))
        existing = cur.fetchone()
        if existing:
            if existing["vote_type"] == vote_type:
                cur.execute(
                    "DELETE FROM comment_votes WHERE comment_id=%s AND user_id=%s",
                    (comment_id, user_id))
            else:
                cur.execute(
                    "UPDATE comment_votes SET vote_type=%s, created_at=%s WHERE comment_id=%s AND user_id=%s",
                    (vote_type, datetime.now().isoformat(), comment_id, user_id))
        else:
            cur.execute(
                "INSERT INTO comment_votes (comment_id, user_id, vote_type, created_at) VALUES (%s,%s,%s,%s)",
                (comment_id, user_id, vote_type, datetime.now().isoformat()))
        cur.execute(
            "SELECT COUNT(*) AS n FROM comment_votes WHERE comment_id=%s AND vote_type='up'", (comment_id,))
        likes = cur.fetchone()["n"]
        cur.execute(
            "SELECT COUNT(*) AS n FROM comment_votes WHERE comment_id=%s AND vote_type='down'", (comment_id,))
        dislikes = cur.fetchone()["n"]
        return likes, dislikes


# ── User profiles ─────────────────────────────────────────────────────────────

def ensure_user_profile(user_id: int, full_name: str, username: str):
    with _cur() as cur:
        cur.execute("""
            INSERT INTO user_profiles (user_id, full_name, username, created_at)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (user_id) DO UPDATE SET full_name=EXCLUDED.full_name, username=EXCLUDED.username
        """, (user_id, full_name, username, datetime.now().isoformat()))


def get_user_profile(user_id: int):
    with _cur() as cur:
        cur.execute("SELECT * FROM user_profiles WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def set_user_visibility(user_id: int, visible: bool):
    with _cur() as cur:
        cur.execute("UPDATE user_profiles SET visible=%s WHERE user_id=%s", (int(visible), user_id))


def get_discoverable_users(exclude_id: int, page: int = 1, per_page: int = 5):
    with _cur() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM user_profiles WHERE visible=1 AND user_id!=%s", (exclude_id,))
        total  = cur.fetchone()["n"]
        offset = (page - 1) * per_page
        cur.execute("""
            SELECT user_id, full_name, username FROM user_profiles
            WHERE visible=1 AND user_id!=%s ORDER BY created_at ASC LIMIT %s OFFSET %s
        """, (exclude_id, per_page, offset))
        return [dict(r) for r in cur.fetchall()], total


# ── Follows ───────────────────────────────────────────────────────────────────

def follow_user(follower_id: int, following_id: int):
    try:
        with _cur() as cur:
            cur.execute(
                "INSERT INTO follows (follower_id, following_id, created_at) VALUES (%s,%s,%s)",
                (follower_id, following_id, datetime.now().isoformat()))
    except Exception:
        pass  # unique constraint


def unfollow_user(follower_id: int, following_id: int):
    with _cur() as cur:
        cur.execute(
            "DELETE FROM follows WHERE follower_id=%s AND following_id=%s",
            (follower_id, following_id))


def is_following(follower_id: int, following_id: int) -> bool:
    with _cur() as cur:
        cur.execute(
            "SELECT 1 FROM follows WHERE follower_id=%s AND following_id=%s",
            (follower_id, following_id))
        return cur.fetchone() is not None


def get_follower_count(user_id: int) -> int:
    with _cur() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM follows WHERE following_id=%s", (user_id,))
        return cur.fetchone()["n"]


def get_following_count(user_id: int) -> int:
    with _cur() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM follows WHERE follower_id=%s", (user_id,))
        return cur.fetchone()["n"]


def get_followers_list(user_id: int):
    with _cur() as cur:
        cur.execute("""
            SELECT up.user_id, up.full_name, up.username
            FROM follows f JOIN user_profiles up ON up.user_id=f.follower_id
            WHERE f.following_id=%s ORDER BY f.created_at DESC
        """, (user_id,))
        return [dict(r) for r in cur.fetchall()]


def get_following_list(user_id: int):
    with _cur() as cur:
        cur.execute("""
            SELECT up.user_id, up.full_name, up.username
            FROM follows f JOIN user_profiles up ON up.user_id=f.following_id
            WHERE f.follower_id=%s ORDER BY f.created_at DESC
        """, (user_id,))
        return [dict(r) for r in cur.fetchall()]


# ── User stats ────────────────────────────────────────────────────────────────

def get_user_aura(user_id: int) -> int:
    with _cur() as cur:
        cur.execute("""
            SELECT COUNT(*) AS n FROM comment_votes cv
            JOIN comments cm ON cv.comment_id=cm.id
            WHERE cm.user_id=%s AND cv.vote_type='up'
        """, (user_id,))
        return cur.fetchone()["n"]


def get_user_stats(user_id: int) -> dict:
    with _cur() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM questions WHERE user_id=%s AND status='approved'", (user_id,))
        questions = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM comments WHERE user_id=%s", (user_id,))
        comments = cur.fetchone()["n"]
    return {"questions": questions, "comments": comments, "aura": get_user_aura(user_id)}


# ── Admin settings ────────────────────────────────────────────────────────────

def get_admin_setting(key: str, default: str = "") -> str:
    with _cur() as cur:
        cur.execute("SELECT value FROM admin_settings WHERE key=%s", (key,))
        row = cur.fetchone()
        return row["value"] if row else default


def set_admin_setting(key: str, value: str):
    with _cur() as cur:
        cur.execute("""
            INSERT INTO admin_settings (key, value) VALUES (%s,%s)
            ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value
        """, (key, value))


# ── Scheduled posts ───────────────────────────────────────────────────────────

def save_scheduled_post(text: str, photo_file_id, buttons_json: str, pin: bool, scheduled_at: str) -> int:
    with _cur() as cur:
        cur.execute("""
            INSERT INTO scheduled_posts
                (text, photo_file_id, buttons_json, pin, scheduled_at, published, created_at)
            VALUES (%s,%s,%s,%s,%s,0,%s) RETURNING id
        """, (text, photo_file_id, buttons_json, int(pin), scheduled_at, datetime.now().isoformat()))
        return cur.fetchone()["id"]


def get_pending_scheduled_posts():
    with _cur() as cur:
        now = datetime.now().isoformat()
        cur.execute("""
            SELECT * FROM scheduled_posts
            WHERE published=0 AND scheduled_at<=%s ORDER BY scheduled_at ASC
        """, (now,))
        return [dict(r) for r in cur.fetchall()]


def mark_scheduled_post_published(post_id: int):
    with _cur() as cur:
        cur.execute("UPDATE scheduled_posts SET published=1 WHERE id=%s", (post_id,))


# ── Daily limit / spam / duplicate ────────────────────────────────────────────

def get_user_question_count_today(user_id: int) -> int:
    today = date.today().isoformat()
    with _cur() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM questions WHERE user_id=%s AND created_at>=%s",
            (user_id, today))
        return cur.fetchone()["n"]


def has_submitted_exact(user_id: int, text: str) -> bool:
    with _cur() as cur:
        cur.execute(
            "SELECT 1 FROM questions WHERE user_id=%s AND LOWER(question)=LOWER(%s) LIMIT 1",
            (user_id, text))
        return cur.fetchone() is not None


def find_duplicate_question(text: str):
    """Return an existing approved question that is very similar, or None."""
    with _cur() as cur:
        cur.execute("SELECT id, question, post_number FROM questions WHERE status='approved'")
        rows = cur.fetchall()

    words_new = {w.lower() for w in text.split() if len(w) > 3}
    if not words_new:
        return None
    best_score, best_row = 0.0, None
    for row in rows:
        words_ex = {w.lower() for w in (row["question"] or "").split() if len(w) > 3}
        if not words_ex:
            continue
        common = words_new & words_ex
        score  = len(common) / len(words_new)
        if len(common) >= 3 and score > best_score:
            best_score, best_row = score, row
    return dict(best_row) if best_score >= 0.5 else None


# ── User question history ──────────────────────────────────────────────────────

def get_user_questions(user_id: int) -> list:
    with _cur() as cur:
        cur.execute("""
            SELECT id, question, status, post_number, created_at
            FROM questions WHERE user_id=%s ORDER BY created_at DESC
        """, (user_id,))
        return [dict(r) for r in cur.fetchall()]


# ── Search ────────────────────────────────────────────────────────────────────

def search_questions(keyword: str) -> list:
    with _cur() as cur:
        cur.execute("""
            SELECT id, question, post_number, tag FROM questions
            WHERE status='approved' AND LOWER(question) LIKE LOWER(%s)
            ORDER BY id DESC LIMIT 10
        """, (f"%{keyword}%",))
        return [dict(r) for r in cur.fetchall()]


# ── Broadcast ─────────────────────────────────────────────────────────────────

def get_all_user_ids() -> list:
    with _cur() as cur:
        cur.execute("SELECT user_id FROM user_profiles ORDER BY created_at ASC")
        return [r["user_id"] for r in cur.fetchall()]


# ── Weekly digest ─────────────────────────────────────────────────────────────

def get_top_questions_week(limit: int = 5) -> list:
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    with _cur() as cur:
        cur.execute("""
            SELECT q.id, q.question, q.post_number, q.tag,
                   (SELECT COUNT(*) FROM comments WHERE question_id=q.id) AS comment_count
            FROM questions q
            WHERE q.status='approved' AND q.answered_at>=%s
            ORDER BY comment_count DESC LIMIT %s
        """, (week_ago, limit))
        return [dict(r) for r in cur.fetchall()]


# ── Legacy compat ─────────────────────────────────────────────────────────────

def get_comments(question_id: int) -> list:
    with _cur() as cur:
        cur.execute("""
            SELECT full_name, username, comment, created_at
            FROM comments WHERE question_id=%s ORDER BY created_at ASC
        """, (question_id,))
        return [tuple(r.values()) for r in cur.fetchall()]
