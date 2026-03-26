"""
database.py — Supabase backend.

All data lives in your Supabase project.  Run supabase_schema.sql once in the
Supabase SQL editor to create the tables, then set SUPABASE_URL and
SUPABASE_KEY in Railway variables.
"""
import os
from datetime import datetime, timedelta, date

from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

_client: Client = None


def _db() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def init_db():
    """Verify Supabase is reachable on startup."""
    try:
        _db().table("questions").select("id").limit(1).execute()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Supabase connection failed: %s", e)


# ── Questions ──────────────────────────────────────────────────────────────────

def save_question(user_id: int, username: str, full_name: str, question: str,
                  photo_file_id: str = None, voice_file_id: str = None) -> int:
    res = _db().table("questions").insert({
        "user_id":       user_id,
        "username":      username,
        "full_name":     full_name,
        "question":      question,
        "photo_file_id": photo_file_id,
        "voice_file_id": voice_file_id,
        "status":        "pending",
        "created_at":    datetime.now().isoformat(),
    }).execute()
    return res.data[0]["id"]


def get_question(question_id: int):
    res = _db().table("questions").select("*").eq("id", question_id).execute()
    return res.data[0] if res.data else None


def next_post_number() -> int:
    res = _db().table("questions").select("post_number").eq("status", "approved").execute()
    nums = [r["post_number"] for r in res.data if r.get("post_number")]
    return (max(nums) if nums else 0) + 1


def assign_post_number(question_id: int, number: int):
    _db().table("questions").update({"post_number": number}).eq("id", question_id).execute()


def reset_questions():
    """Wipe all questions, comments, and votes. Post counter resets to 0."""
    _db().table("comment_votes").delete().neq("id", 0).execute()
    _db().table("comments").delete().neq("id", 0).execute()
    _db().table("questions").delete().neq("id", 0).execute()


def update_status(question_id: int, status: str, tag: str = ""):
    _db().table("questions").update({
        "status":      status,
        "tag":         tag,
        "answered_at": datetime.now().isoformat(),
    }).eq("id", question_id).execute()


def set_channel_msg_id(question_id: int, msg_id: int):
    _db().table("questions").update({"channel_msg_id": msg_id}).eq("id", question_id).execute()


def get_all_questions_export() -> list:
    q_res = _db().table("questions").select("*").order("id").execute()
    questions = q_res.data or []
    # Attach comment counts
    for q in questions:
        cnt = _db().table("comments").select("*", count="exact").eq("question_id", q["id"]).execute()
        q["comment_count"] = cnt.count or 0
    return questions


def get_stats() -> dict:
    res = _db().table("questions").select("status").execute()
    counts = {}
    for r in (res.data or []):
        s = r["status"]
        counts[s] = counts.get(s, 0) + 1
    return counts


# ── Comments ──────────────────────────────────────────────────────────────────

def save_comment(question_id: int, user_id: int, username: str, full_name: str,
                 comment: str = "", photo_file_id: str = None, voice_file_id: str = None) -> int:
    res = _db().table("comments").insert({
        "question_id":   question_id,
        "user_id":       user_id,
        "username":      username,
        "full_name":     full_name,
        "comment":       comment,
        "photo_file_id": photo_file_id,
        "voice_file_id": voice_file_id,
        "created_at":    datetime.now().isoformat(),
    }).execute()
    return res.data[0]["id"]


def get_comment_count(question_id: int) -> int:
    res = _db().table("comments").select("*", count="exact").eq("question_id", question_id).execute()
    return res.count or 0


def get_comments_page(question_id: int, page: int = 1, per_page: int = 3):
    """Return (list_of_dicts, total_count)."""
    total_res = _db().table("comments").select("*", count="exact").eq("question_id", question_id).execute()
    total     = total_res.count or 0
    offset    = (page - 1) * per_page

    rows_res = (
        _db().table("comments")
        .select("*")
        .eq("question_id", question_id)
        .order("created_at")
        .range(offset, offset + per_page - 1)
        .execute()
    )
    comments = rows_res.data or []

    if comments:
        # Batch-fetch all votes for these comments
        cids = [c["id"] for c in comments]
        votes_res = _db().table("comment_votes").select("comment_id, vote_type").in_("comment_id", cids).execute()
        vote_data = votes_res.data or []
        likes_map    = {}
        dislikes_map = {}
        for v in vote_data:
            cid = v["comment_id"]
            if v["vote_type"] == "up":
                likes_map[cid] = likes_map.get(cid, 0) + 1
            else:
                dislikes_map[cid] = dislikes_map.get(cid, 0) + 1
        for c in comments:
            c["likes"]    = likes_map.get(c["id"], 0)
            c["dislikes"] = dislikes_map.get(c["id"], 0)

    return comments, total


# ── Votes ─────────────────────────────────────────────────────────────────────

def vote_comment(comment_id: int, user_id: int, vote_type: str):
    """Toggle vote. Returns (likes, dislikes)."""
    existing_res = (
        _db().table("comment_votes")
        .select("vote_type")
        .eq("comment_id", comment_id)
        .eq("user_id", user_id)
        .execute()
    )
    existing = existing_res.data[0] if existing_res.data else None

    if existing:
        if existing["vote_type"] == vote_type:
            _db().table("comment_votes").delete().eq("comment_id", comment_id).eq("user_id", user_id).execute()
        else:
            _db().table("comment_votes").update({
                "vote_type":  vote_type,
                "created_at": datetime.now().isoformat(),
            }).eq("comment_id", comment_id).eq("user_id", user_id).execute()
    else:
        _db().table("comment_votes").insert({
            "comment_id":  comment_id,
            "user_id":     user_id,
            "vote_type":   vote_type,
            "created_at":  datetime.now().isoformat(),
        }).execute()

    all_votes = _db().table("comment_votes").select("vote_type").eq("comment_id", comment_id).execute()
    likes    = sum(1 for v in (all_votes.data or []) if v["vote_type"] == "up")
    dislikes = sum(1 for v in (all_votes.data or []) if v["vote_type"] == "down")
    return likes, dislikes


# ── User profiles ─────────────────────────────────────────────────────────────

def ensure_user_profile(user_id: int, full_name: str, username: str):
    _db().table("user_profiles").upsert({
        "user_id":    user_id,
        "full_name":  full_name,
        "username":   username,
        "created_at": datetime.now().isoformat(),
    }, on_conflict="user_id").execute()


def get_user_profile(user_id: int):
    res = _db().table("user_profiles").select("*").eq("user_id", user_id).execute()
    return res.data[0] if res.data else None


def set_user_visibility(user_id: int, visible: bool):
    _db().table("user_profiles").update({"visible": int(visible)}).eq("user_id", user_id).execute()


def get_discoverable_users(exclude_id: int, page: int = 1, per_page: int = 5):
    total_res = (
        _db().table("user_profiles")
        .select("*", count="exact")
        .eq("visible", 1)
        .neq("user_id", exclude_id)
        .execute()
    )
    total  = total_res.count or 0
    offset = (page - 1) * per_page
    rows   = (
        _db().table("user_profiles")
        .select("user_id, full_name, username")
        .eq("visible", 1)
        .neq("user_id", exclude_id)
        .order("created_at")
        .range(offset, offset + per_page - 1)
        .execute()
    )
    return rows.data or [], total


# ── Follows ───────────────────────────────────────────────────────────────────

def follow_user(follower_id: int, following_id: int):
    try:
        _db().table("follows").insert({
            "follower_id":  follower_id,
            "following_id": following_id,
            "created_at":   datetime.now().isoformat(),
        }).execute()
    except Exception:
        pass  # duplicate


def unfollow_user(follower_id: int, following_id: int):
    _db().table("follows").delete().eq("follower_id", follower_id).eq("following_id", following_id).execute()


def is_following(follower_id: int, following_id: int) -> bool:
    res = _db().table("follows").select("id").eq("follower_id", follower_id).eq("following_id", following_id).execute()
    return len(res.data) > 0


def get_follower_count(user_id: int) -> int:
    res = _db().table("follows").select("*", count="exact").eq("following_id", user_id).execute()
    return res.count or 0


def get_following_count(user_id: int) -> int:
    res = _db().table("follows").select("*", count="exact").eq("follower_id", user_id).execute()
    return res.count or 0


def get_followers_list(user_id: int):
    follows = _db().table("follows").select("follower_id").eq("following_id", user_id).order("created_at", desc=True).execute()
    ids = [f["follower_id"] for f in (follows.data or [])]
    if not ids:
        return []
    profiles = _db().table("user_profiles").select("user_id, full_name, username").in_("user_id", ids).execute()
    return profiles.data or []


def get_following_list(user_id: int):
    follows = _db().table("follows").select("following_id").eq("follower_id", user_id).order("created_at", desc=True).execute()
    ids = [f["following_id"] for f in (follows.data or [])]
    if not ids:
        return []
    profiles = _db().table("user_profiles").select("user_id, full_name, username").in_("user_id", ids).execute()
    return profiles.data or []


# ── User stats ────────────────────────────────────────────────────────────────

def get_user_aura(user_id: int) -> int:
    """Aura = upvotes received on user's comments."""
    comments_res = _db().table("comments").select("id").eq("user_id", user_id).execute()
    cids = [c["id"] for c in (comments_res.data or [])]
    if not cids:
        return 0
    votes_res = _db().table("comment_votes").select("vote_type").in_("comment_id", cids).eq("vote_type", "up").execute()
    return len(votes_res.data or [])


def get_user_stats(user_id: int) -> dict:
    q_res = _db().table("questions").select("*", count="exact").eq("user_id", user_id).eq("status", "approved").execute()
    c_res = _db().table("comments").select("*", count="exact").eq("user_id", user_id).execute()
    return {
        "questions": q_res.count or 0,
        "comments":  c_res.count or 0,
        "aura":      get_user_aura(user_id),
    }


# ── Admin settings ────────────────────────────────────────────────────────────

def get_admin_setting(key: str, default: str = "") -> str:
    res = _db().table("admin_settings").select("value").eq("key", key).execute()
    return res.data[0]["value"] if res.data else default


def set_admin_setting(key: str, value: str):
    _db().table("admin_settings").upsert({"key": key, "value": value}, on_conflict="key").execute()


# ── Scheduled posts ───────────────────────────────────────────────────────────

def save_scheduled_post(text: str, photo_file_id, buttons_json: str, pin: bool, scheduled_at: str) -> int:
    res = _db().table("scheduled_posts").insert({
        "text":          text,
        "photo_file_id": photo_file_id,
        "buttons_json":  buttons_json,
        "pin":           int(pin),
        "scheduled_at":  scheduled_at,
        "published":     0,
        "created_at":    datetime.now().isoformat(),
    }).execute()
    return res.data[0]["id"]


def get_pending_scheduled_posts():
    now = datetime.now().isoformat()
    res = (
        _db().table("scheduled_posts")
        .select("*")
        .eq("published", 0)
        .lte("scheduled_at", now)
        .order("scheduled_at")
        .execute()
    )
    return res.data or []


def mark_scheduled_post_published(post_id: int):
    _db().table("scheduled_posts").update({"published": 1}).eq("id", post_id).execute()


# ── Daily limit / spam / duplicate ────────────────────────────────────────────

def get_user_question_count_today(user_id: int) -> int:
    today = date.today().isoformat()
    res = (
        _db().table("questions")
        .select("*", count="exact")
        .eq("user_id", user_id)
        .gte("created_at", today)
        .execute()
    )
    return res.count or 0


def has_submitted_exact(user_id: int, text: str) -> bool:
    res = (
        _db().table("questions")
        .select("id")
        .eq("user_id", user_id)
        .ilike("question", text)
        .limit(1)
        .execute()
    )
    return len(res.data) > 0


def find_duplicate_question(text: str):
    """Return an existing approved question that is very similar, or None."""
    res = _db().table("questions").select("id, question, post_number").eq("status", "approved").execute()
    rows = res.data or []

    words_new = {w.lower() for w in text.split() if len(w) > 3}
    if not words_new:
        return None

    best_score, best_row = 0.0, None
    for row in rows:
        words_ex = {w.lower() for w in (row.get("question") or "").split() if len(w) > 3}
        if not words_ex:
            continue
        common = words_new & words_ex
        score  = len(common) / len(words_new)
        if len(common) >= 3 and score > best_score:
            best_score, best_row = score, row

    return best_row if best_score >= 0.5 else None


# ── User question history ──────────────────────────────────────────────────────

def get_user_questions(user_id: int) -> list:
    res = (
        _db().table("questions")
        .select("id, question, status, post_number, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


# ── Search ────────────────────────────────────────────────────────────────────

def search_questions(keyword: str) -> list:
    res = (
        _db().table("questions")
        .select("id, question, post_number, tag")
        .eq("status", "approved")
        .ilike("question", f"%{keyword}%")
        .order("id", desc=True)
        .limit(10)
        .execute()
    )
    return res.data or []


# ── Broadcast helpers ─────────────────────────────────────────────────────────

def get_all_user_ids() -> list:
    res = _db().table("user_profiles").select("user_id").order("created_at").execute()
    return [r["user_id"] for r in (res.data or [])]


# ── Weekly digest ─────────────────────────────────────────────────────────────

def get_top_questions_week(limit: int = 5) -> list:
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    res = (
        _db().table("questions")
        .select("id, question, post_number, tag, answered_at")
        .eq("status", "approved")
        .gte("answered_at", week_ago)
        .execute()
    )
    questions = res.data or []
    for q in questions:
        cnt = _db().table("comments").select("*", count="exact").eq("question_id", q["id"]).execute()
        q["comment_count"] = cnt.count or 0
    questions.sort(key=lambda x: x["comment_count"], reverse=True)
    return questions[:limit]


# ── Legacy compat ─────────────────────────────────────────────────────────────

def get_comments(question_id: int) -> list:
    res = (
        _db().table("comments")
        .select("full_name, username, comment, created_at")
        .eq("question_id", question_id)
        .order("created_at")
        .execute()
    )
    return [tuple(r.values()) for r in (res.data or [])]
