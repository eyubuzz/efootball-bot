import html
import io
import json
import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import ADMIN_ID, BOT_TOKEN, CHANNEL_ID
from database import (
    ensure_user_profile,
    follow_user,
    get_admin_setting,
    get_comment_count,
    get_comments_page,
    get_discoverable_users,
    get_follower_count,
    get_following_count,
    get_pending_scheduled_posts,
    get_question,
    get_stats,
    get_user_aura,
    get_user_profile,
    get_user_stats,
    init_db,
    is_following,
    mark_scheduled_post_published,
    assign_post_number,
    get_all_questions_export,
    next_post_number,
    reset_questions,
    save_comment,
    save_question,
    save_scheduled_post,
    set_admin_setting,
    set_channel_msg_id,
    set_user_visibility,
    unfollow_user,
    update_status,
    vote_comment,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────────────────────
WAITING_QUESTION   = 1
SCHED_TEXT         = 10
SCHED_TIME         = 11

# ── Constants ─────────────────────────────────────────────────────────────────
COMMENTS_PER_PAGE  = 3
GATE_CHANNEL       = "@ebuzznation"
GATE_CHANNEL_URL   = "https://t.me/ebuzznation"
GATE_CHANNEL_2     = "@ebuzznationqa"
GATE_CHANNEL_2_URL = "https://t.me/ebuzznationqa"

# TAGS: key → (display_label, hashtag)
TAGS = {
    "progression": ("📈 Player Progression",   "#PlayerProgression"),
    "teambuildup": ("🏗️ Team Build-up",        "#TeamBuildup"),
    "general":     ("🔧 General",              "#General"),
    "tactics":     ("🎯 Tactics",              "#Tactics"),
    "manager":     ("👔 Manager",              "#Manager"),
    "gpplayer":    ("⭐ GP Player",             "#GPPlayer"),
    "gpmanager":   ("💼 GP Manager",            "#GPManager"),
    "packs":       ("🎁 Pack Opening",          "#PackOpening"),
    "potw":        ("🏆 POTW",                 "#POTW"),
    "contract":    ("📝 Nominating Contract",   "#NominatingContract"),
    "epoints":     ("💎 eFootball Point",       "#eFootballPoint"),
}

POWERED_BY = '\n\n<b>Powered By <a href="https://t.me/ebuzznation">eBuzzNation</a></b>'

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["✏️ Ask Question"], ["👤 Profile", "🔍 Discover", "ℹ️ Help"]],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Choose an option…",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def tag_selection_keyboard(question_id: int) -> InlineKeyboardMarkup:
    buttons, row = [], []
    for key, (label, _) in TAGS.items():
        row.append(InlineKeyboardButton(label, callback_data=f"settag_{question_id}_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Reject Instead", callback_data=f"reject_{question_id}")])
    return InlineKeyboardMarkup(buttons)


def review_keyboard(question_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏷️ Tag & Approve", callback_data=f"tag_{question_id}"),
        InlineKeyboardButton("❌ Reject",         callback_data=f"reject_{question_id}"),
    ]])


async def _edit_admin_msg(query, text: str, parse_mode: str = None, reply_markup=None):
    """Edit admin notification — handles text, photo, and voice messages."""
    if query.message.photo or query.message.voice or query.message.audio or query.message.document:
        await query.edit_message_caption(caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
    else:
        await query.edit_message_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


async def _try_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_id: int):
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass


async def _delete_last(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Delete the last tracked bot message for this user, if any."""
    msg_id = context.user_data.pop("_last_msg", None)
    if msg_id:
        await _try_delete(context, chat_id, msg_id)


async def _is_subscribed(bot, user_id: int) -> bool:
    for channel in (GATE_CHANNEL, GATE_CHANNEL_2):
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception:
            return False
    return True


async def _send_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the subscription gate message and store its id."""
    await _delete_last(context, update.effective_chat.id)
    sent = await update.message.reply_text(
        "👋 To use this bot you must join *both* channels first.\n\n"
        "1️⃣ Join 👉 *eBuzzNation*\n"
        "2️⃣ Join 👉 *eBuzzNation QA*\n"
        "3️⃣ Tap ✅ *Verify* below",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📢 eBuzzNation",    url=GATE_CHANNEL_URL),
                InlineKeyboardButton("📢 eBuzzNation QA", url=GATE_CHANNEL_2_URL),
            ],
            [InlineKeyboardButton("✅ Verify", callback_data="verify")],
        ]),
    )
    context.user_data["_gate_msg"] = sent.message_id


def build_comments_view(question_id: int, page: int, bot_username: str):
    """Return (text, keyboard) for the given comments page."""
    row = get_question(question_id)
    if not row:
        return "⚠️ Question not found.", InlineKeyboardMarkup([])

    tag_info    = TAGS.get(row["tag"] or "", ("", ""))
    tag_label   = tag_info[0]
    tag_hashtag = tag_info[1]
    post_num    = row["post_number"] or question_id

    comments, total = get_comments_page(question_id, page, COMMENTS_PER_PAGE)
    total_pages = max(1, (total + COMMENTS_PER_PAGE - 1) // COMMENTS_PER_PAGE)
    page = max(1, min(page, total_pages))

    lines = [f"💬 *Question #{post_num} — Comments*"]
    if tag_label:
        lines.append(f"🏷️ _{tag_label}_  {tag_hashtag}")
    lines.append(f"📄 Page {page}/{total_pages}  ·  {total} comment{'s' if total != 1 else ''}")
    lines.append("━" * 22)

    if not comments:
        lines.append("\n_No comments yet — be the first!_")
    else:
        for i, c in enumerate(comments, 1):
            aura = get_user_aura(c["user_id"])
            name = c["full_name"] or "Anonymous"
            # Media indicator
            if c.get("voice_file_id"):
                body = "🎤 _Voice message_"
            elif c.get("photo_file_id"):
                body = "📷 _Photo_"
            else:
                body = c["comment"] or ""
            lines.append(f"\n*{i}.* 👤 *{name}*  ⚡{aura}")
            lines.append(body)

    lines.append("\n" + "━" * 22)
    text = "\n".join(lines)

    buttons = []

    # Vote + reply row per comment
    for i, c in enumerate(comments, 1):
        buttons.append([
            InlineKeyboardButton(f"👍 {c['likes']}",    callback_data=f"up_{c['id']}_{question_id}_{page}"),
            InlineKeyboardButton(f"👎 {c['dislikes']}", callback_data=f"dn_{c['id']}_{question_id}_{page}"),
            InlineKeyboardButton(f"↩️ #{i}",            callback_data=f"rp_{c['id']}_{question_id}_{page}"),
        ])

    # Navigation
    nav = [
        InlineKeyboardButton("⬅️", callback_data=f"vc_{question_id}_{page - 1}") if page > 1          else InlineKeyboardButton(" ", callback_data="noop"),
        InlineKeyboardButton(f"{page}/{total_pages}",  callback_data="noop"),
        InlineKeyboardButton("➡️", callback_data=f"vc_{question_id}_{page + 1}") if page < total_pages else InlineKeyboardButton(" ", callback_data="noop"),
    ]
    buttons.append(nav)

    # Add comment — separate row
    buttons.append([InlineKeyboardButton("✏️ Add Comment", callback_data=f"ac_{question_id}")])

    return text, InlineKeyboardMarkup(buttons)


def _channel_keyboard(question_id: int, count: int, bot_username: str) -> InlineKeyboardMarkup:
    """Two-button keyboard for channel posts: View Comments | Add Comment."""
    link_view = f"https://t.me/{bot_username}?start=c_{question_id}"
    link_add  = f"https://t.me/{bot_username}?start=a_{question_id}"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"💬 Comments ({count})", url=link_view),
        InlineKeyboardButton("✏️ Add Comment",          url=link_add),
    ]])


async def update_channel_button(context: ContextTypes.DEFAULT_TYPE, question_id: int):
    """Edit the channel post buttons to show the updated comment count."""
    row = get_question(question_id)
    if not row or not row["channel_msg_id"]:
        return
    count = get_comment_count(question_id)
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=CHANNEL_ID,
            message_id=row["channel_msg_id"],
            reply_markup=_channel_keyboard(question_id, count, context.bot.username),
        )
    except Exception as e:
        logger.warning("Could not update channel button: %s", e)


# ── /start ────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await _is_subscribed(context.bot, user.id):
        await _send_gate(update, context)
        return
    ensure_user_profile(user.id, user.full_name or "Unknown", user.username or "")

    args = context.args

    # Deep-link: /start c_<question_id>  → view comments
    if args and args[0].startswith("c_"):
        try:
            question_id = int(args[0][2:])
        except ValueError:
            question_id = None
        if question_id:
            row = get_question(question_id)
            if not row:
                sent = await update.message.reply_text(
                    "⚠️ This question is no longer available.",
                    reply_markup=MAIN_KEYBOARD,
                )
                context.user_data["_last_msg"] = sent.message_id
                return
            text, keyboard = build_comments_view(question_id, 1, context.bot.username)
            sent = await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
            context.user_data["_last_msg"] = sent.message_id
            return

    # Deep-link: /start a_<question_id>  → go straight to add comment
    if args and args[0].startswith("a_"):
        try:
            question_id = int(args[0][2:])
        except ValueError:
            question_id = None
        if question_id:
            row = get_question(question_id)
            if row and row["status"] == "approved":
                context.user_data["_awaiting_comment_qid"] = question_id
                sent = await update.message.reply_text(
                    f"✏️ *Add comment to Question #{row['post_number'] or question_id}*\n\n"
                    f"Send your text, 🎤 voice, or 📷 photo (3–500 chars for text).\n"
                    f"Send /cancel to go back.",
                    parse_mode="Markdown",
                )
                context.user_data["_conv_prompt"] = sent.message_id
                return
            # Question not found or not approved
            sent = await update.message.reply_text(
                "⚠️ This question is no longer available.",
                reply_markup=MAIN_KEYBOARD,
            )
            context.user_data["_last_msg"] = sent.message_id
            return

    # Deep-link: /start u_<user_id>
    if args and args[0].startswith("u_"):
        try:
            target_id = int(args[0][2:])
        except ValueError:
            target_id = None
        if target_id:
            await _show_user_card(update, context, target_id)
            return

    await _delete_last(context, update.effective_chat.id)
    sent = await update.message.reply_text(
        "👋 *Welcome to the eFootball Q&A Bot!*\n\n"
        "Ask questions about team building, formations, packs & more.\n\n"
        "Use the menu below to get started 👇",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )
    context.user_data["_last_msg"] = sent.message_id


# ── Help ──────────────────────────────────────────────────────────────────────

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _is_subscribed(context.bot, update.effective_user.id):
        await _send_gate(update, context)
        return
    await _delete_last(context, update.effective_chat.id)
    sent = await update.message.reply_text(
        "📖 *How to use this bot:*\n\n"
        "✏️ *Ask Question* — send text, 📷 photo, or 🎤 voice.\n"
        "💬 *View Comments* — tap under any channel post to browse comments.\n"
        "✏️ *Add Comment* — tap the button to reply instantly (text, photo, or voice).\n"
        "👍 / 👎 — vote on comments to earn / give *Aura* points.\n"
        "👤 *Profile* — see your stats and Aura.\n\n"
        "*Topic tags:*\n"
        "📈 #PlayerProgression · 🏗️ #TeamBuildup · 🔧 #General\n"
        "🎯 #Tactics · 👔 #Manager · ⭐ #GPPlayer · 💼 #GPManager\n"
        "🎁 #PackOpening · 🏆 #POTW · 📝 #NominatingContract · 💎 #eFootballPoint",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )
    context.user_data["_last_msg"] = sent.message_id


# ── User card helper ──────────────────────────────────────────────────────────

async def _show_user_card(update: Update, context: ContextTypes.DEFAULT_TYPE, target_id: int):
    profile = get_user_profile(target_id)
    if not profile or not profile["visible"]:
        await update.message.reply_text("⚠️ This profile is private or doesn't exist.", reply_markup=MAIN_KEYBOARD)
        return
    stats     = get_user_stats(target_id)
    followers = get_follower_count(target_id)
    following = get_following_count(target_id)
    name      = profile["full_name"] or "Unknown"
    uname     = f"@{profile['username']}" if profile["username"] else ""
    viewer_id = update.effective_user.id
    already   = is_following(viewer_id, target_id)
    btn_label = "➖ Unfollow" if already else "➕ Follow"
    keyboard  = InlineKeyboardMarkup([[
        InlineKeyboardButton(btn_label, callback_data=f"follow_{target_id}"),
    ]]) if viewer_id != target_id else None
    await update.message.reply_text(
        f"👤 *{name}* {uname}\n"
        f"──────────────────\n"
        f"⚡ Aura:      *{stats['aura']}*\n"
        f"❓ Questions: *{stats['questions']}*\n"
        f"💬 Comments:  *{stats['comments']}*\n"
        f"👥 Followers: *{followers}*  Following: *{following}*",
        parse_mode="Markdown",
        reply_markup=keyboard or MAIN_KEYBOARD,
    )


# ── Profile ───────────────────────────────────────────────────────────────────

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    if not await _is_subscribed(context.bot, user.id):
        await _send_gate(update, context)
        return
    ensure_user_profile(user.id, user.full_name or "Unknown", user.username or "")
    stats     = get_user_stats(user.id)
    profile   = get_user_profile(user.id)
    followers = get_follower_count(user.id)
    following = get_following_count(user.id)
    name      = user.full_name or "Unknown"
    visible   = profile["visible"] if profile else 0
    vis_label = "🔓 Make Private" if visible else "🔒 Make Discoverable"
    await _delete_last(context, update.effective_chat.id)
    sent = await update.message.reply_text(
        f"👤 *{name}*\n"
        f"──────────────────\n"
        f"⚡ Aura:           *{stats['aura']}*\n"
        f"❓ Questions posted: *{stats['questions']}*\n"
        f"💬 Comments made:   *{stats['comments']}*\n"
        f"👥 Followers: *{followers}*  Following: *{following}*\n\n"
        f"_Aura is earned when others upvote your comments._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(vis_label, callback_data="toggle_visibility"),
        ]]),
    )
    context.user_data["_last_msg"] = sent.message_id


# ── Discover ──────────────────────────────────────────────────────────────────

def _discover_keyboard(page: int, total: int, per_page: int = 5) -> InlineKeyboardMarkup:
    total_pages = max(1, (total + per_page - 1) // per_page)
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"disc_{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"disc_{page + 1}"))
    return InlineKeyboardMarkup([nav]) if nav else InlineKeyboardMarkup([])


async def discover_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await _is_subscribed(context.bot, user.id):
        await _send_gate(update, context)
        return
    ensure_user_profile(user.id, user.full_name or "Unknown", user.username or "")
    users, total = get_discoverable_users(user.id, page=1)
    await _delete_last(context, update.effective_chat.id)
    if not users:
        sent = await update.message.reply_text(
            "🔍 No discoverable users yet.\n\nMake your profile public via 👤 *Profile* to appear here.",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
        context.user_data["_last_msg"] = sent.message_id
        return
    lines = ["🔍 *Discover Players*\n"]
    bot_username = context.bot.username
    for u in users:
        name  = u["full_name"] or "Unknown"
        uname = f" (@{u['username']})" if u["username"] else ""
        link  = f"https://t.me/{bot_username}?start=u_{u['user_id']}"
        lines.append(f"• [{name}{uname}]({link})")
    sent = await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=_discover_keyboard(1, total),
    )
    context.user_data["_last_msg"] = sent.message_id


# ── Admin: schedule post (conversation) ───────────────────────────────────────

async def sched_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return ConversationHandler.END
    await _delete_last(context, update.effective_chat.id)
    sent = await update.message.reply_text(
        "📅 *Schedule a Channel Post*\n\n"
        "Send the post text (or a photo with caption).\n"
        "Send /cancel to abort.",
        parse_mode="Markdown",
    )
    context.user_data["_conv_prompt"] = sent.message_id
    return SCHED_TEXT


async def sched_receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sched_text"] = update.message.text.strip()
    context.user_data["sched_photo"] = None
    prompt_id = context.user_data.pop("_conv_prompt", None)
    if prompt_id:
        await _try_delete(context, update.effective_chat.id, prompt_id)
    sent = await update.message.reply_text(
        "⏰ When should it be posted?\n\n"
        "Send date/time in format: `YYYY-MM-DD HH:MM` (24h, UTC)\n"
        "Example: `2026-04-01 18:00`",
        parse_mode="Markdown",
    )
    context.user_data["_conv_prompt"] = sent.message_id
    return SCHED_TIME


async def sched_receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = (update.message.caption or "").strip()
    context.user_data["sched_text"] = caption
    context.user_data["sched_photo"] = update.message.photo[-1].file_id
    prompt_id = context.user_data.pop("_conv_prompt", None)
    if prompt_id:
        await _try_delete(context, update.effective_chat.id, prompt_id)
    sent = await update.message.reply_text(
        "⏰ When should it be posted?\n\n"
        "Send date/time in format: `YYYY-MM-DD HH:MM` (UTC)\n"
        "Example: `2026-04-01 18:00`",
        parse_mode="Markdown",
    )
    context.user_data["_conv_prompt"] = sent.message_id
    return SCHED_TIME


async def sched_receive_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime as dt
    raw = update.message.text.strip()
    try:
        scheduled_at = dt.strptime(raw, "%Y-%m-%d %H:%M").isoformat()
    except ValueError:
        await update.message.reply_text("⚠️ Invalid format. Use `YYYY-MM-DD HH:MM`.", parse_mode="Markdown")
        return SCHED_TIME
    prompt_id = context.user_data.pop("_conv_prompt", None)
    if prompt_id:
        await _try_delete(context, update.effective_chat.id, prompt_id)
    text  = context.user_data.get("sched_text", "")
    photo = context.user_data.get("sched_photo")
    pid = save_scheduled_post(
        text=text,
        photo_file_id=photo,
        buttons_json=json.dumps([]),
        pin=False,
        scheduled_at=scheduled_at,
    )
    conf = await update.message.reply_text(
        f"✅ *Post #{pid} scheduled for {raw} UTC.*",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )
    context.user_data["_last_msg"] = conf.message_id
    return ConversationHandler.END


# ── Ask Question (conversation) ───────────────────────────────────────────────

async def ask_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await _is_subscribed(context.bot, user.id):
        await _send_gate(update, context)
        return WAITING_QUESTION
    ensure_user_profile(user.id, user.full_name or "Unknown", user.username or "")
    await _delete_last(context, update.effective_chat.id)
    sent = await update.message.reply_text(
        "✏️ *What's your eFootball question?*\n\n"
        "Send text (10–600 chars), a 📷 photo with caption, or a 🎤 voice message.\n"
        "Send /cancel to go back.",
        parse_mode="Markdown",
    )
    context.user_data["_conv_prompt"] = sent.message_id
    return WAITING_QUESTION


async def _submit_question(update, context, text: str,
                           photo_file_id: str = None, voice_file_id: str = None):
    """Save question, confirm to user, and notify admin."""
    user = update.effective_user
    qid = save_question(
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name or "Unknown",
        question=text,
        photo_file_id=photo_file_id,
        voice_file_id=voice_file_id,
    )

    prompt_id = context.user_data.pop("_conv_prompt", None)
    if prompt_id:
        await _try_delete(context, update.effective_chat.id, prompt_id)

    conf = await update.message.reply_text(
        f"✅ *Question submitted!*\n\n"
        f"🆔 ID: `#{qid}`\n"
        f"⏳ Pending admin review — you'll be notified once it's posted.",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )
    context.user_data["_last_msg"] = conf.message_id

    user_tag      = f" (@{user.username})" if user.username else ""
    admin_caption = (
        f"🔔 *New Question — #{qid}*\n\n"
        f"👤 *From:* {user.full_name}{user_tag}\n"
        f"🆔 *User ID:* `{user.id}`\n\n"
        f"❓ *Question:*\n{text}"
    )
    if photo_file_id:
        await context.bot.send_photo(
            chat_id=ADMIN_ID, photo=photo_file_id,
            caption=admin_caption, reply_markup=review_keyboard(qid), parse_mode="Markdown",
        )
    elif voice_file_id:
        await context.bot.send_voice(
            chat_id=ADMIN_ID, voice=voice_file_id,
            caption=admin_caption, reply_markup=review_keyboard(qid), parse_mode="Markdown",
        )
    else:
        await context.bot.send_message(
            chat_id=ADMIN_ID, text=admin_caption,
            reply_markup=review_keyboard(qid), parse_mode="Markdown",
        )
    return ConversationHandler.END


async def ask_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if len(text) < 10:
        await update.message.reply_text("⚠️ Too short — add more detail and try again.")
        return WAITING_QUESTION

    if len(text) > 600:
        await update.message.reply_text("⚠️ Too long (max 600 chars). Please shorten your question.")
        return WAITING_QUESTION

    return await _submit_question(update, context, text)


async def ask_receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = (update.message.caption or "").strip()

    if len(caption) < 10:
        await update.message.reply_text(
            "⚠️ Please add a caption describing your question (min 10 characters).\n"
            "Send the photo again with a caption, or just type your question as text."
        )
        return WAITING_QUESTION

    if len(caption) > 600:
        await update.message.reply_text("⚠️ Caption too long (max 600 chars). Please shorten it.")
        return WAITING_QUESTION

    photo_file_id = update.message.photo[-1].file_id
    return await _submit_question(update, context, caption, photo_file_id)


async def ask_receive_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice_file_id = update.message.voice.file_id
    return await _submit_question(update, context, "🎤 Voice question", voice_file_id=voice_file_id)


# ── Add Comment (user_data flag approach — avoids ConversationHandler/callback issues) ──

async def _open_comment_prompt(query, context: ContextTypes.DEFAULT_TYPE, question_id: int, label: str):
    """Set the awaiting-comment flag and send the prompt."""
    row = get_question(question_id)
    display_num = (row["post_number"] or question_id) if row else question_id
    context.user_data["_awaiting_comment_qid"] = question_id
    sent = await query.message.reply_text(
        f"{label} *Question #{display_num}*\n\n"
        f"Send your text, 🎤 voice, or 📷 photo.\n"
        f"Send /cancel to go back.",
        parse_mode="Markdown",
    )
    context.user_data["_conv_prompt"] = sent.message_id


async def comment_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text/voice/photo comment when the user is in awaiting-comment state."""
    question_id = context.user_data.get("_awaiting_comment_qid")
    if not question_id:
        return  # not waiting for a comment — let other handlers deal with it

    msg = update.message

    # Determine comment type
    photo_file_id = None
    voice_file_id = None
    text_body     = ""

    if msg.voice:
        voice_file_id = msg.voice.file_id
    elif msg.photo:
        photo_file_id = msg.photo[-1].file_id
        text_body     = (msg.caption or "").strip()
    else:
        text_body = (msg.text or "").strip()
        if len(text_body) < 3:
            await msg.reply_text("⚠️ Too short. Try again.")
            return
        if len(text_body) > 500:
            await msg.reply_text("⚠️ Too long (max 500 chars). Please shorten.")
            return

    # Validate question still exists
    if not get_question(question_id):
        context.user_data.pop("_awaiting_comment_qid", None)
        context.user_data.pop("_conv_prompt", None)
        sent = await msg.reply_text(
            "⚠️ This question is no longer available.",
            reply_markup=MAIN_KEYBOARD,
        )
        context.user_data["_last_msg"] = sent.message_id
        return

    # Clear state
    context.user_data.pop("_awaiting_comment_qid", None)
    prompt_id = context.user_data.pop("_conv_prompt", None)
    if prompt_id:
        await _try_delete(context, update.effective_chat.id, prompt_id)

    user = update.effective_user
    save_comment(
        question_id=question_id,
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name or "Unknown",
        comment=text_body,
        photo_file_id=photo_file_id,
        voice_file_id=voice_file_id,
    )

    await update_channel_button(context, question_id)

    row = get_question(question_id)
    if row and row["user_id"] != user.id:
        kind = "🎤 voice message" if voice_file_id else ("📷 photo" if photo_file_id else text_body)
        try:
            await context.bot.send_message(
                chat_id=row["user_id"],
                text=(
                    f"💬 *New comment on your Question #{row['post_number'] or question_id}!*\n\n"
                    f"👤 {user.full_name}: {kind}"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass

    count    = get_comment_count(question_id)
    bot_link = f"https://t.me/{context.bot.username}?start=c_{question_id}"
    conf = await msg.reply_text(
        f"✅ *Comment posted!*\n\n"
        f"[View all {count} comment{'s' if count != 1 else ''}]({bot_link})",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
        disable_web_page_preview=True,
    )
    context.user_data["_last_msg"] = conf.message_id


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt_id = context.user_data.pop("_conv_prompt", None)
    if prompt_id:
        await _try_delete(context, update.effective_chat.id, prompt_id)
    await _delete_last(context, update.effective_chat.id)
    context.user_data.clear()
    sent = await update.message.reply_text("Cancelled.", reply_markup=MAIN_KEYBOARD)
    context.user_data["_last_msg"] = sent.message_id
    return ConversationHandler.END


# ── Inline callbacks ──────────────────────────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data  = query.data

    # No-op button (page indicator)
    if data == "noop":
        await query.answer()
        return

    # ── Subscription gate: verify ──
    if data == "verify":
        if not await _is_subscribed(context.bot, query.from_user.id):
            await query.answer("❌ You haven't joined yet. Please join first!", show_alert=True)
            return
        # Delete the gate message
        gate_id = context.user_data.pop("_gate_msg", None)
        if gate_id:
            await _try_delete(context, query.message.chat_id, gate_id)
        await query.answer("✅ Verified!")
        # Show welcome
        ensure_user_profile(query.from_user.id, query.from_user.full_name or "Unknown", query.from_user.username or "")
        sent = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="✅ *Verified! Welcome to the eFootball Q&A Bot.*\n\nUse the menu below 👇",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
        context.user_data["_last_msg"] = sent.message_id
        return

    # ── Add comment ──
    if data.startswith("ac_"):
        question_id = int(data.split("_", 1)[1])
        row = get_question(question_id)
        if not row or row["status"] != "approved":
            await query.answer("⚠️ Question not available.", show_alert=True)
            return
        await query.answer()
        await _open_comment_prompt(query, context, question_id, "💬 *Adding comment to*")
        return

    # ── Reply to comment ──
    if data.startswith("rp_"):
        _, cid, qid, page = data.split("_")
        question_id = int(qid)
        row = get_question(question_id)
        if not row or row["status"] != "approved":
            await query.answer("⚠️ Question not available.", show_alert=True)
            return
        await query.answer()
        await _open_comment_prompt(query, context, question_id, "↩️ *Replying on*")
        return

    # ── View / navigate comments ──
    if data.startswith("vc_"):
        await query.answer()
        _, qid, page = data.split("_")
        text, keyboard = build_comments_view(int(qid), int(page), context.bot.username)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
        return

    # ── Vote up ──
    if data.startswith("up_"):
        _, cid, qid, page = data.split("_")
        likes, dislikes = vote_comment(int(cid), query.from_user.id, "up")
        await query.answer(f"👍 {likes}")
        text, keyboard = build_comments_view(int(qid), int(page), context.bot.username)
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
        except Exception:
            pass
        return

    # ── Vote down ──
    if data.startswith("dn_"):
        _, cid, qid, page = data.split("_")
        likes, dislikes = vote_comment(int(cid), query.from_user.id, "down")
        await query.answer(f"👎 {dislikes}")
        text, keyboard = build_comments_view(int(qid), int(page), context.bot.username)
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
        except Exception:
            pass
        return

    # ── Admin: show tag picker ──
    if data.startswith("tag_"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("⛔ Not authorized.", show_alert=True)
            return
        await query.answer()
        question_id = int(data.split("_", 1)[1])
        row = get_question(question_id)
        if not row:
            await _edit_admin_msg(query, "⚠️ Question not found.")
            return
        if row["status"] != "pending":
            await _edit_admin_msg(query, f"⚠️ Already {row['status']}.")
            return
        await _edit_admin_msg(
            query,
            f"🏷️ *Select tag for Question #{question_id}*\n\n"
            f"👤 {row['full_name']}\n"
            f"❓ {row['question']}\n\n"
            f"Choose the best topic:",
            parse_mode="Markdown",
            reply_markup=tag_selection_keyboard(question_id),
        )
        return

    # ── Admin: set tag & approve ──
    if data.startswith("settag_"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("⛔ Not authorized.", show_alert=True)
            return
        await query.answer()
        _, question_id, tag_key = data.split("_", 2)
        question_id = int(question_id)
        row = get_question(question_id)
        if not row:
            await _edit_admin_msg(query, "⚠️ Question not found.")
            return
        if row["status"] != "pending":
            await _edit_admin_msg(query, f"⚠️ Already {row['status']}.")
            return

        tag_label, tag_hashtag = TAGS.get(tag_key, ("🔧 General", "#General"))
        post_num = next_post_number()
        update_status(question_id, "approved", tag_key)
        assign_post_number(question_id, post_num)

        q_text = html.escape(row['question'])
        channel_caption = (
            f"❓ <b>eFootball Question #{post_num}</b>\n\n"
            f"{q_text}\n\n"
            f"{tag_hashtag}"
            f"{POWERED_BY}"
        )
        btn      = _channel_keyboard(question_id, 0, context.bot.username)
        bot_link = f"https://t.me/{context.bot.username}?start=c_{question_id}"

        # Post to channel — photo, voice, or text
        if row["voice_file_id"]:
            msg = await context.bot.send_voice(
                chat_id=CHANNEL_ID,
                voice=row["voice_file_id"],
                caption=channel_caption,
                parse_mode="HTML",
                reply_markup=btn,
            )
        elif row["photo_file_id"]:
            msg = await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=row["photo_file_id"],
                caption=channel_caption,
                parse_mode="HTML",
                reply_markup=btn,
            )
        else:
            msg = await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=channel_caption,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=btn,
            )
        set_channel_msg_id(question_id, msg.message_id)

        # Notify question author
        try:
            await context.bot.send_message(
                chat_id=row["user_id"],
                text=(
                    f"🎉 *Your question was approved and posted!*\n\n"
                    f"🏷️ Tag: {tag_label}\n"
                    f"❓ {row['question']}\n\n"
                    f"[View comments]({bot_link})"
                ),
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        except Exception:
            pass

        await _edit_admin_msg(
            query,
            f"✅ *Approved & Posted — Channel #{post_num}*\n\n"
            f"🏷️ {tag_label}\n"
            f"👤 {row['full_name']}\n"
            f"❓ {row['question']}\n\n"
            f"📢 Posted to channel.",
            parse_mode="Markdown",
        )
        return

    # ── Admin: reject ──
    if data.startswith("reject_"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("⛔ Not authorized.", show_alert=True)
            return
        await query.answer()
        question_id = int(data.split("_", 1)[1])
        row = get_question(question_id)
        if not row:
            await _edit_admin_msg(query, "⚠️ Question not found.")
            return
        if row["status"] != "pending":
            await _edit_admin_msg(query, f"⚠️ Already {row['status']}.")
            return
        update_status(question_id, "rejected")
        try:
            await context.bot.send_message(
                chat_id=row["user_id"],
                text=(
                    f"❌ *Your question wasn't approved this time.*\n\n"
                    f"❓ {row['question']}\n\n"
                    f"Feel free to rephrase and submit again!"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass
        await _edit_admin_msg(
            query,
            f"❌ *Rejected — #{question_id}*\n\n"
            f"👤 {row['full_name']}\n"
            f"❓ {row['question']}",
            parse_mode="Markdown",
        )
        return

    # ── Toggle profile visibility ──
    if data == "toggle_visibility":
        uid     = query.from_user.id
        profile = get_user_profile(uid)
        if not profile:
            ensure_user_profile(uid, query.from_user.full_name or "Unknown", query.from_user.username or "")
            profile = get_user_profile(uid)
        new_vis = not bool(profile["visible"])
        set_user_visibility(uid, new_vis)
        label = "🔓 Make Private" if new_vis else "🔒 Make Discoverable"
        status = "public — others can discover you 🔓" if new_vis else "private 🔒"
        await query.answer(f"Profile is now {status}", show_alert=True)
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(label, callback_data="toggle_visibility"),
                ]])
            )
        except Exception:
            pass
        return

    # ── Follow / unfollow ──
    if data.startswith("follow_"):
        viewer_id = query.from_user.id
        target_id = int(data.split("_", 1)[1])
        if viewer_id == target_id:
            await query.answer("That's you!", show_alert=True)
            return
        if is_following(viewer_id, target_id):
            unfollow_user(viewer_id, target_id)
            await query.answer("Unfollowed.")
            new_label = "➕ Follow"
        else:
            follow_user(viewer_id, target_id)
            await query.answer("Following!")
            new_label = "➖ Unfollow"
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(new_label, callback_data=f"follow_{target_id}"),
                ]])
            )
        except Exception:
            pass
        return

    # ── Discover pagination ──
    if data.startswith("disc_"):
        await query.answer()
        page = int(data.split("_", 1)[1])
        users, total = get_discoverable_users(query.from_user.id, page=page)
        bot_username = context.bot.username
        lines = [f"🔍 *Discover Players* (page {page})\n"]
        for u in users:
            name  = u["full_name"] or "Unknown"
            uname = f" (@{u['username']})" if u["username"] else ""
            link  = f"https://t.me/{bot_username}?start=u_{u['user_id']}"
            lines.append(f"• [{name}{uname}]({link})")
        try:
            await query.edit_message_text(
                "\n".join(lines),
                parse_mode="Markdown",
                disable_web_page_preview=True,
                reply_markup=_discover_keyboard(page, total),
            )
        except Exception:
            pass
        return

    await query.answer()


# ── Admin: stats ──────────────────────────────────────────────────────────────

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return
    data     = get_stats()
    pending  = data.get("pending",  0)
    approved = data.get("approved", 0)
    rejected = data.get("rejected", 0)
    await update.message.reply_text(
        f"📊 *Bot Statistics*\n\n"
        f"⏳ Pending:  {pending}\n"
        f"✅ Approved: {approved}\n"
        f"❌ Rejected: {rejected}\n"
        f"──────────────\n"
        f"📝 Total:    {pending + approved + rejected}",
        parse_mode="Markdown",
    )


# ── Admin: PDF export ─────────────────────────────────────────────────────────

async def pdf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return

    from fpdf import FPDF

    questions = get_all_questions_export()
    if not questions:
        await update.message.reply_text("No questions in the database yet.")
        return

    status_counts = {}
    for q in questions:
        status_counts[q["status"]] = status_counts.get(q["status"], 0) + 1

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "eFootball Q&A Bot — Questions Export", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    from datetime import datetime as dt
    pdf.cell(0, 6, f"Generated: {dt.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  |  "
             f"Total: {len(questions)}  |  "
             f"Approved: {status_counts.get('approved', 0)}  |  "
             f"Pending: {status_counts.get('pending', 0)}  |  "
             f"Rejected: {status_counts.get('rejected', 0)}",
             ln=True, align="C")
    pdf.ln(4)

    STATUS_ICON = {"approved": "✓", "pending": "…", "rejected": "✗"}

    for q in questions:
        channel_num = f"  [Channel #{q['post_number']}]" if q["post_number"] else ""
        icon        = STATUS_ICON.get(q["status"], "?")
        tag         = TAGS.get(q["tag"] or "", ("",))[0] if q["tag"] else ""

        # Question header bar
        pdf.set_fill_color(230, 230, 230)
        pdf.set_font("Helvetica", "B", 11)
        header = f"[{icon}] DB#{q['id']}{channel_num}  —  {q['status'].upper()}"
        if tag:
            header += f"  |  {tag}"
        pdf.cell(0, 8, header, ln=True, fill=True)

        # Submitter + date
        pdf.set_font("Helvetica", "I", 9)
        uname = f" (@{q['username']})" if q["username"] else ""
        date  = (q["created_at"] or "")[:16].replace("T", " ")
        pdf.cell(0, 5, f"From: {q['full_name']}{uname}   Date: {date}   Comments: {q['comment_count']}", ln=True)

        # Question text
        pdf.set_font("Helvetica", "", 10)
        safe = q["question"].encode("latin-1", errors="replace").decode("latin-1")
        pdf.multi_cell(0, 6, safe)
        pdf.ln(3)

    buf = io.BytesIO(pdf.output())
    buf.name = "questions_export.pdf"
    await update.message.reply_document(
        document=buf,
        filename="questions_export.pdf",
        caption=f"📄 Questions export — {len(questions)} total",
    )


# ── Admin: reset DB ───────────────────────────────────────────────────────────

async def resetdb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return
    # Require confirmation argument: /resetdb confirm
    if not context.args or context.args[0] != "confirm":
        await update.message.reply_text(
            "⚠️ This will delete *all* questions, comments, and votes.\n\n"
            "To confirm, send: `/resetdb confirm`",
            parse_mode="Markdown",
        )
        return
    reset_questions()
    await update.message.reply_text("✅ Database reset. Post counter is back to zero.")


# ── Main ──────────────────────────────────────────────────────────────────────

async def unsupported_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚠️ This bot only accepts text or photo messages.\n\n"
        "Use *✏️ Ask Question* to submit your question.",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def publish_scheduled_posts(context: ContextTypes.DEFAULT_TYPE):
    """Job: publish any due scheduled posts to the channel."""
    posts = get_pending_scheduled_posts()
    for post in posts:
        try:
            buttons_data = json.loads(post.get("buttons_json") or "[]")
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(b["text"], url=b["url"]) for b in row]
                for row in buttons_data
            ]) if buttons_data else None

            if post["photo_file_id"]:
                msg = await context.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=post["photo_file_id"],
                    caption=post["text"] or "",
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
            else:
                msg = await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=post["text"] or "",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=keyboard,
                )
            if post.get("pin"):
                try:
                    await context.bot.pin_chat_message(chat_id=CHANNEL_ID, message_id=msg.message_id)
                except Exception:
                    pass
            mark_scheduled_post_published(post["id"])
            logger.info("Published scheduled post #%s", post["id"])
        except Exception as e:
            logger.error("Failed to publish scheduled post #%s: %s", post["id"], e)


def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # Conversation handler: question submission
    ask_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Text(["✏️ Ask Question"]), ask_start),
        ],
        states={
            WAITING_QUESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_receive),
                MessageHandler(filters.PHOTO,                   ask_receive_photo),
                MessageHandler(filters.VOICE,                   ask_receive_voice),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    # Conversation handler: schedule post (admin)
    sched_conv = ConversationHandler(
        entry_points=[CommandHandler("schedule", sched_start)],
        states={
            SCHED_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sched_receive_text),
                MessageHandler(filters.PHOTO, sched_receive_photo),
            ],
            SCHED_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, sched_receive_time)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    # Group 0: comment_receive runs first for text/voice/photo.
    # If no pending comment it exits immediately; groups are independent so ask_conv still fires.
    _comment_filter = (filters.TEXT | filters.VOICE | filters.PHOTO) & ~filters.COMMAND
    app.add_handler(MessageHandler(_comment_filter, comment_receive), group=0)
    app.add_handler(ask_conv,   group=1)
    app.add_handler(sched_conv, group=1)
    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("help",     help_command))
    app.add_handler(CommandHandler("profile",  profile_command))
    app.add_handler(CommandHandler("stats",    stats))
    app.add_handler(CommandHandler("pdf",      pdf_command))
    app.add_handler(CommandHandler("resetdb",  resetdb_command))
    app.add_handler(CommandHandler("discover", discover_command))

    # Reply keyboard shortcuts
    app.add_handler(MessageHandler(filters.Text(["👤 Profile"]),   profile_command))
    app.add_handler(MessageHandler(filters.Text(["🔍 Discover"]),  discover_command))
    app.add_handler(MessageHandler(filters.Text(["ℹ️ Help"]),      help_command))

    # Unsupported media (photos are handled in the ask conversation above)
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL | filters.VOICE | filters.Sticker.ALL, unsupported_media))

    # Inline callback (view, vote, admin approve/reject, follow, discover)
    app.add_handler(CallbackQueryHandler(button_callback))

    # Background job: check for scheduled posts every minute
    app.job_queue.run_repeating(publish_scheduled_posts, interval=60, first=10)

    logger.info("eFootball bot is running…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
