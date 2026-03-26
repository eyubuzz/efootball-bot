"""
database.py — Supabase REST API via httpx (PostgREST).
Uses SUPABASE_URL and SUPABASE_KEY environment variables.
Run supabase_schema.sql once in the Supabase SQL Editor to create the tables.
"""
from __future__ import annotations

import os
import httpx
from datetime import datetime, timedelta, date

_client: httpx.Client | None = None


import logging as _logging
_log = _logging.getLogger(__name__)


def _http() -> httpx.Client:
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        key = os.getenv("SUPABASE_KEY", "").strip()
        if not url:
            raise RuntimeError("SUPABASE_URL env var is not set")
        if not key:
            raise RuntimeError("SUPABASE_KEY env var is not set")
        base = f"{url}/rest/v1/"
        _log.info("Supabase client init — base_url=%s key_len=%d", base, len(key))
        _client = httpx.Client(
            base_url=base,
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )
    return _client


def _get(table: str, params: dict = None, *, count: bool = False, extra_headers: dict = None):
    h = dict(extra_headers or {})
    if count:
        h["Prefer"] = "count=exact"
    try:
        resp = _http().get(table, params=params or {}, headers=h)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        _log.error("GET %s status %s: %s", table, e.response.status_code, e.response.text[:300])
        raise
    except Exception as e:
        _log.error("GET %s error: %s", table, e)
        raise
    if count:
        cr = resp.headers.get("content-range", "*/0")
        total = int(cr.split("/")[-1]) if "/" in cr else 0
        return resp.json(), total
    return resp.json()


def _post(table: str, data, *, prefer: str = "return=representation"):
    try:
        resp = _http().post(table, json=data, headers={"Prefer": prefer})
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        _log.error("POST %s status %s: %s", table, e.response.status_code, e.response.text[:300])
        raise
    except Exception as e:
        _log.error("POST %s error: %s", table, e)
        raise
    rows = resp.json()
    if isinstance(data, list):
        return rows
    return rows[0] if rows else {}


def _patch(table: str, filters: dict, data: dict):
    try:
        resp = _http().patch(table, params=filters, json=data)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        _log.error("PATCH %s status %s: %s", table, e.response.status_code, e.response.text[:300])
        raise
    except Exception as e:
        _log.error("PATCH %s error: %s", table, e)
        raise


def _delete(table: str, filters: dict):
    try:
        resp = _http().delete(table, params=filters)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        _log.error("DELETE %s status %s: %s", table, e.response.status_code, e.response.text[:300])
        raise
    except Exception as e:
        _log.error("DELETE %s error: %s", table, e)
        raise


def _upsert(table: str, data: dict, on_conflict: str) -> dict:
    try:
        resp = _http().post(
            table,
            params={"on_conflict": on_conflict},
            json=data,
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        _log.error("UPSERT %s status %s: %s", table, e.response.status_code, e.response.text[:300])
        raise
    except Exception as e:
        _log.error("UPSERT %s error: %s", table, e)
        raise
    rows = resp.json()
    return rows[0] if rows else {}


# ── Init ──────────────────────────────────────────────────────────────────────

def init_db():
    """Verify connection on startup — logs result to Railway logs."""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    _log.info("init_db: SUPABASE_URL=%s SUPABASE_KEY=%s",
              (url[:20] + "...") if url else "(NOT SET)",
              ("set, len=" + str(len(key))) if key else "(NOT SET)")
    try:
        _get("questions", {"limit": "1"})
        _log.info("init_db: Supabase connection OK")
    except Exception as e:
        _log.error("init_db: Supabase connection FAILED — %s", e)
        _log.error("init_db: Make sure SUPABASE_URL and SUPABASE_KEY are set in Railway Variables")


# ── Questions ─────────────────────────────────────────────────────────────────

def save_question(user_id: int, username: str, full_name: str, question: str,
                  photo_file_id: str = None, voice_file_id: str = None) -> int:
    row = _post("questions", {
        "user_id": user_id,
        "username": username,
        "full_name": full_name,
        "question": question,
        "photo_file_id": photo_file_id,
        "voice_file_id": voice_file_id,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
    })
    return row["id"]


def get_question(question_id: int):
    rows = _get("questions", {"id": f"eq.{question_id}"})
    return rows[0] if rows else None


def next_post_number() -> int:
    rows = _get("questions", {
        "select": "post_number",
        "status": "eq.approved",
        "order": "post_number.desc",
        "limit": "1",
    })
    if rows and rows[0].get("post_number"):
        return rows[0]["post_number"] + 1
    return 1


def assign_post_number(question_id: int, number: int):
    _patch("questions", {"id": f"eq.{question_id}"}, {"post_number": number})


def reset_questions():
    _delete("comment_votes", {"id": "gte.1"})
    _delete("comments", {"id": "gte.1"})
    _delete("questions", {"id": "gte.1"})


def update_status(question_id: int, status: str, tag: str = ""):
    _patch("questions", {"id": f"eq.{question_id}"}, {
        "status": status,
        "tag": tag,
        "answered_at": datetime.now().isoformat(),
    })


def set_channel_msg_id(question_id: int, msg_id: int):
    _patch("questions", {"id": f"eq.{question_id}"}, {"channel_msg_id": msg_id})


def get_all_questions_export() -> list:
    rows = _get("questions", {
        "select": "id,post_number,full_name,username,question,status,tag,created_at",
        "order": "id.asc",
    })
    for r in rows:
        _, total = _get("comments", {"question_id": f"eq.{r['id']}"}, count=True)
        r["comment_count"] = total
    return rows


def get_stats() -> dict:
    rows = _get("questions", {"select": "status"})
    stats: dict = {}
    for r in rows:
        s = r["status"]
        stats[s] = stats.get(s, 0) + 1
    return stats


# ── Comments ──────────────────────────────────────────────────────────────────

def save_comment(question_id: int, user_id: int, username: str, full_name: str,
                 comment: str = "", photo_file_id: str = None, voice_file_id: str = None) -> int:
    row = _post("comments", {
        "question_id": question_id,
        "user_id": user_id,
        "username": username,
        "full_name": full_name,
        "comment": comment,
        "photo_file_id": photo_file_id,
        "voice_file_id": voice_file_id,
        "created_at": datetime.now().isoformat(),
    })
    return row["id"]


def get_comment_count(question_id: int) -> int:
    _, total = _get("comments", {"question_id": f"eq.{question_id}"}, count=True)
    return total


def get_comments_page(question_id: int, page: int = 1, per_page: int = 3):
    """Return (list_of_dicts, total_count)."""
    _, total = _get("comments", {"question_id": f"eq.{question_id}"}, count=True)
    offset = (page - 1) * per_page
    comments = _get("comments", {
        "question_id": f"eq.{question_id}",
        "order": "created_at.asc",
        "limit": str(per_page),
        "offset": str(offset),
    })
    for cm in comments:
        _, likes = _get("comment_votes",
                        {"comment_id": f"eq.{cm['id']}", "vote_type": "eq.up"}, count=True)
        _, dislikes = _get("comment_votes",
                           {"comment_id": f"eq.{cm['id']}", "vote_type": "eq.down"}, count=True)
        cm["likes"] = likes
        cm["dislikes"] = dislikes
    return comments, total


# ── Votes ─────────────────────────────────────────────────────────────────────

def vote_comment(comment_id: int, user_id: int, vote_type: str):
    """Toggle vote. Returns (likes, dislikes)."""
    existing = _get("comment_votes", {
        "comment_id": f"eq.{comment_id}",
        "user_id": f"eq.{user_id}",
    })
    if existing:
        if existing[0]["vote_type"] == vote_type:
            _delete("comment_votes", {
                "comment_id": f"eq.{comment_id}",
                "user_id": f"eq.{user_id}",
            })
        else:
            _patch("comment_votes",
                   {"comment_id": f"eq.{comment_id}", "user_id": f"eq.{user_id}"},
                   {"vote_type": vote_type, "created_at": datetime.now().isoformat()})
    else:
        _post("comment_votes", {
            "comment_id": comment_id,
            "user_id": user_id,
            "vote_type": vote_type,
            "created_at": datetime.now().isoformat(),
        })
    _, likes = _get("comment_votes",
                    {"comment_id": f"eq.{comment_id}", "vote_type": "eq.up"}, count=True)
    _, dislikes = _get("comment_votes",
                       {"comment_id": f"eq.{comment_id}", "vote_type": "eq.down"}, count=True)
    return likes, dislikes


# ── User profiles ─────────────────────────────────────────────────────────────

def ensure_user_profile(user_id: int, full_name: str, username: str):
    _upsert("user_profiles", {
        "user_id": user_id,
        "full_name": full_name,
        "username": username,
        "created_at": datetime.now().isoformat(),
    }, on_conflict="user_id")


def get_user_profile(user_id: int):
    rows = _get("user_profiles", {"user_id": f"eq.{user_id}"})
    return rows[0] if rows else None


def set_user_visibility(user_id: int, visible: bool):
    _patch("user_profiles", {"user_id": f"eq.{user_id}"}, {"visible": int(visible)})


def get_discoverable_users(exclude_id: int, page: int = 1, per_page: int = 5):
    filters = {"visible": "eq.1", "user_id": f"neq.{exclude_id}"}
    _, total = _get("user_profiles", filters, count=True)
    offset = (page - 1) * per_page
    rows = _get("user_profiles", {
        **filters,
        "select": "user_id,full_name,username",
        "order": "created_at.asc",
        "limit": str(per_page),
        "offset": str(offset),
    })
    return rows, total


# ── Follows ───────────────────────────────────────────────────────────────────

def follow_user(follower_id: int, following_id: int):
    try:
        _post("follows", {
            "follower_id": follower_id,
            "following_id": following_id,
            "created_at": datetime.now().isoformat(),
        })
    except Exception:
        pass  # unique constraint


def unfollow_user(follower_id: int, following_id: int):
    _delete("follows", {
        "follower_id": f"eq.{follower_id}",
        "following_id": f"eq.{following_id}",
    })


def is_following(follower_id: int, following_id: int) -> bool:
    rows = _get("follows", {
        "follower_id": f"eq.{follower_id}",
        "following_id": f"eq.{following_id}",
    })
    return len(rows) > 0


def get_follower_count(user_id: int) -> int:
    _, total = _get("follows", {"following_id": f"eq.{user_id}"}, count=True)
    return total


def get_following_count(user_id: int) -> int:
    _, total = _get("follows", {"follower_id": f"eq.{user_id}"}, count=True)
    return total


def get_followers_list(user_id: int):
    follows = _get("follows", {
        "select": "follower_id",
        "following_id": f"eq.{user_id}",
        "order": "created_at.desc",
    })
    result = []
    for f in follows:
        rows = _get("user_profiles", {
            "select": "user_id,full_name,username",
            "user_id": f"eq.{f['follower_id']}",
        })
        if rows:
            result.append(rows[0])
    return result


def get_following_list(user_id: int):
    follows = _get("follows", {
        "select": "following_id",
        "follower_id": f"eq.{user_id}",
        "order": "created_at.desc",
    })
    result = []
    for f in follows:
        rows = _get("user_profiles", {
            "select": "user_id,full_name,username",
            "user_id": f"eq.{f['following_id']}",
        })
        if rows:
            result.append(rows[0])
    return result


# ── User stats ────────────────────────────────────────────────────────────────

def get_user_aura(user_id: int) -> int:
    comments = _get("comments", {"select": "id", "user_id": f"eq.{user_id}"})
    if not comments:
        return 0
    ids = ",".join(str(c["id"]) for c in comments)
    _, total = _get("comment_votes", {
        "comment_id": f"in.({ids})",
        "vote_type": "eq.up",
    }, count=True)
    return total


def get_user_stats(user_id: int) -> dict:
    _, questions = _get("questions", {
        "user_id": f"eq.{user_id}",
        "status": "eq.approved",
    }, count=True)
    _, comments = _get("comments", {"user_id": f"eq.{user_id}"}, count=True)
    return {"questions": questions, "comments": comments, "aura": get_user_aura(user_id)}


# ── Admin settings ────────────────────────────────────────────────────────────

def get_admin_setting(key: str, default: str = "") -> str:
    rows = _get("admin_settings", {"key": f"eq.{key}"})
    return rows[0]["value"] if rows else default


def set_admin_setting(key: str, value: str):
    _upsert("admin_settings", {"key": key, "value": value}, on_conflict="key")


# ── Scheduled posts ───────────────────────────────────────────────────────────

def save_scheduled_post(text: str, photo_file_id, buttons_json: str, pin: bool, scheduled_at: str) -> int:
    row = _post("scheduled_posts", {
        "text": text,
        "photo_file_id": photo_file_id,
        "buttons_json": buttons_json,
        "pin": int(pin),
        "scheduled_at": scheduled_at,
        "published": 0,
        "created_at": datetime.now().isoformat(),
    })
    return row["id"]


def get_pending_scheduled_posts():
    now = datetime.now().isoformat()
    return _get("scheduled_posts", {
        "published": "eq.0",
        "scheduled_at": f"lte.{now}",
        "order": "scheduled_at.asc",
    })


def mark_scheduled_post_published(post_id: int):
    _patch("scheduled_posts", {"id": f"eq.{post_id}"}, {"published": 1})


# ── Daily limit / spam / duplicate ────────────────────────────────────────────

def get_user_question_count_today(user_id: int) -> int:
    today = date.today().isoformat()
    _, total = _get("questions", {
        "user_id": f"eq.{user_id}",
        "created_at": f"gte.{today}",
    }, count=True)
    return total


def has_submitted_exact(user_id: int, text: str) -> bool:
    rows = _get("questions", {
        "select": "question",
        "user_id": f"eq.{user_id}",
    })
    lower_text = text.lower()
    return any((r.get("question") or "").lower() == lower_text for r in rows)


def find_duplicate_question(text: str):
    """Return an existing approved question that is very similar, or None."""
    rows = _get("questions", {
        "select": "id,question,post_number",
        "status": "eq.approved",
    })
    words_new = {w.lower() for w in text.split() if len(w) > 3}
    if not words_new:
        return None
    best_score, best_row = 0.0, None
    for row in rows:
        words_ex = {w.lower() for w in (row.get("question") or "").split() if len(w) > 3}
        if not words_ex:
            continue
        common = words_new & words_ex
        score = len(common) / len(words_new)
        if len(common) >= 3 and score > best_score:
            best_score, best_row = score, row
    return best_row if best_score >= 0.5 else None


# ── User question history ─────────────────────────────────────────────────────

def get_user_questions(user_id: int) -> list:
    return _get("questions", {
        "select": "id,question,status,post_number,created_at",
        "user_id": f"eq.{user_id}",
        "order": "created_at.desc",
    })


# ── Search ────────────────────────────────────────────────────────────────────

def search_questions(keyword: str) -> list:
    return _get("questions", {
        "select": "id,question,post_number,tag",
        "status": "eq.approved",
        "question": f"ilike.%{keyword}%",
        "order": "id.desc",
        "limit": "10",
    })


# ── Broadcast ─────────────────────────────────────────────────────────────────

def get_all_user_ids() -> list:
    rows = _get("user_profiles", {
        "select": "user_id",
        "order": "created_at.asc",
    })
    return [r["user_id"] for r in rows]


# ── Weekly digest ─────────────────────────────────────────────────────────────

def get_top_questions_week(limit: int = 5) -> list:
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    rows = _get("questions", {
        "select": "id,question,post_number,tag",
        "status": "eq.approved",
        "answered_at": f"gte.{week_ago}",
    })
    for r in rows:
        _, count = _get("comments", {"question_id": f"eq.{r['id']}"}, count=True)
        r["comment_count"] = count
    rows.sort(key=lambda x: x["comment_count"], reverse=True)
    return rows[:limit]


# ── Legacy compat ─────────────────────────────────────────────────────────────

def get_comments(question_id: int) -> list:
    rows = _get("comments", {
        "select": "full_name,username,comment,created_at",
        "question_id": f"eq.{question_id}",
        "order": "created_at.asc",
    })
    return [(r["full_name"], r["username"], r["comment"], r["created_at"]) for r in rows]
